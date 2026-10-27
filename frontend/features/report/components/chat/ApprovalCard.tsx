"use client";

/**
 * 확인 카드 — 쓰기 전에 무엇을·무엇으로 쓸지 사용자가 확정하는 곳(OP-FE ApprovalCard 의 2단계 구조 그대로).
 *   1/2  섹션과 이 섹션에서 다룰 내용 + 참고할 자료(칩을 눌러 빼고 넣는다)
 *   2/2  작성에 필요한 정보(투자의견·기준 주가 등 자료에 없는 사용자 판단) + 요청 사항
 * 수정 카드(revise)는 한 단계 — 요청 사항만. 카드 종류·질문·입력칸 정의는 서버가 준다. 승인·거절 뒤에는 그때 내용으로 굳는다.
 */
import { useState } from "react";
import { useAtomValue } from "jotai";
import { Check, ChevronRight, FileText, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { streamingAtom } from "../../atoms";
import { CARD_KIND_LABEL } from "../../constants";
import { useReportActions } from "../../hooks/useReportStudio";
import type { ChatMessage } from "../../types";

export function ApprovalCard({ message }: { message: ChatMessage }) {
  const actions = useReportActions();
  const streaming = useAtomValue(streamingAtom);
  const ap = message.approval!;
  const [step, setStep] = useState<1 | 2>(1);
  const [inputs, setInputs] = useState<Record<string, string>>(ap.inputs ?? {});
  // 요청 사항 칸은 비워 둔다 — 대화에서 뽑힌 요청(ap.instruction)은 위에 읽기 전용으로, 서버가 따로 싣는다(OP 2026-10-07 규칙)
  const [instruction, setInstruction] = useState("");

  const kind = ap.kind ?? (ap.action === "revise" ? "revise" : "write");
  const pending = ap.state === "pending";
  const isWrite = ap.action === "plan";
  const docs = ap.documents ?? [];
  const excluded = ap.excludedDocs ?? [];
  const usedDocs = docs.filter((d) => !excluded.includes(d.id));
  const fields = ap.inputFields ?? [];
  const label = ap.options?.[0]?.label ?? (isWrite ? "이대로 작성" : "이대로 수정");

  const approve = () => void actions.approve(message.id, { label, instruction: instruction.trim() || undefined, inputs });

  return (
    <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
      <span className="inline-flex items-center rounded-md bg-primary-soft px-2 py-0.5 text-xs font-semibold tracking-wide text-primary">{CARD_KIND_LABEL[kind]}</span>
      <p className="chat-prose mt-2 text-base leading-7 font-semibold text-text-primary">{ap.question}</p>

      {isWrite && pending && <p className="mt-2 text-xs text-text-secondary">{step === 1 ? "1/2 · 섹션과 참고할 자료를 확인합니다" : "2/2 · 작성에 필요한 정보를 더해 주세요(선택)"}</p>}

      {(!isWrite || !pending || step === 1) && (
        <>
          {ap.itemDesc && (
            <div className="mt-3">
              <p className="text-xs font-semibold text-text-primary">
                <span className="mr-1 text-primary">•</span>이 섹션에서 다룰 내용
              </p>
              <p className="mt-1 text-xs leading-5 text-text-secondary">{ap.itemDesc}</p>
            </div>
          )}
          <div className="mt-3">
            <p className="text-xs font-semibold text-text-primary">
              <span className="mr-1 text-primary">•</span>참고할 자료 {docs.length > 0 && <span className="font-normal text-text-secondary">({usedDocs.length}/{docs.length})</span>}
            </p>
            <div className="mt-1.5 rounded-lg border border-neutral-200 bg-background-gray px-3 py-2.5">
              {docs.length === 0 ? (
                <p className="text-xs text-text-secondary">올린 자료가 없습니다 — 근거 없이 쓰면 수치를 쓰지 않습니다. 오른쪽 자료 패널에서 먼저 올리는 것을 권합니다.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {docs.map((d) => {
                    const off = excluded.includes(d.id);
                    return (
                      <button
                        key={d.id}
                        type="button"
                        disabled={!pending}
                        title={off ? "눌러서 다시 넣기" : "눌러서 이 섹션에서 빼기"}
                        onClick={() => actions.toggleCardDoc(message.id, d.id)}
                        className={cn(
                          "inline-flex max-w-full cursor-pointer items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors disabled:cursor-default",
                          off ? "border-neutral-200 bg-white text-text-secondary line-through opacity-60" : "border-primary-soft-border bg-white text-text-primary",
                        )}
                      >
                        <FileText className="size-3 shrink-0 text-primary" aria-hidden />
                        <span className="truncate">{d.label}</span>
                        {d.docType && <span className="shrink-0 text-[10px] text-text-secondary">{d.docType}</span>}
                      </button>
                    );
                  })}
                </div>
              )}
              {ap.note && pending && <p className="mt-2 rounded bg-amber-50 px-2 py-1 text-xs leading-5 text-amber-800">{ap.note}</p>}
              {ap.notes && ap.notes.length > 0 && (
                <div className="mt-2 rounded-lg border border-violet-200 bg-violet-50/60 px-2.5 py-2 text-xs leading-5">
                  <p className="font-medium text-violet-900">참고할 팀 기록</p>
                  {ap.notes.map((n, i) => (
                    <p key={i} className="mt-1 text-text-primary">
                      <span className="mr-1 rounded bg-white px-1 text-[10px] text-violet-800">{n.typeKo}</span>
                      {n.author ? `${n.author}님이 ${n.at} ` : ""}
                      {n.quote ? `“${n.quote}”라고 남기셨습니다.` : n.text}
                    </p>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {pending && (isWrite ? step === 2 : true) && (
        <div className="mt-4">
          {isWrite && fields.length > 0 && (
            <div className="mb-4 flex flex-col gap-2">
              <p className="text-xs font-semibold text-text-primary">
                <span className="mr-1 text-primary">•</span>작성에 필요한 정보(입력한 값은 사용자 판단으로 그대로 씁니다)
              </p>
              {fields.map((f) => (
                <label key={f.key} className="flex flex-col gap-1">
                  <span className="text-xs text-text-primary">{f.label}</span>
                  {f.multiline ? (
                    <textarea
                      rows={2}
                      value={inputs[f.key] ?? ""}
                      placeholder={f.placeholder}
                      onChange={(e) => setInputs((v) => ({ ...v, [f.key]: e.target.value }))}
                      className="rounded-lg border border-neutral-200 bg-white px-3 py-1.5 text-sm leading-6 outline-none focus:border-primary-soft-border"
                    />
                  ) : (
                    <input
                      value={inputs[f.key] ?? ""}
                      placeholder={f.placeholder}
                      onChange={(e) => setInputs((v) => ({ ...v, [f.key]: e.target.value }))}
                      className="h-9 rounded-lg border border-neutral-200 bg-white px-3 text-sm outline-none focus:border-primary-soft-border"
                    />
                  )}
                </label>
              ))}
            </div>
          )}
          <p className="text-xs font-semibold text-text-primary">
            <span className="mr-1 text-primary">•</span>요청 사항
          </p>
          {ap.instruction && <p className="mt-1 text-xs text-text-secondary">대화에서 요청한 것: {ap.instruction}</p>}
          <textarea
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            rows={2}
            placeholder={isWrite ? "예: 부문별 수치를 표 대신 글머리표로, 전년 대비 증감 중심으로" : "예: 리스크를 두 가지로 줄이고 각 리스크의 점검 지표를 붙여 줘"}
            className="mt-1 w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm leading-6 outline-none focus:border-primary-soft-border"
          />
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {pending && isWrite && step === 1 ? (
          <>
            <Button onClick={() => setStep(2)} disabled={streaming}>
              다음
              <ChevronRight className="size-4" aria-hidden />
            </Button>
            <Button variant="ghost" onClick={() => void actions.reject(message.id)} disabled={streaming}>
              <X className="size-4" aria-hidden />
              지금은 안 씀
            </Button>
          </>
        ) : pending ? (
          <>
            {isWrite && (
              <Button variant="ghost" onClick={() => setStep(1)} disabled={streaming}>
                이전
              </Button>
            )}
            <Button onClick={approve} disabled={streaming} title={streaming ? "앞선 응답이 끝난 뒤 누를 수 있습니다" : undefined}>
              <Check className="size-4" aria-hidden />
              {label}
            </Button>
            <Button variant="ghost" onClick={() => void actions.reject(message.id)} disabled={streaming}>
              <X className="size-4" aria-hidden />
              {isWrite ? "지금은 안 씀" : "고치지 않음"}
            </Button>
          </>
        ) : (
          <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium", ap.state === "approved" ? "bg-primary-soft text-primary" : "bg-background-gray text-text-secondary")}>
            {ap.state === "approved" ? <Check className="size-3.5" aria-hidden /> : <X className="size-3.5" aria-hidden />}
            {ap.state === "approved" ? `${ap.chosen ?? label} — 진행함` : "진행하지 않음"}
          </span>
        )}
      </div>
    </div>
  );
}
