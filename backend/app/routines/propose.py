"""말로 루틴 등록 — 요청 문장에서 이름·양식·일정·지시를 뽑아 등록 창에 채울 값으로 돌려준다(저장하지 않는다 — 사람이 등록 창에서 확인).
양식은 목록에 있는 것만 고른다(없으면 비워 사람이 고르게)."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

from fastapi import HTTPException

from app.routines.service import _schedule

log = logging.getLogger(__name__)
PROMPT = """아래 요청을 반복 업무(루틴) 등록 값으로 바꾼다. JSON 하나로만 답한다(설명·코드 블록 없이).
{"name": "업무 이름(20자 이내, 명사구)", "formatId": "양식 목록의 id 그대로(맞는 것이 없으면 빈 문자열)", "schedule": {"every": "daily|weekdays|weekly|manual", "time": "HH:MM", "weekday": 0},
 "instruction": "쓸 때 지킬 것 한두 문장(요청에 있는 것만)"}
규칙:
- every: '매일' daily · '평일'·'영업일' weekdays · '매주 ○요일' weekly(weekday 0=월 … 6=일) · 때를 말하지 않으면 manual. time 은 24시간제(말하지 않으면 07:00).
- 양식은 이름·내용이 요청과 가장 가까운 것 하나. 요청에 없는 내용을 지어내지 않는다."""


async def propose(instruction: str, types: List[Dict[str, str]], llm: Any = None) -> Dict[str, Any]:
    from app.llm.base import ChatParams
    from app.llm.client import ReportLlm

    text = (instruction or "").strip()[:600]
    if not text:
        raise HTTPException(400, "어떤 업무를 언제 할지 적어 주세요.")
    listing = "\n".join(f"- {t['id']}: {t['title']}" for t in types)
    content = f"{PROMPT}\n\n## 양식 목록\n{listing}\n\n## 요청\n{text}"
    try:
        res = await (llm or ReportLlm()).complete("chat", ChatParams(messages=[{"role": "user", "content": content}], temperature=0.1, max_tokens=2000, reasoning_effort="low", timeout_s=90))
        m = re.search(r"\{[\s\S]*\}", re.sub(r"^```(?:json)?|```$", "", (getattr(res, "content", "") or "").strip(), flags=re.M))
        got = json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001
        log.exception("routine propose failed")
        raise HTTPException(502, "등록 값을 만들지 못했습니다. 다시 말해 주세요.") from None
    ids = {t["id"] for t in types}
    return {"name": str(got.get("name") or "").strip()[:40], "formatId": got.get("formatId") if got.get("formatId") in ids else "",
            "schedule": _schedule(got.get("schedule") if isinstance(got.get("schedule"), dict) else {}), "instruction": str(got.get("instruction") or "").strip()[:400], "source": {"kind": "chat"}}
