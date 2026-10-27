"use client";

/** 답·메모 속 출처 링크([문서, p.3](#cite=문서~문단)) — 누르면 그 문단을 연다. 다른 링크는 새 탭. */
import { useMemo } from "react";
import type { Components } from "react-markdown";

export function useCiteComponents(open?: (docId: string, chunk: string) => void): Partial<Components> {
  return useMemo<Partial<Components>>(
    () => ({
      a: ({ href, children }) => {
        const m = /^#cite=([^~]+)~(.+)$/.exec(href ?? "");
        if (m) {
          return open ? (
            <button type="button" onClick={() => open(m[1], m[2])} className="cursor-pointer text-primary underline-offset-2 hover:underline">
              {children}
            </button>
          ) : (
            <span className="text-primary">{children}</span>
          );
        }
        return (
          <a href={href} target="_blank" rel="noreferrer noopener" className="text-primary underline underline-offset-2">
            {children}
          </a>
        );
      },
    }),
    [open],
  );
}
