"use client";

/**
 * 채팅 — 왼쪽은 워크스페이스 채널(멤버 대화, "@에이전트"로 물으면 데이터를 근거로 답), 오른쪽은 원문 보기와 기록 비서(FEATURES.records).
 * 기록 비서: 매일 퇴근 시각 배치가 그날 대화에서 결정·지시·방침·할 일·미결 질문을 기록 후보로 올린다 →
 * 발언자(또는 소유자)가 확인하면 팀 기록이 되고, 리포트 작성·채널 에이전트가 원문 그대로 인용한다.
 * 실시간은 3초 폴링. 대화는 공유된다(개인 대화는 리포트의 에이전트 대화).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AtSign, Bell, Bot, Check, Clock, Loader2, MessageSquare, Paperclip, Play, Plus, Send, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError } from "../../../report/api";
import { ACCEPT } from "../../../report/components/library/DocumentsFolder";
import { DocViewerBody } from "../../../report/components/viewer/DocViewerBody";
import { addRecord, confirmRecord, dismissRecord, downloadProgressDoc, listMessages, listRecords, postMessage, runRecordsNow } from "../../api";
import { useWorkspace } from "../../context";
import { useWorkspaceDocuments } from "../../hooks/useWorkspaceDocuments";
import type { ChannelMsg, RecordsPayload, TeamRecordItem } from "../../types";
import { FEATURES } from "../../features";
import { ChannelNumberChecks } from "./ChannelNumberChecks";

const POLL_MS = 3000;
const TYPE_TONE: Record<string, string> = {
  decision: "bg-primary-soft text-primary-soft-foreground",
  directive: "bg-violet-50 text-violet-800",
  convention: "bg-sky-50 text-sky-800",
  todo: "bg-emerald-50 text-emerald-800",
  question: "bg-amber-50 text-amber-800",
};

function hhmm(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** 에이전트 답의 [S번호] → 눌러서 원문을 여는 작은 칩 */
function AgentText({ m, onCite }: { m: ChannelMsg; onCite: (docId: string, chunk: string) => void }) {
  const parts = m.text.split(/(\[S\d+\])/g);
  return (
    <p className="text-sm leading-6 whitespace-pre-wrap text-text-primary">
      {parts.map((p, i) => {
        const n = /^\[S(\d+)\]$/.exec(p)?.[1];
        const c = n ? m.meta.cites?.[n] : undefined;
        if (!c) return <span key={i}>{p}</span>;
        return (
          <button key={i} type="button" title={`${c.label}${c.page ? ` p.${c.page}` : ""}`} onClick={() => onCite(c.docId, c.chunk)} className="mx-0.5 inline-flex cursor-pointer items-center rounded bg-primary-soft px-1 align-baseline text-[11px] font-medium text-primary hover:underline">
            {c.label.slice(0, 14)}
          </button>
        );
      })}
    </p>
  );
}

