"use client";

/**
 * AI 채팅 상태 — 대화 메시지·표·지금 보는 표·오른쪽 패널(결과/문서 보기). 문서 작성 화면 상태(jotai)와 섞지 않는다.
 * 첫 메시지를 보낼 때 대화를 만들고(onCreated 로 주소를 바꾼다), 한 턴은 SSE(table_update 로 표가 행마다 갱신된다).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { ApiError, getDocuments } from "../report/api";
import { errorText } from "../report/hooks/useReportStudio";
import { streamPost } from "../report/stream";
import type { DocumentCard, StreamError, ToolRun } from "../report/types";
import { cancelChatTurn, chatTurnPath, createChat, getChat, getTable } from "./api";
import type { ResearchEvent, ResearchMessage, ResearchTable } from "./types";

let seq = 0;
const nextId = () => `l${Date.now().toString(36)}${(seq++).toString(36)}`;

export interface Viewing {
  docId: string;
  chunk?: string;
  cell?: [number, number] | null;
  tick: number;
}

export function useResearch(workspaceId: string, chatId: string | null, tableId: string | null, onCreated: (id: string) => void) {
  const [messages, setMessages] = useState<ResearchMessage[]>([]);
  const [tables, setTables] = useState<ResearchTable[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [viewing, setViewing] = useState<Viewing | null>(null);
  const [tab, setTab] = useState<"result" | "viewer">("result");
  const [docs, setDocs] = useState<Record<string, DocumentCard>>({});
  const [loading, setLoading] = useState(false);
  const chatRef = useRef<string | null>(chatId);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    void getDocuments(workspaceId)
      .then((d) => setDocs(Object.fromEntries((d.documents ?? []).map((x) => [x.id, x]))))
      .catch(() => undefined);
  }, [workspaceId]);

  // 대화 열기 — 방금 만든 대화(보내는 중)는 다시 불러오지 않는다
  useEffect(() => {
    if (chatId && chatId === chatRef.current && messages.length) return;
    chatRef.current = chatId;
    abortRef.current?.abort();
    setViewing(null);
    setTab("result");
    if (!chatId) {
      setMessages([]);
      setTables([]);
      setActiveId(null);
      setTitle("");
      return;
    }
    let cancelled = false;
    setLoading(true);
    void getChat(chatId)
      .then((p) => {
        if (cancelled) return;
        setMessages(
          p.messages.map((m) => ({
            ...m,
            text: m.text ?? "",
            streaming: false,
          })),
        );
        setTables(p.tables);
        setTitle(p.chat.title);
        setActiveId(p.chat.currentTableId ?? p.tables[p.tables.length - 1]?.id ?? null);
      })
      .catch(
        () =>
          !cancelled &&
          toast.error("대화를 불러오지 못했습니다.", {
            position: "top-center",
          }),
      )
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [chatId]);

  // 드라이브에서 연 표(?t=)
  useEffect(() => {
    if (!tableId) return;
    let cancelled = false;
    void getTable(tableId)
      .then((t) => {
        if (cancelled) return;
        upsert(t);
        setActiveId(t.id);
        setTab("result");
      })
      .catch(() => !cancelled && toast.error("표를 열지 못했습니다.", { position: "top-center" }));
    return () => {
      cancelled = true;
    };
  }, [tableId]);

  const upsert = (t: ResearchTable) => setTables((prev) => (prev.some((x) => x.id === t.id) ? prev.map((x) => (x.id === t.id ? t : x)) : [...prev, t]));
  const patch = (id: string, fn: (m: ResearchMessage) => ResearchMessage) => setMessages((prev) => prev.map((m) => (m.id === id ? fn(m) : m)));

  const apply = useCallback((msgId: string, e: ResearchEvent) => {
    switch (e.type) {
      case "status":
        setStage(e.stage);
        break;
      case "text":
        setStage("respond");
        patch(msgId, (m) => ({ ...m, text: m.text + e.delta }));
        break;
      case "text_replace":
        patch(msgId, (m) => ({ ...m, text: e.text }));
        break;
      case "tool_start": {
        const tool: ToolRun = {
          id: e.id,
          name: e.name,
          args: e.args,
          status: "running",
        };
        setStage(`tool:${e.name}`);
        patch(msgId, (m) => ({ ...m, tools: [...(m.tools ?? []), tool] }));
        break;
      }
      case "tool_end":
        setStage("think");
        patch(msgId, (m) => ({
          ...m,
          tools: (m.tools ?? []).map((x) => (x.id === e.id ? { ...x, status: e.status, summary: e.summary } : x)),
        }));
        break;
      case "table_update":
        upsert(e.table);
        setActiveId(e.table.id);
        setTab("result");
        patch(msgId, (m) => ({
          ...m,
          tables: [...(m.tables ?? []).filter((x) => x.id !== e.table.id), { id: e.table.id, title: e.table.title }],
        }));
        break;
      case "template_saved":
        toast.success(`양식 '${e.template.name}' 을 저장했습니다.`, {
          position: "top-center",
        });
        break;
      case "error":
        patch(msgId, (m) => ({
          ...m,
          error: { code: e.code, message: e.message },
        }));
        break;
      case "done":
        setStage(null);
        setStreaming(false);
        patch(msgId, (m) => ({ ...m, streaming: false }));
        break;
      default:
        break;
    }
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || streaming) return;
      let id = chatRef.current;
      const asstId = nextId();
      setMessages((prev) => [...prev, { id: nextId(), role: "user", text: trimmed }, { id: asstId, role: "assistant", text: "", streaming: true }]);
      setStreaming(true);
      setStage("route");
      if (!id) {
        try {
          const p = await createChat(workspaceId);
          id = p.chat.id;
          chatRef.current = id;
          onCreated(id);
        } catch (e) {
          patch(asstId, (m) => ({
            ...m,
            streaming: false,
            error: {
              message: e instanceof ApiError ? e.message : "대화를 만들지 못했습니다.",
            },
          }));
          setStreaming(false);
          setStage(null);
          return;
        }
      }
      const ac = new AbortController();
      abortRef.current = ac;
      try {
        await streamPost<ResearchEvent>(
          chatTurnPath(id),
          { text: trimmed, tableId: activeId },
          {
            onEvent: (e) => apply(asstId, e),
            onError: (err: StreamError) => {
              if (err.code === "SESSION_BUSY") toast.error(errorText(err), { position: "top-center" });
              patch(asstId, (m) => ({ ...m, streaming: false, error: err }));
            },
            onAbort: () => patch(asstId, (m) => ({ ...m, streaming: false, aborted: true })),
          },
          ac.signal,
        );
      } finally {
        if (abortRef.current === ac) abortRef.current = null;
        setStreaming(false);
        setStage(null);
      }
    },
    [activeId, apply, onCreated, streaming, workspaceId],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    if (chatRef.current) void cancelChatTurn(chatRef.current).catch(() => undefined);
  }, []);

  const openSource = useCallback((docId: string, chunk?: string, cell?: [number, number] | null) => {
    setViewing({ docId, chunk, cell, tick: Date.now() });
    setTab("viewer");
  }, []);

  const active = useMemo(() => tables.find((t) => t.id === activeId) ?? null, [tables, activeId]);

  return {
    messages,
    tables,
    active,
    setActiveId,
    title,
    streaming,
    stage,
    send,
    stop,
    viewing,
    openSource,
    tab,
    setTab,
    docs,
    loading,
    replaceTable: upsert,
  };
}
