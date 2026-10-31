"""양식 2.0 왕복 비교(L4) — 우리 문서를 틀 DOCX 로 내보내고(Word 로 PDF) 같은 layout.py 로 다시 읽어 원본 샘플과 구조를 맞댄다.

  backend/.venv/Scripts/python -I demo/kirs/roundtrip.py <문서 id> <출력 폴더>
  1) <출력>/roundtrip.docx 를 만든다  2) Word(COM)로 roundtrip.pdf  3) 원본·우리 PDF 를 analyze_layout 으로 읽어 비교
  4) 쪽 PNG(원본 p2·p3·p26 ↔ 우리 같은 역할의 쪽)를 나란히 → <출력>/roundtrip_pages.png  5) demo/kirs/roundtrip.md
그림은 내보내지 않으므로(자리뿐) 비교에서 뺀다. 소제목은 우리가 쓴 섹션만 나온다.
"""
from __future__ import annotations

import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

import fitz  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db import ReportSession, engine  # noqa: E402
from app.report.blueprint_export import build_blueprint_docx  # noqa: E402
from app.templates_import.layout import analyze_layout  # noqa: E402

PDF = HERE.parent / "public_samples" / "07_kirs_sbbtech_2026-01.pdf"
PS = """$w = New-Object -ComObject Word.Application; $w.Visible = $false
try {{ $d = $w.Documents.Open('{src}', $false, $true); $d.SaveAs([ref]'{dst}', [ref]17); $d.Close([ref]0) }} finally {{ $w.Quit() }}"""


def to_pdf(docx: Path, pdf: Path) -> None:
    subprocess.run(["powershell", "-NoProfile", "-Command", PS.format(src=str(docx), dst=str(pdf))], check=True, timeout=300)


def summary(lay: Dict[str, Any]) -> Dict[str, Any]:
    chapters: List[Dict[str, Any]] = []
    for pg in lay["page_list"]:
        if pg.get("band"):
            chapters.append({"title": pg["band"]["text"], "headlines": 0, "keylines": 0, "tables": []})
        for e in pg["elements"]:
            if not chapters:
                continue
            if e["kind"] == "headline":
                chapters[-1]["headlines"] += 1
            elif e["kind"] == "keyline":
                chapters[-1]["keylines"] += 1
    tables = {t["title"]: t for t in lay["tables"] if t.get("title")}
    roles = Counter(p["role"] for p in lay["page_list"])
    side = next((p for p in lay["page_list"] if p.get("sidebar")), None)
    return {"theme": lay["theme"], "chapters": chapters, "tables": tables, "roles": roles, "sidebar": bool(side), "pages": lay["pages"]}


def mark(ok: bool) -> str:
    return "O" if ok else "X"


def page_sheet(orig: Path, ours: Path, pairs: List[tuple], out: Path) -> None:
    a, b = fitz.open(orig), fitz.open(ours)
    W, H = 595, 842
    sheet = fitz.open().new_page(width=W * 2, height=H * len(pairs))
    for k, (pa, pb) in enumerate(pairs):
        for col, (src, pno) in enumerate(((a, pa), (b, pb))):
            r = fitz.Rect(col * W, k * H, (col + 1) * W, (k + 1) * H)
            if pno and pno <= len(src):
                sheet.show_pdf_page(r, src, pno - 1)
            sheet.draw_rect(r, color=(0.5, 0.5, 0.5), width=1)
    sheet.get_pixmap(dpi=45).save(out)


def main(sid: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with Session(engine) as s:
        doc = s.get(ReportSession, sid).doc
    data, _name = build_blueprint_docx(doc)
    docx, pdf = out / "roundtrip.docx", out / "roundtrip.pdf"
    docx.write_bytes(data)
    to_pdf(docx, pdf)
    A, B = summary(analyze_layout(str(PDF))), summary(analyze_layout(str(pdf)))
    lines = [f"# 왕복 비교(L4) — 원본 {PDF.name} ↔ 문서 {sid} 의 틀 DOCX→PDF ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"쪽 수: 원본 {A['pages']} · 우리 {B['pages']} (우리는 그림·쓰지 않은 소주제가 없다)", "", "## 테마", "", "| 항목 | 원본 | 우리 | 같음 |", "|---|---|---|---|"]
    for k in ("accent", "bandFill", "bandText", "sidebarFill", "bodySize", "headlineSize", "bandSize"):
        x, y = A["theme"].get(k), B["theme"].get(k)
        same = (str(x).upper() == str(y).upper()) if isinstance(x, str) else (x is not None and y is not None and abs(float(x) - float(y)) <= 0.6)
        lines.append(f"| {k} | {x} | {y} | {mark(same)} |")
    lines += ["", f"요약 쪽 사이드바: 원본 {mark(A['sidebar'])} · 우리 {mark(B['sidebar'])}", "", "## 장 띠·소제목·핵심 문장", "",
              "| 장 | 원본 소제목 | 우리 소제목 | 원본 핵심 | 우리 핵심 |", "|---|---|---|---|---|"]
    bch = {c["title"]: c for c in B["chapters"]}
    for c in A["chapters"]:
        o = bch.get(c["title"])
        lines.append(f"| {c['title']} | {c['headlines']} | {o['headlines'] if o else '띠 없음'} | {c['keylines']} | {o['keylines'] if o else '-'} |")
    lines += ["", "## 표 양식(제목 · 행 이름 · 위 선 색)", "", "| 표 | 원본 행 | 우리 행 | 행 이름 같음 | 위 선 원본 → 우리 |", "|---|---|---|---|---|"]
    for title, t in A["tables"].items():
        o = B["tables"].get(title)
        if o is None:
            lines.append(f"| {title} | {len(t['rows'])} | 없음 | - | - |")
            continue
        la, lb = [r["label"] for r in t["rows"]], [r["label"] for r in o["rows"]]
        same = sum(1 for x in la if x in lb)  # 순서와 무관하게(빈 머리 행이 다시 읽을 때 빠지면 한 줄씩 밀린다)
        lines.append(f"| {title} | {len(la)} | {len(lb)} | {same}/{len(la)} | {t['look'].get('topRule')} → {o['look'].get('topRule')} |")
    text = "\n".join(lines)
    print(text)
    (HERE / "roundtrip.md").write_text(text + "\n", encoding="utf-8")
    # 쪽 나란히 — 원본 p2(요약)·p3(기업개요 첫 쪽)·p26(재무표) ↔ 우리 같은 역할 쪽
    ours = fitz.open(pdf)
    find = lambda needle: next((i + 1 for i in range(len(ours)) if needle in ours[i].get_text()), None)  # noqa: E731
    page_sheet(PDF, pdf, [(2, find("Company Data")), (3, find("기업개요")), (26, find("포괄손익계산서"))], out / "roundtrip_pages.png")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
