"use client";

/**
 * 문단 본문 — 표는 칸 구조(rows)가 있으면 표로 그리고, 원장에서 온 칸(focusCell)은 강조한다.
 * 칸 구조가 없는 표(옛 추출·PDF 줄 표)는 줄 그대로(고정폭).
 */
import { cn } from "@/lib/utils";
import type { DocChunk } from "../../types";

export function ChunkBody({ chunk, focusCell }: { chunk: DocChunk; focusCell?: [number, number] | null }) {
  if (chunk.kind === "table" && chunk.rows?.length) {
    return (
      <div className="thin-scrollbar overflow-x-auto">
        <table className="w-full border-collapse text-[11px] leading-4">
          <tbody>
            {chunk.rows.map((row, r) => (
              <tr key={r} className={r === 0 ? "bg-background-gray font-medium" : undefined}>
                {row.map((cell, c) => {
                  const on = focusCell && focusCell[0] === r && focusCell[1] === c;
                  return (
                    <td key={c} className={cn("border border-neutral-200 px-1.5 py-0.5 align-top whitespace-pre-wrap text-text-primary", on && "bg-yellow-200 font-semibold ring-2 ring-yellow-400 ring-inset")}>
                      {cell}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return <p className={cn("text-xs leading-5 text-text-primary", chunk.kind === "table" ? "font-mono whitespace-pre-wrap" : "whitespace-pre-wrap")}>{chunk.text}</p>;
}
