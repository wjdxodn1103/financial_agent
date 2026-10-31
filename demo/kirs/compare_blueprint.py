"""양식 2.0 틀 대조 — 원본(정답지 expected_layout.json) 목차·표 ↔ blueprint 의 부분·소주제·표 양식을 1:1 로 맞댄다.

  backend/.venv/Scripts/python -I demo/kirs/compare_blueprint.py [--llm]
  → 콘솔 + demo/kirs/compare_blueprint.md (+ demo/kirs/blueprint_dump.json)
--llm: 소주제 일반화(LLM 한 번, .env 의 모델)까지. 없으면 골격만(LLM 0회).
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "backend"))
from app.templates_import.blueprint import _fallback_names, generalize, skeleton  # noqa: E402
from app.templates_import.layout import analyze_layout  # noqa: E402

PDF = HERE.parent / "public_samples" / "07_kirs_sbbtech_2026-01.pdf"


def norm(s: str) -> str:
    return "".join((s or "").split())


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    exp = json.loads((HERE / "expected_layout.json").read_text(encoding="utf-8"))
    lay = analyze_layout(PDF)
    bp = skeleton(lay, PDF.name)
    if "--llm" in sys.argv:
        from dotenv import load_dotenv

        load_dotenv(HERE.parent.parent / "backend" / ".env")
        from app.llm.client import ReportLlm

        ok = asyncio.run(generalize(bp, lay, ReportLlm()))
        print("LLM 일반화:", "성공" if ok else "실패 — 규칙 대체")
    else:
        _fallback_names(bp)
    (HERE / "blueprint_dump.json").write_text(json.dumps(bp, ensure_ascii=False, indent=1), encoding="utf-8")
    parts = bp["parts"]
    forms = bp["forms"]
    out = [f"# 원본 ↔ 양식 2.0 틀 대조 — {PDF.name} ({datetime.now():%Y-%m-%d %H:%M})", "",
           f"부분 순서: {' → '.join(p['title'] for p in parts)}", "", "| 원본 | 틀 | 맞음 |", "|---|---|---|"]
    ok = total = 0

    def row(a: str, b: str, hit: bool) -> None:
        nonlocal ok, total
        total += 1
        ok += int(hit)
        out.append(f"| {a} | {b} | {'✓' if hit else '✗'} |")

    roles = [p["role"] for p in parts]
    row("표지(p1)", "cover" if "cover" in roles else "없음", "cover" in roles)
    summ = next((p for p in parts if p["role"] == "summary"), None)
    row(f"요약(p2) 주장 {len(exp['summary']['claims'])}개", f"summary 주장 {summ['claims'] if summ else 0}개 · 배치 {summ.get('layout') if summ else '-'}", bool(summ) and summ["claims"] == len(exp["summary"]["claims"]))
    for t in exp["summary"]["main_tables"]:
        hit = bool(summ) and any(norm(forms[b]["title"]) == norm(t) for b in summ["blocks"])
        row(f"요약 본문 아래 표 '{t}'", "요약 blocks" if hit else "없음", hit)
    for t in exp["summary"]["sidebar"]:
        hit = bool(summ) and any(norm(forms[b]["title"]) == norm(t) for b in summ["sidebar"])
        row(f"요약 사이드바 '{t}'", "요약 sidebar" if hit else "없음", hit)
    chapters = [p for p in parts if p["role"] == "chapter"]
    for k, c in enumerate(exp["chapters"]):
        got = chapters[k] if k < len(chapters) else None
        row(f"장 {k + 1} '{c['title']}'(p{c['page']}) 띠", f"{got['title']} (띠 {got['band']})" if got else "없음", bool(got) and norm(got["title"]) == norm(c["title"]) and got["band"])
        for j, s in enumerate(c["subsections"]):
            gs = got["subtopics"][j] if got and j < len(got["subtopics"]) else None
            row(f"  소제목 '{s['title']}'", f"소주제 '{gs['title']}' (예시 {'같음' if gs and norm(gs['example']) == norm(s['title']) else '다름'})" if gs else "없음",
                bool(gs) and norm(gs["example"]) == norm(s["title"]) and bool(gs["title"]))
        if got:
            row(f"  핵심 문장 칸", f"keyline {got['keyline']}", got["keyline"])
    app = next((p for p in parts if p["role"] == "appendix"), None)
    for t in [t for t in exp["tables"] if t["page"] == 26]:
        hit = bool(app) and any(norm(forms[b]["title"]) == norm(t["title"]) for b in app["blocks"])
        f = next((forms[b] for b in (app or {}).get("blocks", []) if norm(forms[b]["title"]) == norm(t["title"])), None)
        rows_ok = bool(f) and [norm(r["label"]) for r in f["rows"]] == [norm(x) for x in t["rows"]]
        row(f"부록 표 '{t['title']}' {len(t['rows'])}행", f"appendix · 행 {len(f['rows']) if f else 0} · 단위 {f.get('unit') if f else '-'}", hit and rows_ok)
    row("고지(p27)", "disclaimer" if "disclaimer" in roles else "없음", "disclaimer" in roles)
    th = bp["theme"]
    row("테마(강조색·띠·사이드바·제목색)", f"{th['accent']} · {th['bandFill']} · {th['sidebarFill']} · {th['captionColor']}", all(th.get(k) for k in ("accent", "bandFill", "sidebarFill", "captionColor")))
    row("머리글·바닥글", f"{[h['text'] for h in bp['page']['header']]} / {[h['text'] for h in bp['page']['footer']]}", bool(bp["page"]["header"]))
    out.insert(3, f"**맞음 {ok}/{total}** · 표 양식 {sum(1 for f in forms.values() if f['kind'] == 'table')}개 · 그림 자리 {sum(1 for f in forms.values() if f['kind'] == 'figure')}개 · 이름 '{bp['name']}'")
    out += ["", "## 장별 소주제(틀)", ""]
    for c in chapters:
        out.append(f"- **{c['title']}**{' — ' + c['guide'] if c.get('guide') else ''}")
        for s in c["subtopics"]:
            out.append(f"  - {s['title']} ← 샘플 '{s['example']}'" + (f" · 표·그림 {', '.join(forms[b]['title'] for b in s['blocks'])}" if s["blocks"] else "") + (f"\n    - 안내: {s['guide']}" if s.get("guide") else ""))
    md = "\n".join(out)
    (HERE / "compare_blueprint.md").write_text(md + "\n", encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
