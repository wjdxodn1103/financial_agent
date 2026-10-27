import type { ReactNode } from "react";

/** 문서형 페이지 머리 — 큰 제목·한 줄 설명·오른쪽 동작. 폭은 본문과 같게(wide 면 넓은 표 화면). */
export function PageHeader({ title, desc, actions, wide = false }: { title: string; desc?: string; actions?: ReactNode; wide?: boolean }) {
  return (
    <div className={`mx-auto flex items-end justify-between gap-4 px-8 pt-8 pb-6 ${wide ? "max-w-[1180px]" : "max-w-[960px]"}`}>
      <div className="min-w-0">
        <h1 className="text-[26px] leading-tight font-bold tracking-tight text-text-primary">{title}</h1>
        {desc && <p className="mt-1.5 text-[15px] leading-6 text-text-secondary">{desc}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
