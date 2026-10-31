"""양식 2.0 추출 점검 — templates_import/layout.analyze_layout 결과를 손으로 적은 정답지(expected_layout.json)와 맞댄다(LLM 0회).

  backend/.venv/Scripts/python -I demo/kirs/check_layout.py [pdf] [--dump]
  → 콘솔 표 + demo/kirs/check_layout_result.md   (--dump: 추출 결과 JSON 을 demo/kirs/layout_dump.json 에)

글자 비교는 빈칸을 빼고 한다. 표 행 이름은 100% 가 기준(틀이 표 양식을 그대로 옮기려면 행 하나도 틀리면 안 된다).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "backend"))
from app.templates_import.layout import analyze_layout  # noqa: E402

PDF = HERE.parent / "public_samples" / "07_kirs_sbbtech_2026-01.pdf"
EXPECTED = HERE / "expected_layout.json"
OUT = HERE / "check_layout_result.md"


def norm(s: str) -> str:
    return "".join((s or "").split())


def score(name: str, got: List[str], want: List[str]) -> Dict[str, Any]:
    g = [norm(x) for x in got]
    w = [norm(x) for x in want]
    hit = [x for x in w if x in g]
    return {"name": name, "ok": len(hit), "total": len(w), "missing": [want[i] for i, x in enumerate(w) if x not in g], "extra": [got[i] for i, x in enumerate(g) if x not in w][:8]}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pdf = Path(args[0]) if args else PDF
    lay = analyze_layout(pdf)
    if "--dump" in sys.argv:
        (HERE / "layout_dump.json").write_text(json.dumps(lay, ensure_ascii=False, indent=1), encoding="utf-8")
    exp = json.loads(EXPECTED.read_text(encoding="utf-8"))
    rows: List[Dict[str, Any]] = []
    if not lay.get("ok"):
        print("글자층 없음:", lay.get("reason"))
        return
    pages = {p["page"]: p for p in lay["page_list"]}
    # 쪽 역할
    rows.append(score("쪽 역할", [f"{k}:{pages[int(k)]['role']}" for k in exp["page_roles"] if int(k) in pages], [f"{k}:{v}" for k, v in exp["page_roles"].items()]))
    # 장 띠
    bands = [f"{p['page']}:{p['band']['text']}" for p in lay["page_list"] if p.get("band")]
    rows.append(score("장 띠", bands, [f"{c['page']}:{c['title']}" for c in exp["chapters"]]))
    # 소제목(장 안) — 쪽:제목
    heads = [f"{p['page']}:{e['text']}" for p in lay["page_list"] if p["role"] not in ("summary", "cover") for e in p["elements"] if e["kind"] == "headline"]
    rows.append(score("장 소제목", heads, [f"{s['page']}:{s['title']}" for c in exp["chapters"] for s in c["subsections"]]))
    # 요약 주장
    sp = exp["summary"]["page"]
    claims = [e["text"] for e in pages[sp]["elements"] if e["kind"] == "headline"]
    rows.append(score("요약 주장", claims, exp["summary"]["claims"]))
    side_titles = [o["title"] for o in lay["tables"] + lay["figures"] if o["page"] == sp and o["column"] == "side"]
    rows.append(score("요약 사이드바", side_titles, exp["summary"]["sidebar"]))
    # 핵심 묶음 수
    kl = {str(k): sum(1 for e in pages[int(k)]["elements"] if e["kind"] == "keyline") for k in exp["keyline_groups"]}
    rows.append(score("핵심 묶음 수(쪽)", [f"{k}:{v}" for k, v in kl.items()], [f"{k}:{v}" for k, v in exp["keyline_groups"].items()]))
    # 그림 제목
    figs = [f for f in lay["figures"] if f.get("title")]
    rows.append(score("그림 제목(표본)", [f"{f['page']}:{f['title']}" for f in figs] + [f"{t['page']}:{t['title']}" for t in lay["tables"]], [f"{s['page']}:{s['title']}" for s in exp["figures"]["spot"]]))
    fig_count = {"name": f"그림·표 제목 개수(≥{exp['figures']['count_min']})", "ok": len(figs) + sum(1 for t in lay["tables"] if t.get("title")), "total": exp["figures"]["count_min"], "missing": [], "extra": []}
    rows.append(fig_count)
    # 표
    for t in exp["tables"]:
        cand = [x for x in lay["tables"] if x["page"] == t["page"] and norm(x.get("title", "")) == norm(t["title"])]
        if not cand:
            rows.append({"name": f"표 '{t['title']}'", "ok": 0, "total": len(t["rows"]), "missing": ["(표를 못 찾음)"], "extra": [f"{x['page']}:{x.get('title')}" for x in lay["tables"] if x["page"] == t["page"]][:6]})
            continue
        x = cand[0]
        got_rows = [r["label"] for r in x["rows"]]
        r = score(f"표 '{t['title']}' 행", got_rows, t["rows"])
        # 순서까지 — 같은 길이면 자리별
        r["order"] = [norm(a) for a in got_rows] == [norm(b) for b in t["rows"]]
        rows.append(r)
        if t.get("columns"):
            rows.append(score(f"표 '{t['title']}' 열", x.get("columns", []), t["columns"]))
        if t.get("indented"):
            rows.append(score(f"표 '{t['title']}' 들여쓰기", [rr["label"] for rr in x["rows"] if rr.get("indent")], sorted(set(t["indented"]))))
    # 테마
    th = lay["theme"]
    et = exp["theme"]
    tm = [("accent", th.get("accent"), et["accent"]), ("band_fill", th.get("bandFill"), et["band_fill"]), ("sidebar_fill", th.get("sidebarFill"), et["sidebar_fill"]),
          ("caption_color", th.get("captionColor"), et["caption_color"]), ("body_size", th.get("bodySize"), et["body_size"]), ("headline_size", th.get("headlineSize"), et["headline_size"]),
          ("band_size", th.get("bandSize"), et["band_size"])]
    def same(g: Any, w: Any) -> bool:
        if isinstance(w, str) and w.startswith("#") and isinstance(g, str) and g.startswith("#"):
            return all(abs(int(g[i:i + 2], 16) - int(w[i:i + 2], 16)) <= 4 for i in (1, 3, 5))  # 색은 반올림 차이(±4)까지 같다
        return str(g).upper() == str(w).upper()
    rows.append({"name": "테마", "ok": sum(1 for _n, g, w in tm if same(g, w)), "total": len(tm), "missing": [f"{n}: {g} ≠ {w}" for n, g, w in tm if not same(g, w)], "extra": []})

    lines = [f"# 양식 2.0 추출 점검 — {pdf.name} ({datetime.now():%Y-%m-%d %H:%M})", "", "| 항목 | 맞음 | 전체 | 빠짐 | 남음(정답에 없는 것) |", "|---|---|---|---|---|"]
    for r in rows:
        flag = "" if r["ok"] >= r["total"] and r.get("order", True) is not False else " ✗"
        order = "" if r.get("order", True) else " (순서 다름)"
        lines.append(f"| {r['name']}{flag} | {r['ok']} | {r['total']}{order} | {'; '.join(r['missing'][:6])} | {'; '.join(str(e) for e in r['extra'][:6])} |")
    md = "\n".join(lines)
    OUT.write_text(md + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
