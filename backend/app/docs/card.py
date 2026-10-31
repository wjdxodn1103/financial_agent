"""문서 카드 — 자료 목록·출처 표기·작성 브리프가 쓰는 서지 정보.

두 단계(OP 의 "임시 카드 → 온디맨드 정리"와 같은 방식):
  A. temp_card: 업로드 직후, LLM 없이 — 제목(PDF 메타데이터·첫 제목 줄·파일명), 문서 종류(키워드), 날짜(정규식).
  B. enrich_card: LLM 1회 — 제목·문서 종류·기준일·발행처·대상 기업·한 줄 요약. 리포트에 인용된 문서와 사용자가 "카드 정리"를
     누른 문서에만(업로드한 문서 전부에 LLM 을 돌리지 않는다).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.llm.base import ChatParams

log = logging.getLogger(__name__)

DOC_TYPES: List[tuple] = [
    ("사업보고서", r"사업\s*보고서|annual\s*report|10-K"),
    ("분기·반기보고서", r"분기\s*보고서|반기\s*보고서|quarterly\s*report|10-Q"),
    ("감사보고서", r"감사\s*보고서|audit"),
    ("IR 자료", r"\bIR\b|investor\s*relations|실적\s*발표|기업\s*설명회|earnings\s*(release|call|presentation)"),
    ("애널리스트 리포트", r"투자\s*의견|목표\s*주가|target\s*price|equity\s*research|리서치\s*센터|매수|buy\s*\(|outperform"),
    ("공시", r"공시|주요\s*사항\s*보고|DART|전자\s*공시"),
    ("내부 규정·지침", r"규정|지침|내규|세칙|매뉴얼|가이드라인|policy|guideline|procedure"),
    ("뉴스·보도자료", r"보도\s*자료|뉴스|기사|press\s*release"),
    ("경제·산업 자료", r"경제\s*전망|산업\s*동향|시장\s*동향|통계|지표|outlook|market\s*report"),
]
_DATE = re.compile(r"((?:19|20)\d{2})\s*[.\-/년]\s*(\d{1,2})(?!\s*(?:분기|Q|차|반기|\d))\s*[.\-/월]?\s*(?:(\d{1,2})\s*일?)?")
_YEAR_Q = re.compile(r"((?:19|20)\d{2})\s*년?\s*([1-4])\s*(?:분기|Q)|([1-4])Q\s*((?:19|20)?\d{2})", re.I)


def guess_doc_type(text: str) -> str:
    for name, rx in DOC_TYPES:
        if re.search(rx, text, re.I):
            return name
    return "기타 문서"


def guess_date(text: str) -> str:
    q = _YEAR_Q.search(text)
    if q:
        return f"{q.group(1)} {q.group(2)}Q" if q.group(1) else f"{q.group(4)} {q.group(3)}Q"
    m = _DATE.search(text)
    if m and 1 <= int(m.group(2)) <= 12:
        y, mo, d = m.group(1), int(m.group(2)), m.group(3)
        return f"{y}-{mo:02d}-{int(d):02d}" if d and 1 <= int(d) <= 31 else f"{y}-{mo:02d}"
    y = re.search(r"(?:19|20)\d{2}", text)
    return y.group(0) if y else ""


def _clean_title(t: str) -> str:
    t = re.sub(r"\s+", " ", t or "").strip(" -–—|·")
    return t[:120]


def temp_card(extracted: Dict[str, Any], file_name: str) -> Dict[str, Any]:
    stem = re.sub(r"[_]+", " ", Path(file_name).stem).strip()
    meta = extracted.get("meta") or {}
    paras = extracted.get("paras") or []
    # PDF 의 첫 제목 줄은 대개 절 제목("II. 사업의 내용")이라 문서 제목으로 쓰지 않는다 — DOCX·MD 는 첫 제목이 곧 문서 제목인 경우가 많다
    first_heading = "" if extracted.get("fileType") == "PDF" else next((p.get("heading") for p in paras if p.get("heading")), "")
    pdf_title = meta.get("title") or ""
    # PDF 메타데이터 제목은 "Microsoft Word - 문서1" 같은 쓰레기가 많다 — 파일명보다 나을 때만
    if pdf_title and (re.search(r"microsoft|untitled|^문서\d*$|\.docx?$|\.hwp", pdf_title, re.I) or len(pdf_title) < 4):
        pdf_title = ""
    title = _clean_title(pdf_title or first_heading or stem) or stem
    probe = f"{file_name}\n{title}\n{(extracted.get('frontText') or '')[:2000]}"
    return {"title": title, "docType": guess_doc_type(probe), "date": guess_date(f"{file_name} {(extracted.get('frontText') or '')[:1500]}"), "issuer": "", "company": "", "oneLine": ""}


CARD_SYSTEM = """너는 금융 문서 서지 정리기다. 문서 앞부분을 읽고 아래 JSON 하나만 출력한다(설명·코드블록 없이).
{"title": "문서 제목(문서에 적힌 그대로, 없으면 내용으로 짧게)",
 "docType": "사업보고서|분기·반기보고서|감사보고서|IR 자료|애널리스트 리포트|공시|내부 규정·지침|뉴스·보도자료|경제·산업 자료|기타 문서 중 하나",
 "date": "기준일 또는 발행일(YYYY-MM-DD, 모르면 YYYY 또는 빈 문자열)",
 "issuer": "작성·발행 기관(증권사·회사·기관명, 모르면 빈 문자열)",
 "company": "다루는 기업명(여럿이면 대표 하나, 없으면 빈 문자열)",
 "oneLine": "문서가 무엇을 다루는지 한국어 한 문장(60자 이내, 문서에 있는 내용만)"}
