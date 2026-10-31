"""루틴(화면 없는 작성)의 자동 목차 — 양식 2.0 틀 문서는 대화로 소주제 제목(회사에 대한 주장 한 줄)과 범위를 사용자와 정한 뒤 썼다.
루틴은 그 단계가 없어 섹션마다 회사 소개를 되풀이하고, 자료 없는 자리를 일반론으로 채우고, 소제목이 자리 이름('기업 소개') 그대로였다(2026-10-31 시험).

그래서 쓰기 전에 장마다 한 번:
  자리(소주제)마다 따로 자료를 찾고(대화 규칙과 같다 — 여러 자리를 한 질의에 묶지 않는다) →
  LLM 이 자리마다 {소제목 주장 한 줄, 다룰 범위, 근거가 있나, 없으면 필요한 자료} 를 낸다(JSON, 글만 — 숫자는 쓰는 단계가 자료로) →
  코드가 소제목을 바꾸고(update_outline rename 과 같다), 범위와 '같은 장 다른 자리의 범위(쓰지 않을 것)'를 그 섹션의 작성 지시로 넘기며,
  근거가 없는 자리는 쓰지 않고 남긴다(경고에 필요한 자료). LLM 이 실패하면 자리 이름 그대로 쓰는 예전 방식으로 간다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from app.agent.session import Doc
from app.docs.chunk import preview
from app.docs.store import doc_label, load_meta, search_docs
from app.llm.base import ChatParams

log = logging.getLogger(__name__)
PER_SLOT = 5  # 자리마다 찾을 문단 수
SNIPPET = 220

PROMPT = """너는 기업분석 보고서의 목차를 정한다. 아래는 한 장(章)의 소주제 자리와, 자리마다 따로 찾은 자료다.
자리마다 정할 것:
- title: 이 회사에 대한 사실 주장 한 줄(25자 안팎, 예: '정밀 구동 부품 제조사, 2022년 코스닥 상장' · '베어링·감속기가 매출 대부분'). 자료에 있는 사실로만.
  자리 이름('기업 소개')을 되풀이하지 않는다.
- scope: 이 자리에서 다룰 것 1~2문장. 같은 장의 다른 자리와 겹치지 않게 나눈다. 회사 일반 소개(설립·대표자·소재지·상장)는 첫 자리에만.
- evidence: 그 자리의 주제를 쓸 자료가 있으면 true. 찾은 자료가 회사 일반 소개뿐이고 그 자리 주제(예: 주요 고객 이름·매출 의존도)가 없으면 false.
- need: evidence 가 false 면 필요한 자료(예: '사업보고서 주요 거래처 현황'), 아니면 빈 문자열.
JSON 만 출력한다: {"slots": [{"n": 1, "title": "…", "scope": "…", "evidence": true, "need": ""}, …]}"""


def _subtopic(doc: Doc, sec: Dict[str, Any]) -> Dict[str, Any]:
    cov = (sec.get("covers") or [""])[0]
    part = next((p for p in (doc.get("layout") or {}).get("parts") or [] if cov.startswith(f"{p.get('id')}_")), None)
    try:
        k = int(cov.split("_")[1]) - 1
    except (IndexError, ValueError):
        return {}
    subs = (part or {}).get("subtopics") or []
    return subs[k] if 0 <= k < len(subs) else {}


def _name(subject: str) -> str:
    """'에스비비테크(코스닥 389500, …) 기업분석 보고서' → '에스비비테크' — 검색어에는 회사 이름만(긴 설명을 붙이면 질의가 흐려져 주주 표를 못 찾았다)."""
    return re.split(r"[(（,\s]", (subject or "").strip())[0][:40]


def _material(doc_ids: Sequence[str], queries: List[str]) -> List[str]:
    seen, out = set(), []
    for h in search_docs(doc_ids, queries, k=PER_SLOT, per_doc=2, exclude_disclaimer=True):
        key = (h["docId"], (h.get("chunk") or {}).get("id"))
        if key in seen:
            continue
        seen.add(key)
        text = (h.get("chunk") or {}).get("text") or ""
        out.append(f"  - [{doc_label(load_meta(h['docId']), h['docId'])}] {preview(text, SNIPPET)}")
    return out


def _json(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M))
    try:
        v = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


async def plan_chapter(llm: Any, doc: Doc, part: Dict[str, Any], steps: Sequence[str], doc_ids: Sequence[str], subject: str) -> List[Dict[str, Any]]:
    """한 장의 자리들(steps 안의 소주제 섹션) → [{step, name(자리 이름), title, scope, evidence, need}]. 실패하면 []."""
    secs = [s for s in doc.get("sections") or [] if s.get("part") == part.get("id") and s.get("role") == "subsection" and s["step"] in steps]
    if not secs:
        return []
    blocks: List[str] = []
    for n, s in enumerate(secs, 1):
        st = _subtopic(doc, s)
        guide = re.split(r"(?<=[.!?。])\s+", str(st.get("guide") or "").strip())[0]
        qs = [q for q in [f"{_name(subject)} {s['title']}".strip(), s["title"], guide] if q]
        mat = await asyncio.to_thread(_material, doc_ids, qs)
        blocks.append(f"[{n}] 자리 이름: {s['title']}" + (f" / 안내: {guide}" if guide else "") + "\n" + ("\n".join(mat) if mat else "  - (찾은 자료 없음)"))
    content = f"{PROMPT}\n\n## 대상\n{subject or '(대상 기업)'}\n\n## 장: {part.get('title') or ''}" + (f" — {part['guide']}" if part.get("guide") else "") + "\n\n" + "\n\n".join(blocks)
    try:
        res = await llm.complete("chat", ChatParams(messages=[{"role": "user", "content": content}], temperature=0.2, max_tokens=1500, reasoning_effort="low", timeout_s=120))
    except Exception:  # noqa: BLE001 — 목차를 못 정하면 자리 이름 그대로 쓴다
        log.exception("auto outline failed: %s", part.get("title"))
        return []
    got = _json(getattr(res, "content", "") or "") or {}
    by_n = {int(x.get("n") or 0): x for x in got.get("slots") or [] if isinstance(x, dict)}
    out: List[Dict[str, Any]] = []
    for n, s in enumerate(secs, 1):
        x = by_n.get(n) or {}
        title = re.sub(r"\s+", " ", str(x.get("title") or "")).strip()[:40]
        out.append({"step": s["step"], "name": s["title"], "title": title or s["title"], "scope": re.sub(r"\s+", " ", str(x.get("scope") or "")).strip()[:240],
                    "evidence": x.get("evidence") is not False, "need": str(x.get("need") or "").strip()[:120]})
    return out


def brief_for(plan: List[Dict[str, Any]], step: str) -> str:
    """그 섹션의 작성 지시 — 이 자리의 범위 + 같은 장 다른 자리의 범위(쓰지 않을 것)."""
    me = next((p for p in plan if p["step"] == step), None)
    if not me:
        return ""
    others = [f"「{p['title']}」: {p['scope']}" for p in plan if p["step"] != step and p["scope"]]
    lines = [f"이 자리의 소제목: {me['title']}"] + ([f"이 자리에서 다룰 것: {me['scope']}"] if me["scope"] else [])
    if others:
        lines.append("같은 장의 다른 자리가 다룰 것(여기서 쓰지 않는다 — 회사 일반 소개도 첫 자리에서만): " + " / ".join(others))
    return "\n".join(lines)


__all__ = ["plan_chapter", "brief_for"]
