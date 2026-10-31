"""양식 2.0 틀(blueprint) — 레이아웃 분석(layout.py) → 보고서 틀. 코드가 골격을 정하고 LLM(글만 한 번)은 일반화만 한다.

코드가 정하는 것: 부분(part) 순서·역할(표지·요약·장·부록·고지), 장 = 띠 글자(또는 장 제목), 장마다 샘플 소제목 자리(순서·개수),
                 표·그림이 어느 자리 뒤에 오는지(요약 본문 아래·사이드바·소주제 뒤·부록), 테마(색·크기)·머리글/바닥글, 표 양식(행·열·들여쓰기·모양).
LLM 이 하는 것: 샘플 소제목(회사마다 다른 주장) → 일반 소주제 이름과 작성 안내, 장 안내, 문체, 요소 규칙 문구. 실패하면 규칙 대체(장 이름 + 번호).
회사 고유 숫자·내용은 틀에 넣지 않는다(예시 글은 문체 참고로 짧게만).

blueprint = {
  version: 2, source: {file, pages},
  theme: {accent, bandFill, bandText, sidebarFill, captionColor, captionSize, bodySize, headlineSize, bandSize, sourceSize, tableSize},
  page: {header: [{text, align}], footer: [{text, align}]},
  parts: [
    {id:"cover", role:"cover", title, checkpoints: n, fields: [..]},
    {id:"summary", role:"summary", title, layout:"main+sidebar", claims: n, blocks:[formId], sidebar:[formId], examples:[주장 예시]},
    {id:"c1", role:"chapter", title, band: bool, keyline: bool, guide, subtopics:[{title, guide, example, blocks:[formId]}]},
    {id:"appendix", role:"appendix", title, blocks:[formId]},
    {id:"disclaimer", role:"disclaimer", title},
  ],
  forms: {formId: {id, kind:"table"|"figure"|"note", title, page, position, ...표: stub, unit, columns, headGroups, rows[{label, unit, indent, bold, group}], look}},
  rules: {claim, keyline, para, caption, source}, style, name, desc
}
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .layout import _is_grey

logger = logging.getLogger(__name__)

_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"
_UNIT = re.compile(r"\(([^()]*?(?:억원|백만원|십억원|천원|원|%|배|%p|bp|주|만주|백만주|USD|달러|조원))\)\s*$")
_BULLET = re.compile(r"^\s*[■•▪●◆\-]\s*")

DEFAULT_RULES = {
    "claim": "요약 주장 — 회사·산업·실적 가운데 하나를 한 줄 주장으로(25자 안팎, 숫자 하나 정도). 바로 아래 본문 2~4문장이 그 주장을 숫자와 근거로 받친다.",
    "keyline": "핵심 문장 — 옆 문단의 요지 한 문장(40자 안팎, 좁은 칸에서 2~4줄로 접힌다)을 굵게. 요지가 뚜렷한 문단에만 둔다.",
    "para": "본문 — 문단마다 3~5문장, 첫 문장에 요지. 숫자는 단위·기준 시점과 함께, 문장 끝에 출처.",
    "caption": "그림·표 제목 — '대상 + 내용'(예: '○○ 연간 매출액 추이'). 번호 없이.",
    "source": "자료 줄 — 그림·표 바로 아래 '자료: 출처 이름'.",
}


def _unit_of(label: str, fallback: str = "") -> Tuple[str, str]:
    m = _UNIT.search(label or "")
    return (m.group(1).strip(), label) if m else (fallback, label)


def _table_form(t: Dict[str, Any], fid: str, position: str) -> Dict[str, Any]:
    stub = t.get("stub") or ""
    table_unit = (_UNIT.search(stub).group(1) if _UNIT.search(stub) else "") or (re.sub(r"[()]", "", stub) if re.fullmatch(r"\(.*\)", stub) else "")
    if not table_unit and t.get("unitNote"):  # 제목 줄 오른쪽 '(단위: 억원, %)' — 금액 단위(첫 것)가 표 단위
        table_unit = re.split(r"[,/·]", t["unitNote"])[0].strip()
    rows = []
    for r in t.get("rows") or []:
        unit, _label = _unit_of(r.get("label") or "", table_unit if not r.get("group") else "")
        # 소수 자릿수 = 샘플 값 칸의 최빈 자릿수(서식 — 값 자체는 틀에 넣지 않는다)
        decs = [len(v.split(".")[1]) if "." in v else 0 for v in (re.sub(r"[^\d.\-]", "", x) for x in r.get("values") or []) if re.fullmatch(r"-?[\d]+(?:\.\d+)?", v or "")]
        rows.append({"label": r.get("label") or "", "unit": unit, "indent": int(r.get("indent") or 0), "bold": bool(r.get("bold")), "group": bool(r.get("group")),
                     **({"decimals": max(set(decs), key=decs.count)} if decs else {}),
                     # 강조 행 — 행 이름 글자가 색(동종 업종 밸류에이션의 대상 기업 행 빨강): 행 전체를 그 색으로
                     **({"color": r["color"]} if r.get("color") and not _is_grey(r["color"]) else {}),
                     # 샘플 값 — 양식 화면 미리보기만 쓴다(채우기는 원장으로, research/form_rows 는 이 값을 보지 않는다)
                     "sample": [str(v) for v in r.get("values") or []]})
    form = {"id": fid, "kind": "table", "title": t.get("title") or "", "page": t.get("page"), "position": position, "stub": stub, "unit": table_unit,
            "columns": list(t.get("columns") or []), "rows": rows, "look": t.get("look") or {}, "source": bool(t.get("source")),
            "captionStyle": t.get("captionStyle"), "sourceStyle": t.get("sourceStyle"), "bbox": t.get("bbox")}
    if t.get("unitNote"):
        form["unitNote"] = t["unitNote"]  # 제목 줄 오른쪽 '(단위: …)' 그대로 — 화면·Word 가 제목 옆에
    notes = [n for n in t.get("notes") or [] if re.match(r"^\s*(주|Note|Notes)\s*[:：)\d]", n, re.I)]
    if notes:
        form["noteSample"] = notes  # 표 아래 '주:' 줄(샘플 글 — 미리보기만, 문서는 쓰는 사람이 적는다)
    if t.get("headGroups"):
        # 묶음 머리 — 레이아웃의 {label, from, to}(열 번호)를 화면·Word 표 블록 꼴(첫 열 뒤 [{label, span, group?}] — research/block.py)로
        spans: List[Dict[str, Any]] = []
        k, n = 0, len(form["columns"])
        while k < n:
            g = next((g for g in t["headGroups"] if g.get("from") == k and g.get("to", k) >= k), None)
            if g is not None:
                span = min(int(g["to"]), n - 1) - k + 1
                spans.append({"label": g.get("label") or "", "span": span, "group": True})
                k += span
            else:
                spans.append({"label": "", "span": 1})
                k += 1
        form["headGroups"] = spans
    return form


def _figure_form(f: Dict[str, Any], fid: str, position: str) -> Dict[str, Any]:
    return {"id": fid, "kind": "note" if f.get("kind") == "note" else "figure", "title": f.get("title") or "", "page": f.get("page"), "position": position,
            "source": bool(f.get("source")), "captionStyle": f.get("captionStyle"), "sourceStyle": f.get("sourceStyle"), "bbox": f.get("bbox"),
            **({"chart": f["chart"]} if f.get("chart") else {})}  # 차트 모양(종류·계열 색·값 표시·범주) — 채울 때 우리 자료로 같은 꼴(research/form_charts)


def skeleton(lay: Dict[str, Any], file_name: str) -> Dict[str, Any]:
    """레이아웃 → 틀 골격(LLM 없이). 장·소주제 자리는 샘플 그대로 두고 example 에 샘플 글을 둔다."""
    pages = lay["page_list"]
    objs = {o["id"]: o for o in lay["tables"] + lay["figures"]}
    forms: Dict[str, Dict[str, Any]] = {}
    seen_titles: Dict[str, int] = {}

    def form_of(ref: str, position: str) -> Optional[str]:
        o = objs.get(ref)
        if o is None or (o in lay["figures"] and not o.get("title")):
            return None  # 제목 없는 그림 조각은 틀에 넣지 않는다
        # 열 이름이 하나도 없는 '표'(이름 붙은 막대 차트 — 행 이름은 있어도 열 머리가 없다)는 그림 자리로
        is_table = o in lay["tables"] and (any(c for c in o.get("columns") or []) or o.get("stub") or len(o.get("columns") or []) <= 1)
        base = re.sub(r"[^0-9A-Za-z가-힣]+", "", o.get("title") or "")[:16] or ("표" if is_table else "그림")
        n = seen_titles.get(base, 0) + 1
        seen_titles[base] = n
        fid = f"{'t' if is_table else 'f'}_{base}{'' if n == 1 else n}"
        forms[fid] = _table_form(o, fid, position) if is_table else _figure_form(o, fid, position)
        return fid

    parts: List[Dict[str, Any]] = []
    chapter: Optional[Dict[str, Any]] = None
    sub: Optional[Dict[str, Any]] = None
    appendix: Optional[Dict[str, Any]] = None
    for pg in pages:
        role = pg["role"]
        els = pg["elements"]
        if role == "cover":
            titles = [e["text"] for e in els if e["kind"] == "title"]
            bullets = [e for e in els if _BULLET.match(e.get("text") or "")]
            parts.append({"id": "cover", "role": "cover", "title": "표지", "checkpoints": len(bullets) or 3, "fields": ["회사명(종목코드)", "한 줄 제목", "시장·업종", "작성일"], "examples": titles[:3]})
            continue
        if role == "summary":
            claims = [e["text"] for e in els if e["kind"] == "headline" and e["column"] == "main"]
            main = [form_of(e["ref"], "main") for e in els if e.get("ref") and e["column"] == "main"]
            side = [form_of(e["ref"], "sidebar") for e in els if e.get("ref") and e["column"] == "side"]
            parts.append({"id": "summary", "role": "summary", "title": "요약", "layout": "main+sidebar" if pg.get("sidebar") else "single", "claims": len(claims) or 3,
                          "blocks": [x for x in main if x], "sidebar": [x for x in side if x], "examples": claims[:5]})
            continue
        if role == "disclaimer":
            parts.append({"id": "disclaimer", "role": "disclaimer", "title": "고지"})
            continue
        if role == "appendix":
            if appendix is None:
                appendix = {"id": "appendix", "role": "appendix", "title": "부록", "blocks": []}
                parts.append(appendix)
            appendix["blocks"] += [x for x in (form_of(e["ref"], "main") for e in els if e.get("ref")) if x]
            continue
        # 장 쪽·이어지는 쪽 — 띠가 있으면 그 쪽에서 장이 시작하고, 요소 순서대로 장 제목(띠 없는 문서)·소주제·표·그림
        def new_chapter(title: str, band: bool) -> Dict[str, Any]:
            c = {"id": f"c{sum(1 for p in parts if p['role'] == 'chapter') + 1}", "role": "chapter", "title": title, "band": band, "keyline": False, "subtopics": []}
            parts.append(c)
            return c

        if pg.get("band") and (chapter is None or chapter["title"] != pg["band"]["text"]):
            chapter, sub = new_chapter(pg["band"]["text"], True), None
        for e in els:
            if e["kind"] == "chapter":
                chapter, sub = new_chapter(e["text"], False), None
                continue
            if chapter is None:
                continue
            # pattern = 샘플 소주제의 짜임(K 핵심 문장 · P 본문 문단 · M 작은 제목 · 표·그림 id) — 작성기가 이 순서로 쓰고 표·그림 자리를 잡는다
            if e["kind"] == "headline":
                sub = {"title": "", "example": e["text"], "guide": "", "blocks": [], "pattern": []}
                chapter["subtopics"].append(sub)
            elif e["kind"] == "keyline":
                chapter["keyline"] = True
                if sub is not None:
                    sub["pattern"].append("K")
            elif e["kind"] in ("para", "minor") and sub is not None:
                sub["pattern"].append("P" if e["kind"] == "para" else "M")
            elif e.get("ref"):
                fid = form_of(e["ref"], "main")
                if fid:
                    (sub["blocks"] if sub is not None else chapter.setdefault("blocks", [])).append(fid)
                    if sub is not None:
                        sub["pattern"].append(fid)
    for p in parts:
        if p["role"] == "chapter" and not p["subtopics"]:
            p["subtopics"] = [{"title": "", "example": "", "guide": "", "blocks": p.pop("blocks", [])}]
    if appendix is not None:
        titles = " ".join(forms[b]["title"] for b in appendix["blocks"] if b in forms)
        appendix["title"] = "재무제표" if re.search(r"손익|재무상태|현금흐름|Financial|Income|Balance", titles, re.I) else "부록"
    th = lay["theme"]
    sizes = [o["sourceStyle"]["size"] for o in lay["tables"] + lay["figures"] if o.get("sourceStyle")]
    tsize = [t["look"].get("fontSize") for t in lay["tables"] if t.get("look", {}).get("fontSize")]
    theme = {"accent": th.get("accent"), "bandFill": th.get("bandFill"), "bandText": th.get("bandText"), "sidebarFill": th.get("sidebarFill"),
             "captionColor": th.get("captionColor"), "captionSize": th.get("captionSize"), "bodySize": th.get("bodySize"), "headlineSize": th.get("headlineSize"),
             "bandSize": th.get("bandSize"), "sourceSize": max(set(sizes), key=sizes.count) if sizes else None, "tableSize": max(set(tsize), key=tsize.count) if tsize else None}
    page = {"header": [{"text": h["text"], "align": h["align"]} for h in lay.get("header") or []][:2],
            "footer": [{"text": h["text"], "align": h["align"]} for h in lay.get("footer") or [] if not re.fullmatch(r"\d+", h["text"])][:2]}
    # 머리글·바닥글이 글자가 아니면(로고 그림 — KIRS) 기본 꼴: 왼쪽 '대상 | 코드', 오른쪽 작성일, 바닥 오른쪽 쪽 번호
    if not page["header"]:
        page["header"] = [{"text": "{subject}", "align": "left"}, {"text": "{date}", "align": "right"}]
    if not page["footer"]:
        page["footer"] = [{"text": "{page}", "align": "right"}]
    return {"version": 2, "source": {"file": file_name, "pages": lay["pages"]}, "theme": theme, "page": page, "parts": parts, "forms": forms, "rules": dict(DEFAULT_RULES), "style": "", "name": "", "desc": ""}


def _fallback_names(bp: Dict[str, Any]) -> None:
    """LLM 이 없을 때 — 소주제 이름 = 장 이름 + 번호(겹치지 않게), 안내 = 샘플 소제목을 '예: …'로."""
    for p in bp["parts"]:
        if p["role"] != "chapter":
            continue
        for k, s in enumerate(p["subtopics"]):
            if not s.get("title"):
                s["title"] = f"{p['title']} {_CIRCLED[k] if k < len(_CIRCLED) else k + 1}"
            if not s.get("guide") and s.get("example"):
                s["guide"] = f"샘플 소제목 예: '{s['example']}' — 이 회사에 맞는 주장 한 줄로 바꿔 쓴다."
    bp["name"] = bp.get("name") or re.sub(r"\.[A-Za-z0-9]+$", "", bp["source"]["file"])[:60]


def style_facts(lay: Dict[str, Any]) -> Dict[str, Any]:
    """샘플 본문 집계(코드) — 문장 끝맺음 비율, 문단당 문장 수, 핵심 문장 줄 수, 요약 본문 줄 수. LLM 은 문체 안내를 이 사실대로 쓴다."""
    paras = [e["text"] for p in lay["page_list"] for e in p["elements"] if e["kind"] == "para" and len(e["text"]) > 40]
    sents = [x.strip() for t in paras for x in re.split(r"(?<=[.다요])\s+", t) if len(x.strip()) > 8]
    ends = {"~다.": sum(1 for x in sents if re.search(r"(?<!니)다\.?$", x)), "~니다.": sum(1 for x in sents if re.search(r"니다\.?$", x)),
            "명사형(~임·~함·~중)": sum(1 for x in sents if re.search(r"(임|함|음|중|전망|기대|예상)\.?$", x))}
    total = max(1, sum(ends.values()))
    keys = [e["text"].count("\n") + 1 for p in lay["page_list"] for e in p["elements"] if e["kind"] == "keyline"]
    return {"ends": {k: round(v * 100 / total) for k, v in ends.items()}, "sentencesPerPara": round(len(sents) / max(1, len(paras)), 1),
            "keylineLines": round(sum(keys) / len(keys), 1) if keys else None}


PROMPT = """아래는 보고서 샘플 한 편에서 코드가 읽은 틀(장·소제목·요약 주장·표 이름)이다. 다른 회사·다른 대상에도 쓸 수 있게 '일반화'해서 JSON 하나로만 답한다(설명·코드 블록 없이).
{"name": "양식 이름(보고서 종류, 회사 이름 없이, 20자 안)",
 "subject": "샘플이 다룬 대상(회사) 이름 — 샘플에 쓰인 그대로",
 "desc": "어떤 보고서인지 한 문장",
 "style": "문체 안내 3~5줄 — 문장 끝맺음, 문단 길이, 숫자·단위 표기, 소제목 꼴(아래 '샘플 집계'의 사실을 그대로 따른다)",
 "chapters": [{"title": "장 제목(샘플 그대로)", "guide": "이 장에 무엇을 어떤 근거로 쓰는지 1~2문장",
               "subtopics": [{"title": "일반 소주제 이름(회사 이름·숫자 없이, 12자 안, 예: 기업 소개·제품 및 매출 구성·주요 고객·최대 주주)", "guide": "무엇을 어떤 근거로 쓰는지 1~2문장"}]}],
 "forms": [{"id": "아래 '표·그림' 의 id 그대로", "title": "일반 제목(대상 회사 이름 자리는 {subject}, 제품·고객·경쟁사 등 고유 이름과 연도 없이, 20자 안. 예: '{subject} 주요 연혁'·'제품별 매출 비중'·'글로벌 시장 전망')"}]}