function RecordCard({ r, onConfirm, onDismiss }: { r: TeamRecordItem; onConfirm?: () => void; onDismiss?: () => void }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white px-3 py-2">
      <div className="flex items-start gap-1.5">
        <span className={cn("shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium", TYPE_TONE[r.type])}>{r.typeKo}</span>
        <p className="min-w-0 flex-1 text-xs leading-5 text-text-primary">{r.text}</p>
      </div>
      {r.quotes.map((q, i) => (
        <p key={i} className="mt-1 border-l-2 border-neutral-200 pl-2 text-[11px] leading-4 text-text-secondary">
          {q.author} · {hhmm(q.at)} — “{q.text}”
        </p>
      ))}
      {(r.scope || r.source.due || r.status === "confirmed") && (
        <p className="mt-1 text-[10px] text-text-secondary">
          {r.scope && `범위: ${r.scope} · `}
          {r.source.due && `기한: ${r.source.due} · `}
          {r.status === "confirmed" ? `확인 ${r.confirmedBy}` : ""}
        </p>
      )}
      {(onConfirm || onDismiss) && (
        <div className="mt-1.5 flex gap-1.5">
          {onConfirm && (
            <button type="button" onClick={onConfirm} className="inline-flex cursor-pointer items-center gap-1 rounded-md bg-primary px-2 py-0.5 text-[11px] text-white hover:bg-primary-hover">
              <Check className="size-3" aria-hidden />
              확인 — 팀 기록으로
            </button>
          )}
          {onDismiss && (
            <button type="button" onClick={onDismiss} className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-neutral-200 px-2 py-0.5 text-[11px] text-text-secondary hover:bg-neutral-50">
              <X className="size-3" aria-hidden />
              버리기
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function ChannelView() {
  const ws = useWorkspace();
  const docs = useWorkspaceDocuments(ws.workspaceId, false);
  const [msgs, setMsgs] = useState<ChannelMsg[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [recs, setRecs] = useState<RecordsPayload | null>(null);
  const [running, setRunning] = useState(false);
  const [manual, setManual] = useState<{ type: string; text: string } | null>(null);
  const [view, setView] = useState<{ docId: string; chunk: string; cell?: [number, number] | null; tick: number } | null>(null);
  const [thread, setThread] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [replying, setReplying] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const lastRef = useRef<string | undefined>(undefined);
  const canPost = ws.can("reviewer");
  const members = ws.detail?.members ?? [];

  const merge = useCallback((incoming: ChannelMsg[], updated: ChannelMsg[] = []) => {
    if (!incoming.length && !updated.length) return;
    setMsgs((cur) => {
      const byId = new Map(cur.map((m) => [m.id, m]));
      for (const m of [...incoming, ...updated]) byId.set(m.id, m);
      return Array.from(byId.values()).sort((a, b) => a.createdAt.localeCompare(b.createdAt));
    });
    const last = incoming[incoming.length - 1];
    if (last) lastRef.current = last.createdAt;
  }, []);

  // 처음엔 전부, 그 뒤엔 3초마다 이후 것만(+ 답이 끝난 에이전트 메시지)
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      try {
        const r = await listMessages(ws.workspaceId, lastRef.current);
        if (!cancelled) merge(r.messages, r.updated);
      } catch {
        /* 다음 주기에 */
      }
      if (!cancelled) timer = setTimeout(() => void tick(), POLL_MS);
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [merge, ws.workspaceId]);

  const loadRecords = useCallback(async () => {
    try {
      setRecs(await listRecords(ws.workspaceId));
    } catch {
      /* 없음 */
    }
  }, [ws.workspaceId]);

  useEffect(() => {
    void loadRecords();
  }, [loadRecords]);

  // 스레드 — 답글은 threadId 로 묶어 본 목록에서 빼고 첫 메시지 아래 "답글 n" 으로
  const roots = useMemo(() => (FEATURES.threads ? msgs.filter((m) => !m.threadId) : msgs), [msgs]);
  const repliesOf = useMemo(() => {
    const out = new Map<string, ChannelMsg[]>();
    for (const m of msgs) if (m.threadId) out.set(m.threadId, [...(out.get(m.threadId) ?? []), m]);
    return out;
  }, [msgs]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [roots.length]);

  const openRef = (docId: string, chunk: string, cell: [number, number] | null) => setView((v) => ({ docId, chunk, cell, tick: (v?.tick ?? 0) + 1 }));

  const replyLink = (m: ChannelMsg) => {
    if (!FEATURES.threads) return null;
    const n = repliesOf.get(m.id)?.length ?? 0;
    if (!n && !canPost) return null;
    return (
      <button type="button" onClick={() => setThread(m.id)} className="mt-0.5 inline-flex cursor-pointer items-center gap-1 text-[11px] text-primary hover:underline">
        <MessageSquare className="size-3" aria-hidden />
        {n ? `답글 ${n}개 · ${hhmm(repliesOf.get(m.id)![n - 1].createdAt)}` : "답글 달기"}
      </button>
    );
  };

  const sendReply = async () => {
    const t = reply.trim();
    if (!t || !thread || replying) return;
    setReplying(true);
    try {
      const r = await postMessage(ws.workspaceId, t, [], thread);
      merge([r.message, ...(r.agent ? [r.agent] : [])]);
      setReply("");
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "보내지 못했습니다.", { position: "top-center" });
    } finally {
      setReplying(false);
    }
  };

  const send = async () => {
    const t = text.trim();
    if (!t || sending) return;
    setSending(true);
    try {
      const r = await postMessage(ws.workspaceId, t);
      merge([r.message, ...(r.agent ? [r.agent] : [])]);
      setText("");
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "보내지 못했습니다.", { position: "top-center" });
    } finally {
      setSending(false);
    }
  };

  const attach = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.accept = ACCEPT;
    input.onchange = async () => {
      const files = input.files ? Array.from(input.files) : [];
      if (!files.length) return;
      await docs.upload(files);
      // 처리(인제스트)가 끝나야 문서 id 가 생긴다 — 메시지에는 이름으로 알리고, 자료는 워크스페이스 자료 목록에 붙는다
      setText((t) => `${t}${t ? " " : ""}📎 ${files.map((f) => f.name).join(", ")} 올렸습니다.`.trim());
    };
    input.click();
  };

  const recCall = async (fn: () => Promise<RecordsPayload>, ok?: string) => {
    try {
      const r = await fn();
      setRecs(r);
      if (ok) toast.success(ok, { position: "top-center" });
      if (r.taskId) toast.success("할 일 기록이라 할 일 목록에도 넣었습니다.", { position: "top-center" });
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "처리하지 못했습니다.", { position: "top-center" });
    }
  };

  const runNow = async () => {
    setRunning(true);
    await recCall(() => runRecordsNow(ws.workspaceId));
    setRunning(false);
  };

  const candidates = useMemo(() => (recs?.records ?? []).filter((r) => r.status === "candidate"), [recs]);
  const confirmed = useMemo(() => (recs?.records ?? []).filter((r) => r.status === "confirmed"), [recs]);
  const lastRun = recs?.runs?.[0];
  const viewDoc = view ? (docs.documents ?? []).find((d) => d.id === view.docId) : null;
  const threadRoot = thread ? msgs.find((m) => m.id === thread) : undefined;

  /** 메시지 한 줄 — 본 목록과 스레드 패널이 같이 쓴다. inThread 면 답글 링크를 그리지 않는다 */
  const renderMsg = (m: ChannelMsg, inThread = false) => {
              const mine = m.userId === ws.me.id;
              if (m.kind === "system") {
                return (
                  <div key={m.id} className="flex justify-center">
                    <div className="max-w-[85%] rounded-lg border border-neutral-200 bg-white px-3 py-1.5 text-center text-xs leading-5 whitespace-pre-wrap text-text-secondary">
                      <Bell className="mr-1 inline size-3 align-[-2px] text-primary" aria-hidden />
                      {m.text}
                      <span className="ml-1 text-[10px]">{hhmm(m.createdAt)}</span>
                      {m.meta.report && (
                        <button type="button" onClick={() => ws.nav.openReport(m.meta.report!.id)} className="ml-1.5 cursor-pointer text-primary hover:underline">
                          리포트 열기
                        </button>
                      )}
                    </div>
                  </div>
                );
              }
              if (m.kind === "agent") {
                return (
                  <div key={m.id} className="flex gap-2">
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-white">
                      <Bot className="size-4" aria-hidden />
                    </span>
                    <div className="min-w-0 max-w-[80%] rounded-xl border border-primary-soft-border bg-primary-soft/50 px-3 py-2">
                      <p className="text-[11px] font-medium text-primary">에이전트 · {hhmm(m.createdAt)}</p>
                      {m.meta.pending ? (
                        <p className="flex items-center gap-1.5 text-sm text-text-secondary">
                          <Loader2 className="size-3.5 animate-spin" aria-hidden />
                          자료에서 근거를 찾는 중…
                        </p>
                      ) : (
                        <AgentText m={m} onCite={(docId, chunk) => openRef(docId, chunk, null)} />
                      )}
                      {!inThread && !m.meta.pending && replyLink(m)}
                    </div>
                  </div>
                );
              }
              return (
                <div key={m.id} className={cn("flex flex-col", mine && "items-end")}>
                  <p className="text-[11px] text-text-secondary">
                    {m.author} · {hhmm(m.createdAt)}
                  </p>
                  <div className={cn("max-w-[80%] rounded-xl px-3 py-2 text-sm leading-6 whitespace-pre-wrap", mine ? "bg-primary text-white" : "bg-background-gray text-text-primary")}>
                    {m.text}
                    {m.meta.attachments?.map((a) => (
                      <span key={a.docId} className="mt-1 block text-xs opacity-80">
                        📎 {a.label}
                      </span>
                    ))}
                  </div>
                  {m.meta.numberChecks && <ChannelNumberChecks checks={m.meta.numberChecks} align={mine ? "end" : undefined} onOpen={openRef} />}
                  {m.meta.mentions?.includes(ws.me.id) && <span className="mt-0.5 text-[10px] text-amber-700">나를 불렀습니다</span>}
                  {!inThread && replyLink(m)}
                </div>
              );
  };

  return (
    <div className="flex min-h-0 flex-1">
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="shrink-0 border-b border-neutral-200 px-5 py-3">
          <h1 className="text-[22px] leading-tight font-bold tracking-tight text-text-primary">채팅</h1>
        </div>
        <div ref={listRef} className="thin-scrollbar min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {msgs.length === 0 && <p className="text-sm text-text-secondary">아직 대화가 없습니다.</p>}
          <div className="flex flex-col gap-3">
            {roots.map((m) => renderMsg(m))}
          </div>
        </div>
        {canPost ? (
          <div className="shrink-0 border-t border-neutral-200 px-4 py-3">
            <div className="mb-1.5 flex flex-wrap items-center gap-1">
              <AtSign className="size-3.5 text-text-secondary" aria-hidden />
              {[{ id: "agent", name: "에이전트" }, ...members.filter((x) => x.user.id !== ws.me.id).map((x) => ({ id: x.user.id, name: x.user.name }))].map((p) => (
                <button key={p.id} type="button" onClick={() => setText((t) => `${t}${t && !t.endsWith(" ") ? " " : ""}@${p.name} `)} className="cursor-pointer rounded-full border border-neutral-200 px-2 py-0.5 text-[11px] text-text-secondary hover:bg-neutral-50">
                  @{p.name}
                </button>
              ))}
            </div>
            <div className="flex items-end gap-2">
              <button type="button" title="파일 첨부(워크스페이스 자료로 올라갑니다)" aria-label="파일 첨부" onClick={attach} className="flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-md border border-neutral-200 text-text-secondary hover:bg-neutral-50">
                <Paperclip className="size-4" aria-hidden />
              </button>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    void send();
                  }
                }}
                rows={2}
                placeholder="메시지 · @에이전트"
                className="min-h-[44px] flex-1 resize-none rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary"
              />
              <Button size="icon" aria-label="보내기" disabled={sending || !text.trim()} onClick={() => void send()}>
                {sending ? <Loader2 className="animate-spin" aria-hidden /> : <Send aria-hidden />}
              </Button>
            </div>
          </div>
        ) : (
          <p className="shrink-0 border-t border-neutral-200 px-5 py-3 text-xs text-text-secondary">열람자는 대화를 읽을 수만 있습니다.</p>
        )}
      </section>

      {(FEATURES.records || (view && viewDoc) || threadRoot) && (
      <aside className="thin-scrollbar flex w-[360px] shrink-0 flex-col overflow-y-auto border-l border-neutral-200 bg-background-gray/40 px-4 py-4">
        {view && viewDoc ? (
          <div className="mb-3 flex h-[420px] shrink-0 flex-col overflow-hidden rounded-xl border border-neutral-200 bg-white">
            <div className="flex justify-end border-b border-neutral-100 px-2 py-1">
              <button type="button" aria-label="원문 닫기" onClick={() => setView(null)} className="cursor-pointer rounded p-1 text-text-secondary hover:bg-neutral-100">
                <X className="size-3.5" aria-hidden />
              </button>
            </div>
            <div className="min-h-0 flex-1">
              <DocViewerBody workspaceId={ws.workspaceId} doc={viewDoc} focusChunk={view.chunk} focusCell={view.cell} tick={view.tick} />
            </div>
          </div>
        ) : null}

        {threadRoot && (
          <div className="mb-4 flex max-h-[520px] shrink-0 flex-col overflow-hidden rounded-xl border border-neutral-200 bg-white">
            <div className="flex items-center justify-between border-b border-neutral-100 px-3 py-1.5">
              <p className="text-xs font-semibold text-text-primary">스레드 · 답글 {repliesOf.get(threadRoot.id)?.length ?? 0}</p>
              <button type="button" aria-label="스레드 닫기" onClick={() => setThread(null)} className="cursor-pointer rounded p-1 text-text-secondary hover:bg-neutral-100">
                <X className="size-3.5" aria-hidden />
              </button>
            </div>
            <div className="thin-scrollbar flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto px-3 py-2.5 text-[13px]">
              {renderMsg(threadRoot, true)}
              <div className="border-t border-dashed border-neutral-200" />
              {(repliesOf.get(threadRoot.id) ?? []).map((m) => renderMsg(m, true))}
            </div>
            {canPost && (
              <div className="flex items-end gap-1.5 border-t border-neutral-100 px-2 py-2">
                <textarea
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      void sendReply();
                    }
                  }}
                  rows={2}
                  placeholder="답글 — @에이전트 로 물으면 이 스레드에 답합니다"
                  className="min-h-[40px] flex-1 resize-none rounded-md border border-neutral-200 px-2 py-1.5 text-xs outline-none focus:border-primary"
                />
                <Button size="icon" aria-label="답글 보내기" disabled={replying || !reply.trim()} onClick={() => void sendReply()}>
                  {replying ? <Loader2 className="animate-spin" aria-hidden /> : <Send aria-hidden />}
                </Button>
              </div>
            )}
          </div>
        )}

        {FEATURES.records && (
        <>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-primary">기록 비서</h2>
          <button
            type="button"
            title="팀 기록·충돌 채택·검수·자료·작업을 날짜순으로 묶은 경과 문서(DOCX)"
            onClick={() => void downloadProgressDoc(ws.workspaceId).catch(() => toast.error("경과 문서를 만들지 못했습니다.", { position: "top-center" }))}
            className="cursor-pointer text-[11px] text-primary hover:underline"
          >
            경과 문서 받기
          </button>
        </div>
        <p className="mt-0.5 flex items-center gap-1 text-[11px] text-text-secondary">
          <Clock className="size-3" aria-hidden />
          매일 {recs?.offHour ?? "19:00"} 배치 · 다음 {recs?.nextRunAt ? hhmm(recs.nextRunAt) : "…"}
          {lastRun && ` · 마지막 ${hhmm(lastRun.startedAt)} (${lastRun.status === "ok" ? `메시지 ${lastRun.processed}개 → 후보 ${lastRun.candidates}건` : lastRun.status})`}
        </p>
        {ws.can("owner") && (
          <Button size="sm" variant="outline" className="mt-2" disabled={running} onClick={() => void runNow()} title="퇴근 시각을 기다리지 않고 지금까지의 대화를 정리합니다(소유자 전용 · 데모·테스트용)">
            {running ? <Loader2 className="animate-spin" aria-hidden /> : <Play aria-hidden />}
            배치 지금 실행
          </Button>
        )}

        <h3 className="mt-4 text-xs font-semibold text-text-secondary">확인을 기다리는 후보 {candidates.length}</h3>
        <div className="mt-1.5 flex flex-col gap-2">
          {candidates.length === 0 && <p className="text-xs text-text-secondary">없음</p>}
          {candidates.map((r) => (
            <RecordCard
              key={r.id}
              r={r}
              onConfirm={r.canConfirm ? () => void recCall(() => confirmRecord(ws.workspaceId, r.id), "팀 기록으로 남겼습니다.") : undefined}
              onDismiss={r.canConfirm ? () => void recCall(() => dismissRecord(ws.workspaceId, r.id)) : undefined}
            />
          ))}
        </div>

        <div className="mt-5 flex items-center justify-between">
          <h3 className="text-xs font-semibold text-text-secondary">팀 기록 {confirmed.length}</h3>
          {canPost && !manual && (
            <button type="button" onClick={() => setManual({ type: "directive", text: "" })} className="inline-flex cursor-pointer items-center gap-0.5 text-[11px] text-primary hover:underline">
              <Plus className="size-3" aria-hidden />
              직접 남기기
            </button>
          )}
        </div>
        {manual && (
          <div className="mt-1.5 rounded-lg border border-neutral-200 bg-white p-2">
            <select aria-label="기록 종류" value={manual.type} onChange={(e) => setManual({ ...manual, type: e.target.value })} className="rounded border border-neutral-200 px-1.5 py-0.5 text-xs">
              <option value="decision">결정</option>
              <option value="directive">지시</option>
              <option value="convention">방침</option>
              <option value="todo">할 일</option>
              <option value="question">미결 질문</option>
            </select>
            <textarea value={manual.text} onChange={(e) => setManual({ ...manual, text: e.target.value })} rows={2} placeholder="예: 매출은 연결 기준으로 쓴다" className="mt-1 w-full resize-none rounded border border-neutral-200 px-2 py-1 text-xs" />
            <div className="flex justify-end gap-1">
              <button type="button" onClick={() => setManual(null)} className="cursor-pointer px-2 py-0.5 text-[11px] text-text-secondary">
                취소
              </button>
              <button
                type="button"
                disabled={!manual.text.trim()}
                onClick={() => void recCall(() => addRecord(ws.workspaceId, manual.type, manual.text), "팀 기록으로 남겼습니다.").then(() => setManual(null))}
                className="cursor-pointer rounded bg-primary px-2 py-0.5 text-[11px] text-white disabled:opacity-50"
              >
                남기기
              </button>
            </div>
          </div>
        )}
        <div className="mt-1.5 flex flex-col gap-2 pb-6">
          {confirmed.length === 0 && <p className="text-xs text-text-secondary">아직 없음</p>}
          {confirmed.map((r) => (
            <RecordCard key={r.id} r={r} />
          ))}
        </div>
        </>
        )}
      </aside>
      )}
    </div>
  );
}