문서에 없는 정보는 지어내지 말고 빈 문자열로 둔다."""


# 카드 정리가 돌려준 종류를 이 목록 값으로 맞춘다 — 위 DOC_TYPES(이름, 규칙) 의 이름 + 기타 문서(같은 이름으로 덮어쓰면 guess_doc_type 이 깨진다)
DOC_TYPE_NAMES = tuple([name for name, _rx in DOC_TYPES] + ["기타 문서"])


def _doc_type(v: str) -> str:
    """목록 밖 값('반기보고서'·'보도자료')은 낱말이 겹치는 목록 값으로, 없으면 빈 값(기존 추정을 지킨다)."""
    v = v.strip()
    if v in DOC_TYPE_NAMES:
        return v
    for t in DOC_TYPE_NAMES:
        if any(part and part in v for part in re.split(r"[·\s]+", t) if len(part) >= 2 and part not in ("자료", "문서")):
            return t
    return ""


def _json_object(raw: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


async def enrich_card(llm: Any, card: Dict[str, Any], file_name: str, front_text: str) -> Optional[Dict[str, Any]]:
    """LLM 으로 카드 정리 → 새 카드(실패하면 None). 빈 값은 기존 값을 지킨다."""
    user = f"파일명: {file_name}\n현재 제목 추정: {card.get('title') or ''}\n\n[문서 앞부분]\n{front_text[:4000]}"
    params = ChatParams(messages=[{"role": "system", "content": CARD_SYSTEM}, {"role": "user", "content": user}], temperature=0.0, max_tokens=1200, reasoning_effort="none", timeout_s=120)
    try:
        res = await llm.complete("chat", params)
    except Exception as e:  # noqa: BLE001
        log.warning("[card] enrich failed: %s", e)
        return None
    got = _json_object(res.content)
    if not got:
        log.warning("[card] enrich returned no JSON: %r", (res.content or "")[:120])
        return None
    out = dict(card)
    if isinstance(got.get("docType"), str):
        got["docType"] = _doc_type(got["docType"])
    for k in ("title", "docType", "date", "issuer", "company", "oneLine"):
        v = got.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()[:160]
    return out
