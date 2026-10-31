"""문서 양식을 말로 고치기 — "2번 섹션 안내를 이렇게 바꿔줘", "이 표 이름을 …로"처럼 적으면 LLM 이 양식(JSON)을 고쳐 돌려준다.

고칠 수 있는 것: 이름·설명·문체, 섹션(제목·수준·안내 — 더하기·빼기·순서), 표·차트 양식(이름·설명·차트 종류·빼기 — 새로 만들지는 못한다).
돌려받은 것은 registry.update_format 으로 저장한다(화면에서 직접 고친 것과 같은 검사). 옛 양식의 섹션 자리(slots)는 같은 섹션 id 면 그대로 둔다.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.llm.base import ChatParams

logger = logging.getLogger(__name__)

PROMPT = """아래는 보고서 '문서 양식'(JSON)이다. 사용자 요청대로 고친 양식을 JSON 하나로만 답한다(설명·코드 블록 없이).
{"summary": "무엇을 고쳤는지 한 문장",
 "format": {"name": "", "desc": "", "style": "",
            "sections": [{"id": "s1", "title": "", "level": 1, "guide": ""}],
            "assets": [{"id": "a1", "name": "", "desc": "", "chartType": "line|bar|barh|area|pie|combo|band|other 또는 표면 빈 문자열"}]}}
규칙:
- 요청과 상관없는 부분은 글자 하나 바꾸지 않고 그대로 둔다.
- 섹션은 더하기·빼기·순서 바꾸기·수준(1~3) 바꾸기를 할 수 있다. 있던 섹션은 id 를 그대로 두고, 새 섹션은 id 를 빈 문자열로.
- 표·차트(assets)는 이름·설명·차트 종류를 고치거나 뺄 수만 있다(새로 만들지 않는다). 남길 것은 id 를 그대로.
- 요청을 이 양식으로 할 수 없으면 format 은 그대로 두고 summary 에 이유를 적는다."""


def _json(text: str) -> Optional[Dict[str, Any]]:
    t = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M)
    m = re.search(r"\{[\s\S]*\}", t)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except ValueError:
        return None


def current(view: Dict[str, Any]) -> Dict[str, Any]:
    """양식 화면 모양(registry._row_view) → LLM 에 보일 고칠 수 있는 부분만."""
    return {
        "name": view["title"],
        "desc": view.get("desc") or "",
        "style": view.get("style") or "",
        "sections": [{"id": s.get("id") or "", "title": s["title"], "level": s.get("level") or 1, "guide": s.get("guide") or ""} for s in view.get("sections") or []],
        "assets": [{"id": a["id"], "name": a["name"], "desc": a.get("desc") or "", "chartType": (a.get("chart") or {}).get("type") or ""} for a in view.get("assets") or []],
    }


def to_body(view: Dict[str, Any], got: Dict[str, Any]) -> Dict[str, Any]:
    """LLM 답 → update_format body. 옛 섹션 자리(slots)는 같은 id 섹션에 그대로."""
    slots = {s.get("id"): s.get("slots") or [] for s in view.get("sections") or []}
    secs: List[Dict[str, Any]] = []
    for s in got.get("sections") or []:
        if isinstance(s, dict) and str(s.get("title") or "").strip():
            sid = str(s.get("id") or "")
            secs.append({**({"id": sid} if sid in slots else {}), "title": s["title"], "level": s.get("level") or 1, "guide": s.get("guide") or "", "slots": slots.get(sid, [])})
    body: Dict[str, Any] = {"name": got.get("name") or view["title"], "desc": got.get("desc", view.get("desc") or ""), "style": got.get("style", view.get("style") or ""), "sections": secs or view.get("sections")}
    if view.get("assets") and isinstance(got.get("assets"), list):  # 목록이 아예 없으면(답이 잘림 등) 표·차트는 그대로
        body["assets"] = [{"id": a.get("id"), "name": a.get("name") or "", "desc": a.get("desc") or "", **({"chartType": a["chartType"]} if a.get("chartType") else {})} for a in got.get("assets") or [] if isinstance(a, dict)]
    return body


async def revise(view: Dict[str, Any], instruction: str, llm: Any) -> Tuple[Dict[str, Any], str]:
    """→ (update_format body, 요약 한 문장). LLM 이 못 고치면 400."""
    text = (instruction or "").strip()[:1000]
    if not text:
        raise HTTPException(400, "어떻게 고칠지 적어 주세요.")
    content = f"{PROMPT}\n\n## 지금 양식\n{json.dumps(current(view), ensure_ascii=False)}\n\n## 사용자 요청\n{text}"
    got = None
    for tokens in (6000, 9600):
        try:
            res = await llm.complete("chat", ChatParams(messages=[{"role": "user", "content": content}], temperature=0.1, max_tokens=tokens, timeout_s=180))
        except Exception:  # noqa: BLE001 — 한 번 더
            logger.exception("format revise failed")
            continue
        got = _json(getattr(res, "content", "") or "")
        if got and isinstance(got.get("format"), dict):
            break
    if not got or not isinstance(got.get("format"), dict):
        raise HTTPException(502, "AI 가 양식을 고치지 못했습니다. 다시 말해 주세요.")
    return to_body(view, got["format"]), str(got.get("summary") or "").strip()[:300]


__all__ = ["revise"]
