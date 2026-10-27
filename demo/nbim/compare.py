"""작성 결과 ↔ 원본 반기 보고서(정답지) 숫자 대조 — 리포트 본문 숫자가 원본 PDF 에 있는지 섹션별 비율로 보인다(LLM 0회).

  backend/.venv/Scripts/python -I demo/nbim/compare.py [세션 id]     (기본 = demo/nbim/.report, 백엔드 8200 이 떠 있어야 한다)
  → 콘솔 표 + demo/nbim/compare_result.md

리포트 숫자 = GET /api/sessions/{id}/numbers 의 items(숫자 확인 탭과 같은 목록).
원본 숫자 = PDF 본문의 '5.7 percent'·'156 billion kroner'·'0.05 percentage point' + 표 칸(표 제목의 단위: in percent ·
in billions of kroner …). 그림(CHART) 축 눈금·연도 머리는 뺀다. 표 제목에 단위가 없으면 칸 값은 '단위 미표기'로 값끼리만 본다.
같은 값 = backend/app/ledger/numbers.py 의 same_value(반올림 한 단위까지, 경계는 제외 — _same) — %·%p 는 값끼리, 금액은 abs(크로네 등) 끼리.
부호는 한국어 본문이 '감소·하회' 같은 말로 나타내는 일이 많아 크기가 같으면 일치로 세고 '부호 다름'으로 적는다.
원본 PDF 는 내려받은 자료라 믿지 않는다 — 글자만 읽고(PyMuPDF), python -I 로 돌린다.
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF
import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "backend"))
from app.ledger.numbers import find_amounts, same_value  # noqa: E402

PDF = HERE.parent / "public_samples" / "03_nbim_gpfg_half_year_2025_investments.pdf"
OUT = HERE / "compare_result.md"
STATUS_KO = {"source": "자료와 일치", "calc": "계산값", "input": "입력값", "mismatch": "원장과 다름", "unsourced": "출처 없음"}

_NUM = r"(?<![\w.,])(?P<sign>[-–−])?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![.,]?\d)"
_TEXT = re.compile(
    _NUM + r"(?:\s*(?P<unit>percentage\s+points?|per\s?cent|%|(?P<scale>trillion|billion|million|thousand)\s+(?P<cur>kroner|NOK|euros?|dollars?|USD|EUR)))?",
    re.I,
)
_RANGE = re.compile(r"(?<![\w.,])(?P<num>\d+(?:\.\d+)?)\s*[–-]\s*\d+(?:\.\d+)?\s*(?P<unit>percentage\s+points?|per\s?cent|%)", re.I)
_CELL = re.compile(r"^\s*(?P<sign>[-–−])?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*$")
_FOOTNOTE = re.compile(r"^\s*\d{1,2}\s*\t")
_SCALE = {"trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3}
_CUR = {"kroner": "NOK", "nok": "NOK", "euro": "EUR", "euros": "EUR", "eur": "EUR", "dollar": "USD", "dollars": "USD", "usd": "USD"}


def _entry(sign: Optional[str], num: str, kind: str, scale: float = 1.0, currency: Optional[str] = None, page: int = 0, where: str = "") -> Dict[str, Any]:
    dec = len(num.split(".")[1]) if "." in num else 0
    v = float(num.replace(",", "")) * (-1.0 if sign else 1.0)
    return {"kind": kind, "value": v, "abs": v * scale, "step": 10 ** -dec * scale, "currency": currency, "page": page, "where": where}


def _caption_unit(caption: str) -> Dict[str, Any]:
    c = " ".join(caption.lower().split())
    if "percentage point" in c:
        return {"kind": "pp"}
    if re.search(r"\bin percent\b|\bpercent\b", c):
        return {"kind": "percent"}
    m = re.search(r"(trillion|billion|million|thousand)s?\s+of\s+(kroner|euros?|dollars?)", c)
    if m:
        return {"kind": "amount", "scale": _SCALE[m.group(1)], "currency": _CUR[m.group(2)]}
    return {"kind": "unknown"}


def pdf_numbers(path: Path) -> List[Dict[str, Any]]:
    """원본 PDF → 숫자 목록 [{kind: percent|pp|amount|plain|unknown, value, abs, step, currency, page, where}]."""
    out: List[Dict[str, Any]] = []
    with fitz.open(str(path)) as doc:
        for pno, page in enumerate(doc, start=1):
            text = page.get_text("text")
            flat = " ".join(text.split())
            # 본문(단위가 붙은 숫자) — 줄바꿈 넘어 '1,010 \n billion kroner' 도 잡도록 공백을 편다
            for m in _TEXT.finditer(flat):
                where = f"본문: …{flat[max(0, m.start() - 40): m.start()]}**{m.group(0).strip()}**{flat[m.end(): m.end() + 30]}…"
                unit = (m.group("unit") or "").lower()
                if not unit:
                    out.append(_entry(m.group("sign"), m.group("num"), "plain", page=pno, where=where))
                elif m.group("scale"):
                    out.append(_entry(m.group("sign"), m.group("num"), "amount", _SCALE[m.group("scale").lower()], _CUR[m.group("cur").lower()], pno, where))
                else:
                    out.append(_entry(m.group("sign"), m.group("num"), "pp" if "point" in unit else "percent", page=pno, where=where))
            for m in _RANGE.finditer(flat):  # '60–80 percent' 의 60
                unit = m.group("unit").lower()
                out.append(_entry(None, m.group("num"), "pp" if "point" in unit else "percent", page=pno, where=f"본문: …{flat[max(0, m.start() - 40): m.start()]}**{m.group(0).strip()}**{flat[m.end(): m.end() + 30]}…"))
            # 표 칸 — 'TABLE n' 제목(다음 두 줄까지)의 단위를 붙인다. CHART 축 눈금·각주 번호·연도 머리는 뺀다
            lines = text.splitlines()
            ctx: Optional[Dict[str, Any]] = None
            label = ""
            for i, line in enumerate(lines):
                head = re.match(r"^\s*(TABLE|CHART)\s+(\d+)\b", line)
                if head:
                    ctx = {**_caption_unit(" ".join(lines[i: i + 3])), "name": f"{head.group(1)} {head.group(2)}"} if head.group(1) == "TABLE" else {"kind": "chart"}
                    label = ""
                    continue
                if _FOOTNOTE.match(line):
                    ctx = None
                    continue
                cell = _CELL.match(line)
                if not cell:
                    if line.strip():
                        label = line.strip()
                    continue
                if not ctx or ctx["kind"] == "chart":
                    continue
                num = cell.group("num")
                if "," not in num and "." not in num and 1900 <= int(num) <= 2100:
                    continue
                where = f"{ctx['name']} · {label}"
                out.append(_entry(cell.group("sign"), num, ctx["kind"], ctx.get("scale", 1.0), ctx.get("currency"), pno, where))
    return out


_CUR_AFTER = re.compile(r"^\s*(유로|달러|엔|위안|파운드|크로네)")
_CUR_KO = {"유로": "EUR", "달러": "USD", "엔": "JPY", "위안": "CNY", "파운드": "GBP", "크로네": "NOK"}


def _amount(raw: str, sentence: str) -> Optional[Dict[str, Any]]:
    found = find_amounts(raw) or [a for a in find_amounts(sentence) if a["raw"] == raw]
    a = next((a for a in found if a["raw"] == raw), found[0] if found else None)
    if a and not a["percent"] and not a.get("currency") and raw in sentence:
        # find_amounts 는 '40억 유로' 를 '40억' 까지만 잡는다 — 바로 뒤 통화 낱말로 통화를 채운다(원본의 다른 통화 금액과 섞이지 않게)
        m = _CUR_AFTER.match(sentence[sentence.find(raw) + len(raw):])
        if m:
            a = {**a, "currency": _CUR_KO[m.group(1)]}
    return a


def _same(x: float, sx: float, y: float, sy: float) -> bool:
    """same_value + 경계 제외 — same_value 는 오차 여유(1e-9) 때문에 같은 자릿수의 한 단위 차이(281억 vs 280억, 6.74% vs 6.73%)도
    같다고 본다(그 docstring 은 '다르다'). 정답지 대조는 그 한 단위 차이를 틀린 숫자로 센다."""
    return same_value(x, sx, y, sy) and abs(x - y) < 0.5 * (sx + sy) - 1e-9 * max(1.0, abs(x), abs(y))


def _pool(a: Dict[str, Any]) -> str:
    if a["percent"]:
        return "percent"
    if a.get("currency") or abs(a["abs"]) != abs(a["value"]):
        return "amount"
    return "plain"


def candidates(a: Dict[str, Any], originals: List[Dict[str, Any]]) -> List[tuple]:
    """리포트 숫자 하나 → 원본에서 같은 값들 [(부호 순위, 값 차이(리포트 자릿수 단위), 종류 순위, 원본, 비고)]."""
    pool = _pool(a)
    want = "pp" if a.get("pp") else pool
    cands = []
    for o in originals:
        if pool == "percent" and o["kind"] in ("percent", "pp"):
            x, sx, y, sy = a["value"], a["step"], o["value"], o["step"]
        elif pool == "amount" and o["kind"] == "amount":
            if a.get("currency") and o.get("currency") and a["currency"] != o["currency"]:
                continue
            x, sx, y, sy = a["abs"], a["step"], o["abs"], o["step"]
        elif o["kind"] == "unknown" or (pool == "plain" and o["kind"] == "plain"):
            x, sx = a["value"], 10 ** -int(a.get("decimals") or 0)
            y, sy = o["value"], o["step"]
        else:
            continue
        kind_rank = 0 if o["kind"] == want else 1 if o["kind"] == "unknown" else 2
        if _same(x, sx, y, sy):
            cands.append((0, round(abs(x - y) / sx, 6), kind_rank, o, ""))
        elif _same(abs(x), sx, abs(y), sy):
            cands.append((1, round(abs(abs(x) - abs(y)) / sx, 6), kind_rank, o, "부호 다름"))
    return cands


def pick(cands: List[tuple], near: Dict[int, int]) -> Optional[Dict[str, Any]]:
    """같은 값이 여러 곳이면: 부호까지 같은 것 → 같은 문장의 다른 숫자가 많이 맞은 쪽(near = 쪽 → 개수) → 값이 가장 가까운 것
    (5.74% 는 '5.7 percent' 보다 표의 5.74) → 단위 종류가 같은 것(%p ↔ percentage point) → 쪽 순. 없으면 None."""
    if not cands:
        return None
    _s, _d, _k, o, note = min(cands, key=lambda c: (c[0], -near.get(c[3]["page"], 0), c[1], c[2], c[3]["page"]))
    if o["kind"] == "unknown":
        note = ", ".join(x for x in (note, "단위 미표기 표 값") if x)
    return {**o, "note": note}


def _w(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def _pad(s: str, n: int, right: bool = False) -> str:
    gap = " " * max(0, n - _w(s))
    return gap + s if right else s + gap


def _cell(s: str) -> str:
    return " ".join(str(s).split()).replace("|", "\\|")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="리포트 본문 숫자 ↔ 원본 반기 보고서 PDF 대조")
    ap.add_argument("session", nargs="?", help="리포트 세션 id (기본 = demo/nbim/.report)")
    ap.add_argument("--pdf", default=str(PDF))
    ap.add_argument("--base", default="http://localhost:8200")
    ap.add_argument("--user", default="u_kim")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    sid = args.session or (HERE / ".report").read_text(encoding="utf-8").strip()
    pdf = Path(args.pdf)

    data = httpx.get(f"{args.base}/api/sessions/{sid}/numbers", headers={"X-User-Id": args.user}, timeout=60).raise_for_status().json()
    items = [data["items"][k] for k in data.get("order") or data["items"].keys()]
    originals = pdf_numbers(pdf)

    rows: List[Dict[str, Any]] = []
    for it in items:
        a = _amount(it["raw"], it["sentence"])
        cands = candidates(a, originals) if a else []
        rows.append({**it, "cands": cands, "found": pick(cands, {})})
    # 원본 위치 고르기 2회차 — 같은 문장의 다른 숫자가 많이 맞은 쪽을 먼저(9.7% 가 TABLE 5 가 아니라 위임 한도 표 TABLE 13 으로)
    first = [r["found"] for r in rows]
    for i, r in enumerate(rows):
        near: Dict[int, int] = {}
        for j, o in enumerate(rows):
            if j != i and first[j] and (o.get("section"), o["sentence"]) == (r.get("section"), r["sentence"]):
                near[first[j]["page"]] = near.get(first[j]["page"], 0) + 1
        r["found"] = pick(r["cands"], near)

    sections: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        sections.setdefault(r.get("section") or "(섹션 없음)", []).append(r)
    total, hit = len(rows), sum(1 for r in rows if r["found"])

    def pct(h: int, n: int) -> str:
        return f"{100 * h / n:.1f}%" if n else "-"

    kinds: Dict[str, int] = {}
    for o in originals:
        kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
    kinds_ko = " · ".join(f"{k} {v}" for k, v in sorted(kinds.items()))

    # 콘솔
    print(f"세션 {sid} · 원본 {pdf.name} (숫자 {len(originals)}개: {kinds_ko})")
    print(_pad("섹션", 24) + _pad("숫자", 6, True) + _pad("원본에 있음", 12, True) + _pad("비율", 8, True))
    for name, rs in sections.items():
        h = sum(1 for r in rs if r["found"])
        print(_pad(name, 24) + _pad(str(len(rs)), 6, True) + _pad(str(h), 12, True) + _pad(pct(h, len(rs)), 8, True))
    print(_pad("전체", 24) + _pad(str(total), 6, True) + _pad(str(hit), 12, True) + _pad(pct(hit, total), 8, True))
    missing = [r for r in rows if not r["found"]]
    print(f"\n원본에 없는 숫자 {len(missing)}개" + (":" if missing else ""))
    for r in missing:
        print(f"  [{r.get('section')}] {r['raw']} ({STATUS_KO.get(r.get('status'), r.get('status'))}) — {r['sentence']}")
    noted = [r for r in rows if r["found"] and r["found"]["note"]]
    if noted:
        print(f"\n일치 — 비고가 붙은 숫자 {len(noted)}개:")
        for r in noted:
            print(f"  [{r.get('section')}] {r['raw']} — {r['found']['note']} (p.{r['found']['page']} {r['found']['where']})")

    # 마크다운
    md = [
        "# 작성 결과 ↔ 원본 반기 보고서 숫자 대조",
        "",
        f"- 리포트 세션 `{sid}` · 원본 `{pdf.name}` · {datetime.now().strftime('%Y-%m-%d %H:%M')} · `demo/nbim/compare.py` (LLM 0회)",
        f"- 원본에서 읽은 숫자 {len(originals)}개 ({kinds_ko}) — 본문 단위 숫자 + 표 칸(표 제목의 단위), 그림 축 눈금·연도 머리 제외",
        "- 같은 값 = 반올림 한 단위까지(`same_value`, 같은 자릿수의 한 단위 차이 6.74% vs 6.73% 는 다름) · %·%p 는 값끼리 · 금액은 abs 값끼리(통화가 둘 다 있으면 같아야) · 크기만 같으면 '부호 다름'으로 일치",
        "- '있음' = 그 값이 원본 어딘가에 있다는 뜻 — 같은 지표의 값인지는 아래 '원본 위치' 칸으로 확인",
        "",
        "## 원본에 있는 숫자 비율",
        "",
        "| 섹션 | 본문 숫자 | 원본에 있음 | 비율 |",
        "|---|---:|---:|---:|",
    ]
    for name, rs in sections.items():
        h = sum(1 for r in rs if r["found"])
        md.append(f"| {_cell(name)} | {len(rs)} | {h} | {pct(h, len(rs))} |")
    md += [f"| **전체** | **{total}** | **{hit}** | **{pct(hit, total)}** |", "", f"## 원본에 없는 숫자 ({len(missing)}개)", ""]
    if missing:
        md += ["| 섹션 | 숫자 | 숫자 확인 판정 | 문장 |", "|---|---|---|---|"]
        md += [f"| {_cell(r.get('section'))} | {_cell(r['raw'])} | {STATUS_KO.get(r.get('status'), r.get('status'))} | {_cell(r['sentence'])} |" for r in missing]
    else:
        md.append("없음 — 본문 숫자가 모두 원본에 있다.")
    md += ["", "## 숫자별 대조", "", "| 섹션 | 숫자 | 원본 | 원본 위치 | 비고 |", "|---|---|---|---|---|"]
    for r in rows:
        f = r["found"]
        if f:
            md.append(f"| {_cell(r.get('section'))} | {_cell(r['raw'])} | 있음 | p.{f['page']} {_cell(f['where'])} | {f['note']} |")
        else:
            md.append(f"| {_cell(r.get('section'))} | {_cell(r['raw'])} | **없음** | | {STATUS_KO.get(r.get('status'), '')} |")
    Path(args.out).write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\n→ {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
