"use client";

/**
 * 공용 자료실 — 조직이 같이 쓰는 자료 선반. 여기 있는 자료는 이 워크스페이스에 **붙여야** 검색·원장·리포트에 들어간다
 * (워크스페이스 밖은 찾지 않는다는 원칙). 붙이기는 편집자 이상, 내리기는 올린 사람.
 */
import { useCallback, useEffect, useState } from "react";
import { Library, Loader2, Paperclip, Search, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ApiError } from "../../../report/api";
import { FileTypeIcon } from "../../../report/components/library/rows";
import { attachFromLibrary, listLibrary, unpublishDocument } from "../../api";
import { useWorkspace } from "../../context";
import type { LibraryEntry } from "../../types";

export function LibraryPanel({ onClose, onAttached }: { onClose: () => void; onAttached: (docId: string) => void }) {
  const ws = useWorkspace();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<LibraryEntry[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const canAttach = ws.can("editor");

  const load = useCallback(
    async (query = "") => {
      try {
        setItems(await listLibrary(query, ws.workspaceId));
      } catch {
        setItems([]);
      }
    },
    [ws.workspaceId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (id: string, fn: () => Promise<LibraryEntry[]>, ok: string, after?: () => void) => {
    setBusy(id);
    try {
      setItems(await fn());
      toast.success(ok, { position: "top-center" });
      after?.();
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "처리하지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="rounded-xl border border-primary-soft-border bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-text-primary">
          <Library className="size-4 text-primary" aria-hidden />
          공용 자료실
        </p>
        <button type="button" aria-label="닫기" onClick={onClose} className="cursor-pointer rounded p-1 text-text-secondary hover:bg-neutral-100">
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <p className="mt-1 text-[11px] text-text-secondary">다른 워크스페이스가 올린 자료입니다. 붙여야 이 워크스페이스의 검색·원장·리포트에 들어갑니다.</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void load(q);
        }}
        className="mt-2 flex items-center gap-2 rounded-lg border border-neutral-200 px-2.5 py-1.5"
      >
        <Search className="size-4 text-text-secondary" aria-hidden />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="자료 이름·발행처·메모" className="min-w-0 flex-1 text-sm outline-none" />
      </form>
      <div className="thin-scrollbar mt-2 flex max-h-72 flex-col gap-1 overflow-y-auto">
        {items === null && <p className="px-1 py-2 text-xs text-text-secondary">불러오는 중…</p>}
        {items?.length === 0 && <p className="px-1 py-2 text-xs text-text-secondary">자료실에 올라온 자료가 없습니다. 자료 목록에서 자료를 골라 &quot;공용 자료실에 올리기&quot;를 누르세요.</p>}
        {items?.map((it) => (
          <div key={it.id} className="flex items-start gap-2 rounded-lg px-2 py-1.5 hover:bg-neutral-50">
            <FileTypeIcon type={it.card.fileType} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm text-text-primary">{it.card.label}</span>
              <span className="block truncate text-[11px] text-text-secondary">{[it.card.docType, it.card.date, it.card.issuer].filter(Boolean).join(" · ") || it.card.fileName}</span>
              <span className="block truncate text-[11px] text-text-secondary">
                {it.publishedBy} · {it.from}
                {it.note ? ` — ${it.note}` : ""}
              </span>
            </span>
            {it.attached ? (
              <span className="shrink-0 rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700">붙어 있음</span>
            ) : (
              canAttach && (
                <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void act(it.id, () => attachFromLibrary(ws.workspaceId, it.id), "이 워크스페이스 자료로 붙였습니다.", () => onAttached(it.docId))}>
                  {busy === it.id ? <Loader2 className="animate-spin" aria-hidden /> : <Paperclip aria-hidden />}
                  붙이기
                </Button>
              )
            )}
            {it.publishedById === ws.me.id && (
              <button
                type="button"
                title="자료실에서 내리기(이미 붙인 워크스페이스의 자료는 남습니다)"
                aria-label="자료실에서 내리기"
                disabled={busy !== null}
                onClick={() => window.confirm("공용 자료실에서 내릴까요? 이미 붙인 워크스페이스의 자료는 그대로 남습니다.") && void act(it.id, () => unpublishDocument(it.id, ws.workspaceId), "자료실에서 내렸습니다.")}
                className="shrink-0 cursor-pointer rounded p-1 text-text-secondary hover:text-red-600"
              >
                <Trash2 className="size-3.5" aria-hidden />
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