규칙:
- chapters 는 아래 장과 같은 개수·같은 순서. subtopics 도 장마다 샘플 소제목과 같은 개수·같은 순서로, 샘플 소제목이 무엇을 다루는지 보고 일반 이름을 붙인다.
- forms 는 아래 '표·그림' 의 모든 id 에 하나씩. 샘플 제목에 고유 이름이 없으면(예: 'Company Data'·'포괄손익계산서') 샘플 제목을 글자 그대로 둔다.
- 제품 하나를 보여 주는 그림(제품 사진·제품명 제목)은 업종 단어도 빼고 '주요 제품 ①'·'주요 제품 ②' 처럼 번호로 둔다. 경쟁사 그림은 '경쟁사 ① 실적 추이' 처럼.
- 소주제 이름은 문서 안에서 겹치지 않게.
- 회사 이름·고유 숫자·제품 이름은 이름과 안내에 넣지 않는다."""


def _llm_input(bp: Dict[str, Any], lay: Dict[str, Any]) -> str:
    out = [f"샘플 파일: {bp['source']['file']}"]
    summ = next((p for p in bp["parts"] if p["role"] == "summary"), None)
    if summ:
        out.append("요약 쪽 주장 예시: " + " / ".join(summ.get("examples") or []))
    paras: Dict[str, str] = {}  # 샘플 소제목 → 그 아래 첫 문단 앞부분
    cur: Optional[str] = None
    for pg in lay["page_list"]:
        for e in pg["elements"]:
            if e["kind"] == "headline":
                cur = e["text"]
            elif e["kind"] == "para" and cur and cur not in paras:
                paras[cur] = e["text"][:120]
    for p in bp["parts"]:
        if p["role"] != "chapter":
            continue
        out.append(f"장: {p['title']}")
        for s in p["subtopics"]:
            first = paras.get(s.get("example") or "", "")
            out.append(f"  - 샘플 소제목: {s.get('example') or '(없음)'}" + (f" | 첫 문단: {first}" if first else ""))
    out.append("표·그림(id: 샘플 제목):")
    out += [f"  {f['id']}: {f['title']}" for f in bp["forms"].values() if f.get("title")]
    return "\n".join(out)


async def generalize(bp: Dict[str, Any], lay: Dict[str, Any], llm: Any) -> bool:
    """LLM 으로 소주제 이름·안내·문체를 일반화(골격은 그대로). 성공하면 True, 실패하면 규칙 대체."""
    from app.templates_import.analyze import _ask

    chapters = [p for p in bp["parts"] if p["role"] == "chapter"]
    # 추론 모델은 생각 글자도 출력 상한에 든다 — 4000 이면 답이 잘려 JSON 이 깨진다(2026-10-30 실측, 서버 두 번 모두)
    raw = await _ask(llm, f"{PROMPT}\n\n{_llm_input(bp, lay)}", 9000) if llm is not None else None
    ok = False
    if raw and isinstance(raw.get("chapters"), list) and len(raw["chapters"]) == len(chapters):
        used: set = set()
        for p, rc in zip(chapters, raw["chapters"]):
            p["guide"] = str(rc.get("guide") or "").strip()[:300]
            subs = rc.get("subtopics") if isinstance(rc.get("subtopics"), list) else []
            if len(subs) != len(p["subtopics"]):
                continue
            for s, rs in zip(p["subtopics"], subs):
                t = re.sub(r"\s+", " ", str((rs or {}).get("title") or "")).strip()[:30]
                if t and t not in used:
                    s["title"] = t
                    used.add(t)
                s["guide"] = str((rs or {}).get("guide") or "").strip()[:300]
        # 표·그림 제목 — 샘플 회사·제품 이름을 뺀 일반 제목(대상 자리 {subject} 는 문서의 대상으로 바뀐다). 샘플 제목은 sampleTitle 에.
        # 표는 원본 제목이 양식의 일부라 샘플 회사 이름이 든 것만 바꾼다(그림은 자리뿐이라 제품 이름까지 일반화)
        subject = re.sub(r"\s+", "", str(raw.get("subject") or ""))
        for rf in raw.get("forms") if isinstance(raw.get("forms"), list) else []:
            f = bp["forms"].get(str((rf or {}).get("id") or ""))
            t = re.sub(r"\s+", " ", str((rf or {}).get("title") or "")).strip()[:40]
            if f is None or not t or t == f["title"]:
                continue
            if f["kind"] == "table" and not (subject and subject in f["title"].replace(" ", "")):
                continue
            f["sampleTitle"], f["title"] = f["title"], t
        bp["name"] = str(raw.get("name") or "").strip()[:60]
        bp["desc"] = str(raw.get("desc") or "").strip()[:200]
        bp["style"] = str(raw.get("style") or "").strip()[:800]
        ok = True
    _fallback_names(bp)
    return ok


def to_v1(bp: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """옛 화면·도구용 sections·assets — 장마다 섹션(요약 포함), 표 양식은 v1 에셋 모양(원본 잘라 보기 box 포함)."""
    sections = []
    for p in bp["parts"]:
        if p["role"] in ("summary", "chapter", "appendix"):
            guide = p.get("guide") or ("; ".join(s["title"] for s in p.get("subtopics") or []) if p["role"] == "chapter" else "")
            sections.append({"id": p["id"], "title": p["title"], "level": 1, "guide": guide[:600], "slots": []})
    W, H = 595.32, 841.92
    assets = []
    for f in bp["forms"].values():
        if f["kind"] != "table":
            continue
        part = next((p["id"] for p in bp["parts"] if f["id"] in (p.get("blocks") or []) + (p.get("sidebar") or []) + [b for s in p.get("subtopics") or [] for b in s.get("blocks") or []]), None)
        box = f.get("bbox")
        assets.append({"id": f["id"], "kind": "table", "name": f["title"] or "표", "desc": "", "sectionId": part, "position": "sidebar" if f["position"] == "sidebar" else "main",
                       "source": {"page": f.get("page"), "box": [round(box[0] / W, 4), round(box[1] / H, 4), round(box[2] / W, 4), round(box[3] / H, 4)] if box else None, "caption": f["title"]},
                       "caption": {"label": "", "numbered": False}, "sourceLine": bool(f.get("source")), "note": False,
                       "table": {"stub": f.get("stub") or "", "rowKind": "항목", "rows": len(f["rows"]), "groups": [{"label": "", "unit": f.get("unit") or "", "columns": f.get("columns") or []}]},
                       "look": {"headerFill": "#FFFFFF", "headerText": "#000000", "rule": (f.get("look") or {}).get("topRule") or (f.get("look") or {}).get("rule"), "lines": (f.get("look") or {}).get("lines") or "horizontal",
                                "numberAlign": "right", "captionBold": True, "captionColor": (f.get("captionStyle") or {}).get("color")}})
    return sections, assets


async def build_blueprint(path: str, file_name: str, llm: Any) -> Optional[Dict[str, Any]]:
    """글자층 PDF → {blueprint, proposal(v1 호환)}. 글자층이 없으면 None(VL 경로)."""
    import asyncio

    from app.templates_import.layout import analyze_layout

    lay = await asyncio.to_thread(analyze_layout, path)
    if not lay.get("ok"):
        return None
    bp = skeleton(lay, file_name)
    try:
        await generalize(bp, lay, llm)
    except Exception:  # noqa: BLE001 — 일반화가 실패해도 골격으로
        logger.exception("blueprint generalize failed")
        _fallback_names(bp)
    sections, assets = to_v1(bp)
    return {"name": bp["name"], "desc": bp["desc"], "style": bp["style"], "sections": sections, "assets": assets, "blueprint": bp, "pages": {"read": lay["pages"], "total": lay["pages"]}}


__all__ = ["DEFAULT_RULES", "build_blueprint", "generalize", "skeleton", "to_v1"]
