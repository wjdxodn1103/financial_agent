"""데이터 워크북 오프라인 확인 — 업로드와 같은 경로(엑셀 읽기 → 청크 → 원장 figure → 묶음)로 돌려 본다(서버·LLM 없이).

  backend/.venv/Scripts/python demo/nbim/check_pack.py
확인: 모든 블록 시트를 찾음 · 칸 값 = make_pack 의 값(소수 자리 포함) · 원장 충돌 묶음 0개.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "backend"))
sys.path.insert(0, str(HERE))
from app.docs.chunk import chunk_paragraphs  # noqa: E402
from app.docs.extract import extract_xlsx  # noqa: E402
from app.formats.nbim_half_year import BLOCKS  # noqa: E402
from app.ledger import figures as F  # noqa: E402
from make_pack import DATA  # noqa: E402


def main() -> int:
    pack = HERE / "NBIM_2025H1_성과데이터.xlsx"
    chunks = chunk_paragraphs(extract_xlsx(pack)["paras"])
    figs = []
    for ch in chunks:
        for f in F.table_figures("pack", ch):
            figs.append({**f, "fid": F.fid(f)})
    problems = 0
    for bid, (_title, _header, rows) in DATA.items():
        sheet = BLOCKS[bid]["sheet"]
        mine = [c for c in chunks if c.get("sheet") == sheet and c.get("rows")]
        sf = [f for f in figs if f.get("sheet") == sheet]
        expected = sum(1 for r in rows for v in r[1:] if isinstance(v, (int, float)))
        ok = bool(mine) and len(sf) == expected
        problems += 0 if ok else 1
        sample = sf[0] if sf else {}
        print(f"{'OK ' if ok else 'BAD'} {sheet:24s} 청크 {len(mine)} · figure {len(sf)}/{expected} · 단위 {mine[0].get('unit') if mine else '-'} · 예: {sample.get('metric')} | {sample.get('period')}({sample.get('periodKey')}) = {sample.get('raw')} abs={sample.get('abs')}")
        # 값·소수 자리
        for f in sf:
            r, c = f["cell"]
            want = rows[r - 1][c] if 0 < r <= len(rows) and c < len(rows[r - 1]) else None
            if not isinstance(want, (int, float)) or abs(float(f["value"]) - float(want)) > 1e-9:
                problems += 1
                print(f"    값 다름 {f['metric']} {f['period']}: 원장 {f['raw']} vs 데이터 {want}")
    by_base = {}
    for f in figs:
        by_base.setdefault(F.base_key(f), []).append(f)
    conflicts = [k for k, fs in by_base.items() if len(F._clusters(fs)) > 1]
    print(f"figure {len(figs)}개 · 묶음 {len(by_base)}개 · 충돌 {len(conflicts)}개", conflicts[:5])
    problems += len(conflicts)
    print("문제 없음" if not problems else f"문제 {problems}건")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
