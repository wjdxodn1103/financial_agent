"use client";

/**
 * 검토 요청 — 내가 작성한 문서 여러 편을 골라 한 검토자에게 한 번에 보낸다(문서마다 검토 작업 + 채팅 알림).
 * 아래는 받은 요청·보낸 요청 — 받은 것은 '검토 완료'로 닫는다. 문서를 누르면 작성 화면.
 */
import { useCallback, useEffect, useState } from "react";
import { Check, FileText, Loader2, Send } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { ApiError } from "../../../report/api";
import { approveDoc, getMyPage, sendReviewRequests } from "../../api";
import { useWorkspace } from "../../context";
import type { MyPage } from "../../types";

function ago(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const min = Math.round((Date.now() - t) / 60000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  if (min < 60 * 24) return `${Math.round(min / 60)}시간 전`;
  const d = new Date(t);
  return `${d.getMonth() + 1}월 ${d.getDate()}일`;
}

export function RequestsView() {
  const ws = useWorkspace();
  const [page, setPage] = useState<MyPage | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"in" | "out">("in");

  const load = useCallback(async () => {
    try {
      const p = await getMyPage(ws.workspaceId);
      setPage(p);
      setReviewer((r) => r || p.reviewers[0]?.id || "");
    } catch {
      toast.error("불러오지 못했습니다.", { position: "top-center" });
    }
  }, [ws.workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const send = async () => {
    if (!picked.length || !reviewer || busy) return;
    setBusy(true);
    try {
      const r = await sendReviewRequests(ws.workspaceId, picked, reviewer, note);
      toast.success(`${r.sent}건 보냈어요`, { position: "top-center" });
      setPicked([]);
      setNote("");
      setTab("out");
      await load();
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : "보내지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  const docs = page?.documents ?? [];
  const list = (tab === "in" ? page?.received : page?.sent) ?? [];
  const sorted = list.slice().sort((a, b) => Number(a.done) - Number(b.done) || b.at.localeCompare(a.at));
  const canSend = ws.can("editor");

  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto bg-neutral-100">
      <div className="mx-auto max-w-[1040px] px-8 pt-8 pb-14">
        <h1 className="text-[26px] leading-tight font-bold tracking-tight text-text-primary">검토 요청</h1>

        {canSend && (
          <section className="mt-6 rounded-[24px] bg-white px-6 py-5">
            <h2 className="text-[19px] font-bold tracking-tight text-text-primary">보내기</h2>
            <div className="mt-3 flex flex-col">
              {page && docs.length === 0 && <p className="py-6 text-center text-[15px] text-neutral-500">작성한 문서가 없어요</p>}
              {docs.map((d) => {
                const on = picked.includes(d.id);
                const pct = d.sections ? Math.round((d.written / d.sections) * 100) : 0;
                return (
                  <label key={d.id} className={cn("flex cursor-pointer items-center gap-3 rounded-xl px-2 py-2.5 transition-colors", on ? "bg-primary-soft" : "hover:bg-neutral-50")}>
                    <span className={cn("flex size-6 shrink-0 items-center justify-center rounded-full border-2 transition-colors", on ? "border-primary bg-primary text-white" : "border-neutral-300")}>{on && <Check className="size-3.5" strokeWidth={3} aria-hidden />}</span>
                    <input type="checkbox" className="sr-only" checked={on} onChange={(e) => setPicked((cur) => (e.target.checked ? [...cur, d.id] : cur.filter((x) => x !== d.id)))} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[15px] font-medium text-text-primary">{d.title}</span>
                      <span className="mt-1 flex items-center gap-2">
                        <span className="h-1.5 w-28 overflow-hidden rounded-full bg-neutral-100">
                          <span className="block h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
                        </span>
                        <span className="num text-[12px] font-semibold text-neutral-500">
                          {d.written}/{d.sections}
                        </span>
                      </span>
                    </span>
                    {d.review && <span className={cn("shrink-0 rounded-lg px-2.5 py-1 text-[12px] font-semibold", d.review.done ? "bg-neutral-100 text-neutral-500" : "bg-primary-soft text-primary")}>{d.review.person.split(" ")[0]} {d.review.done ? "검토 완료" : "검토 중"}</span>}
                  </label>
                );
              })}
            </div>
            {docs.length > 0 && (
              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-neutral-100 pt-4">
                <select value={reviewer} onChange={(e) => setReviewer(e.target.value)} aria-label="검토자" className="h-11 rounded-xl bg-neutral-100 px-3 text-[14px] font-medium text-text-primary outline-none">
                  {(page?.reviewers ?? []).map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
                <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="메모" className="h-11 min-w-[200px] flex-1 rounded-xl bg-neutral-100 px-4 text-[14px] outline-none focus:bg-white focus:ring-2 focus:ring-primary/30" />
                <button type="button" disabled={!picked.length || !reviewer || busy} onClick={() => void send()} className="flex h-11 cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-5 text-[15px] font-semibold text-white hover:bg-primary-hover disabled:opacity-40">
                  {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
                  {picked.length ? `${picked.length}건 보내기` : "보내기"}
                </button>
              </div>
            )}
          </section>
        )}

        <section className="mt-4 rounded-[24px] bg-white px-6 py-5">
          <div className="flex items-center justify-between">
            <h2 className="text-[19px] font-bold tracking-tight text-text-primary">요청 목록</h2>
            <div className="flex rounded-xl bg-neutral-100 p-1 text-[13px] font-semibold">
              {(
                [
                  ["in", `받은 요청 ${page?.received.length ?? 0}`],
                  ["out", `보낸 요청 ${page?.sent.length ?? 0}`],
                ] as const
              ).map(([id, label]) => (
                <button key={id} type="button" onClick={() => setTab(id)} className={cn("cursor-pointer rounded-lg px-3 py-1.5 transition-colors", tab === id ? "bg-white text-text-primary shadow-sm" : "text-neutral-500 hover:text-neutral-700")}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="mt-3">
            {page && sorted.length === 0 && <p className="py-8 text-center text-[15px] text-neutral-500">{tab === "in" ? "받은 요청이 없어요" : "보낸 요청이 없어요"}</p>}
            {sorted.map((r) => (
              <div key={r.taskId} className="flex items-center gap-3 rounded-xl px-2 py-2.5 transition-colors hover:bg-neutral-50">
                <button type="button" onClick={() => ws.nav.openReport(r.reportId)} className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 text-left">
                  <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-full", r.done ? "bg-neutral-100 text-neutral-400" : "bg-primary-soft text-primary")}>
                    <FileText className="size-[18px]" aria-hidden />
                  </span>
                  <span className="min-w-0">
                    <span className={cn("block truncate text-[15px] font-medium", r.done ? "text-neutral-500" : "text-text-primary")}>{r.title}</span>
                    <span className="block truncate text-[13px] text-neutral-500">
                      {r.person} · {ago(r.at)}
                      {r.note ? ` · “${r.note}”` : ""}
                    </span>
                  </span>
                </button>
                {r.done ? (
                  <span className="shrink-0 rounded-lg bg-neutral-100 px-2.5 py-1 text-[12px] font-semibold text-neutral-500">완료</span>
                ) : tab === "in" ? (
                  <button
                    type="button"
                    // 문서 화면의 [검토 완료]와 같다 — 문서 승인 + 검토 작업 끝 + 작성자에게 알림
                    onClick={() =>
                      void approveDoc(r.reportId)
                        .then(() => getMyPage(ws.workspaceId))
                        .then(setPage)
                        .catch(() => toast.error("검토를 마치지 못했습니다.", { position: "top-center" }))
                    }
                    className="shrink-0 cursor-pointer rounded-lg bg-neutral-100 px-3 py-1.5 text-[13px] font-semibold text-neutral-700 hover:bg-neutral-200"
                  >
                    검토 완료
                  </button>
                ) : (
                  <span className="shrink-0 rounded-lg bg-primary-soft px-2.5 py-1 text-[12px] font-semibold text-primary">검토 중</span>
                )}
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
