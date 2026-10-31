"""양식 2.0 장 비교(P5) — 원본 PDF 한 장(띠 ~ 다음 띠)의 요소 순서 ↔ 우리 문서 같은 장의 블록 순서(LLM 0회).

  backend/.venv/Scripts/python -I demo/kirs/compare_chapter.py <문서 id> [장 제목=기업개요]
  → 콘솔 + demo/kirs/compare_chapter.md
요소 기호: K = 핵심 문장(왼쪽 굵은 줄) · P = 본문 문단 · M = 작은 제목 · F = 그림 · T = 표. 같은 기호가 이어지면 ×n.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from sqlmodel import Session  # noqa: E402

from app.db import ReportSession, engine  # noqa: E402
from app.report.view import build_report_view  # noqa: E402
from app.templates_import.layout import analyze_layout  # noqa: E402

PDF = HERE.parent / "public_samples" / "07_kirs_sbbtech_2026-01.pdf"
SYM = {"keyline": "K", "para": "P", "minor": "M", "figure": "F", "table": "T"}


def squash(seq: List[str]) -> str:
    out: List[Tuple[str, int]] = []
    for s in seq:
        if out and out[-1][0] == s and s in ("P", "K"):
            out[-1] = (s, out[-1][1] + 1)
        else:
            out.append((s, 1))
    return " ".join(s if n == 1 else f"{s}×{n}" for s, n in out)


def original(chapter: str) -> List[Dict[str, Any]]:
    lay = analyze_layout(str(PDF))
    subs: List[Dict[str, Any]] = []
    inside = False
    for pg in lay["page_list"]:
        if pg.get("band"):
            inside = pg["band"]["text"].replace(" ", "") == chapter.replace(" ", "")
            if not inside and subs:
                break
        if not inside:
            continue
        for e in pg["elements"]:
            if e["kind"] == "headline":
                subs.append({"title": e["text"], "seq": [], "pages": {pg["page"]}})
            elif subs and e["kind"] in SYM:
                subs[-1]["seq"].append(SYM[e["kind"]] + (f"({(e.get('text') or e.get('title') or '')[:14]})" if e["kind"] in ("figure", "table", "minor") else ""))
                subs[-1]["pages"].add(pg["page"])
    return subs


def ours(doc: Dict[str, Any], chapter: str) -> List[Dict[str, Any]]:
    view = build_report_view(doc)
    subs: List[Dict[str, Any]] = []
    inside = False
    for b in view["blocks"]:
        k = b.get("kind")
        if k == "band":
            inside = (b.get("title") or b.get("text") or "").replace(" ", "") == chapter.replace(" ", "")
            continue
        if not inside:
            continue
        if k == "heading" and (b.get("depth") or 1) >= 2:
            subs.append({"title": b.get("text") or "", "no": b.get("no"), "seq": [], "status": b.get("status")})
        elif subs and k in ("heading", "subhead"):
            subs[-1]["seq"].append(f"M({(b.get('text') or '')[:14]})")
        elif subs and k == "para":
            subs[-1]["seq"].append("K" if b.get("role") == "keyline" else "P")
        elif subs and k in ("figure", "table", "format"):
            t = b.get("title") or b.get("caption") or b.get("label") or ""
            subs[-1]["seq"].append(("F" if k == "figure" or b.get("placeholder") else "T") + f"({t[:14]})")
        elif subs and k not in ("empty",):
            subs[-1]["seq"].append(f"?{k}")
    return subs


def main(sid: str, chapter: str) -> None:
    with Session(engine) as s:
        doc = s.get(ReportSession, sid).doc
    a, b = original(chapter), ours(doc, chapter)
    lines = [f"# 장 비교(P5) — '{chapter}' 원본 {PDF.name} ↔ 문서 {sid} ({datetime.now():%Y-%m-%d %H:%M})", "",
             "K 핵심 문장 · P 본문 문단 · M 작은 제목 · F 그림 · T 표", "",
             "| # | 원본 소제목 | 원본 요소 순서 | 우리 소제목 | 우리 요소 순서 |", "|---|---|---|---|---|"]
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else {"title": "—", "seq": []}
        y = b[i] if i < len(b) else {"title": "—", "seq": []}
        lines.append(f"| {i + 1} | {x['title']} | {squash(x['seq'])} | {y['title']} | {squash(y['seq'])} |")
    text = "\n".join(lines)
    print(text)
    (HERE / "compare_chapter.md").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "기업개요")
