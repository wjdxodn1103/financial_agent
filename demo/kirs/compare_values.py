"""양식 2.0 표 값 대조(L3) — 틀의 표 양식을 우리 자료(DART 원장)로 채운 칸 ↔ 원본 PDF 표의 같은 행·같은 연도 칸(LLM 0회).

  backend/.venv/Scripts/python -I demo/kirs/compare_values.py [문서 세션 id]
  → 콘솔 + demo/kirs/compare_values.md
자료 = 그 문서(기본: 에스비비테크 시험 문서 rmvu9dyi2c5pu)의 데이터 범위. 원본의 실적 연도(F 가 아닌 열)만 맞댄다.
같은 값 = 원본 표기 자릿수까지 반올림해 같으면(원본 75 ↔ 우리 74.8 → 75). 글 칸(적지·흑전)은 글이 같아야.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "backend"))
from app.research.form_rows import fill_form  # noqa: E402
from app.templates_import.blueprint import skeleton  # noqa: E402
from app.templates_import.layout import analyze_layout  # noqa: E402

PDF = HERE.parent / "public_samples" / "07_kirs_sbbtech_2026-01.pdf"
TARGET = ["포괄손익계산서", "재무상태표", "현금흐름표", "주요투자지표", "Forecast earnings & Valuation", "실적 추이 및 전망"]


def norm(s: str) -> str:
    return "".join((s or "").split())


def num(s: str):
    t = re.sub(r"[,\s]", "", s or "")
    try:
        return float(t)
    except ValueError:
        return None


def same(orig: str, ours: str) -> bool:
    a, b = num(orig), num(ours)
    if a is None or b is None:
        return norm(orig) == norm(ours)
    d = len(orig.split(".")[1]) if "." in orig else 0
    return abs(round(b, d) - a) <= 10 ** -d * 0.51 + 1e-9


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sid = sys.argv[1] if len(sys.argv) > 1 else "rmvu9dyi2c5pu"
    from sqlmodel import Session

    import app.db as db
    from app.db import engine

    model = next(getattr(db, n) for n in dir(db) if n in ("ReportSession",) and hasattr(getattr(db, n), "doc"))
    from app.services.report_service import report_scope_ids

    with Session(engine) as s:  # 화면·내보내기와 같은 지금의 데이터 범위
        row = s.get(model, sid)
        doc_ids = report_scope_ids(s, s.get(db.Workspace, row.workspace_id), row.doc or {}, row.created_by)
    lay = analyze_layout(PDF)
    bp = skeleton(lay, PDF.name)
    orig = {norm(t["title"]): t for t in lay["tables"]}
    out = [f"# 표 값 대조(L3) — 원본 {PDF.name} ↔ DART 로 채운 틀 ({datetime.now():%Y-%m-%d %H:%M})", "", f"자료 {len(doc_ids)}건 · 대상 에스비비테크", ""]
    tot_ok = tot = 0
    for f in bp["forms"].values():
        if f["kind"] != "table" or norm(f["title"]) not in {norm(t) for t in TARGET}:
            continue
        blk = fill_form(f, doc_ids, "에스비비테크")
        o = orig[norm(f["title"])]
        o_cols = o["columns"]
        ours_cols = blk["header"][1:]
        years = [c for c in o_cols if re.fullmatch(r"\d{4}", c) and c in ours_cols]
        ok = n = 0
        miss: List[str] = []
        empty: List[str] = []
        for orow, brow in zip(o["rows"], blk["rows"]):
            if norm(orow["label"]) != norm(brow[0]["text"]):
                miss.append(f"행 어긋남 {orow['label']} ↔ {brow[0]['text']}")
                continue
            for y in years:
                ov = orow["values"][o_cols.index(y)] if o_cols.index(y) < len(orow["values"]) else ""
                cell = brow[1 + ours_cols.index(y)]
                if not ov:
                    continue
                if not cell["text"]:
                    empty.append(f"{orow['label']} {y}")
                    continue
                n += 1
                if same(ov, cell["text"]):
                    ok += 1
                else:
                    miss.append(f"{orow['label']} {y}: 원본 {ov} ↔ 우리 {cell['text']}")
        tot_ok += ok
        tot += n
        out.append(f"## {f['title']} — 비교 연도 {', '.join(years)} · 맞음 {ok}/{n} · 빈 칸 {len(empty)}")
        if miss:
            out.append("- 다름: " + "; ".join(miss[:14]))
        if empty:
            out.append("- 빈 칸(자료·사전 없음): " + ", ".join(empty[:16]) + (" …" if len(empty) > 16 else ""))
        out.append("")
    out.insert(3, f"**전체 맞음 {tot_ok}/{tot}**")
    md = "\n".join(out)
    (HERE / "compare_values.md").write_text(md + "\n", encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
