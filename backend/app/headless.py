"""화면 없이 문서 쓰기 — 루틴(예약 작성)·재심의 안건·IC 회의록 정리가 같이 쓴다.

새 문서(양식) → 워크스페이스 맥락 → 섹션마다 작성기(근거 검색·원장·숫자 검사) → AI 초안·근거 고정 → 저장·드라이브 자리.
as_of 면 그날까지의 자료만 쓴다(날짜 지정 재현). 상한(섹션 수·시간·LLM 호출 수)을 넘으면 그때까지 쓴 것만 남기고 멈춘다.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import re
import time
from typing import Any, Dict, List, Optional

from sqlmodel import Session

from app import usage
from app.agent.auto_outline import brief_for
from app.agent.session import find_section, log_section, mark_ai_draft, set_section
from app.agent.writer import write_section
from app.db import ReportSession, User, engine
from app.docs.asof import docs_as_of
from app.docs.citations import token_doc_ids

log = logging.getLogger(__name__)
MAX_SECTIONS = 10
MAX_SECONDS = 15 * 60
LAYOUT_MAX_SECTIONS = 20  # 틀(양식 2.0) 문서 — 장마다 소주제가 있어 섹션이 많다
LAYOUT_MAX_SECONDS = 45 * 60
MAX_CALLS = 120


class Stopped(Exception):
    pass


async def write_report(*, workspace_id: str, owner_id: str, format_id: str, title: str, instruction: str = "", data_scope: Optional[Dict[str, Any]] = None,
                       as_of: Optional[str] = None, folder_id: Optional[str] = None, origin: Optional[Dict[str, Any]] = None, extra_brief: str = "",
                       steps: Optional[List[str]] = None, on_step: Optional[Any] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    """→ {sessionId, written, skipped, warnings, stopped, sec}. 문서는 만든 사람(owner) 이름으로 만든다."""
    from app.llm.client import ReportLlm
    from app.services.report_service import ReportService, _persist_doc, _workspace_context

    started = time.monotonic()
    with Session(engine) as s:
        user = s.get(User, owner_id)
        if user is None:
            raise RuntimeError("만든 사람 계정이 없습니다.")
        payload = ReportService(s).create(workspace_id, user, title=title, report_type=format_id, folder_id=folder_id, data_scope=data_scope)
        sid = payload["session"]["id"] if "session" in payload else payload["id"]
        row = s.get(ReportSession, sid)
        doc = copy.deepcopy(row.doc or {})
    # 양식이 정한 준비 단계 — 쓰기 전에 그날 자료를 새로 받는다(전일 증시 요약: 시세·금리·일정·시장 뉴스 제목 → '증시 요약 데이터' 자료)
    custom = (doc.get("layout") or {}).get("writer") or ""
    if (doc.get("layout") or {}).get("prepare") == "market_daily":
        from app.market import daily

        await asyncio.to_thread(daily.prepare, workspace_id, as_of, owner_id)
    doc.update(await asyncio.to_thread(_workspace_context, workspace_id, doc, owner_id))
    doc_ids = docs_as_of(doc.get("documentIds") or [], as_of)
    doc["origin"] = {**(origin or {}), "asOf": as_of, "headless": True}
    doc["approval"] = {"status": "draft", "label": "AI 초안"}
    llm = ReportLlm()
    written: List[str] = []
    warnings: List[str] = []
    stopped = ""
    # steps = 쓸 섹션(id 또는 제목) · limit = 앞 섹션 몇 개만
    cap, max_seconds = (LAYOUT_MAX_SECTIONS, LAYOUT_MAX_SECONDS) if doc.get("layout") else (MAX_SECTIONS, MAX_SECONDS)
    order = sorted(doc.get("sections") or [], key=lambda x: x.get("role") == "summary")  # 요약(주장 3개)은 본문 장을 다 쓴 뒤
    want = [x["step"] for x in order if not steps or x["step"] in steps or x.get("title") in steps][:min(limit or cap, cap)]
    # 양식 2.0 틀 문서 — 쓰기 전에 장마다 소제목(주장 한 줄)·범위를 자료로 정한다(대화의 목차 합의를 대신 — app/agent/auto_outline.py)
    plans: Dict[str, List[Dict[str, Any]]] = {}
    if doc.get("layout"):
        from app.agent.auto_outline import plan_chapter

        subject = str((doc.get("setup") or {}).get("subject") or re.split(r"(?<=[.。])\s", instruction.strip())[0])[:120]
        for part in doc["layout"].get("parts") or []:
            if part.get("role") != "chapter" or time.monotonic() - started > max_seconds:
                continue
            plan = await plan_chapter(llm, doc, part, want, doc_ids, subject)
            for p in plan:
                plans[p["step"]] = plan
                sec = find_section(doc, p["step"])
                if sec is not None and p["evidence"] and p["title"] != sec["title"]:
                    sec["title"] = p["title"]  # update_outline rename 과 같다
    for step in want:
        if time.monotonic() - started > max_seconds:
            stopped = "시간 상한"
            break
        if usage.calls() > MAX_CALLS:
            stopped = "호출 상한"
            break
        sec = find_section(doc, step)
        if sec is None:
            continue
        me = next((p for p in plans.get(step) or [] if p["step"] == step), None)
        if me and not me["evidence"]:  # 자료에 그 주제가 없는 자리 — 일반론으로 채우지 않고 남긴다
            warnings.append(f"{sec['title']}: 자료 없음 — 필요한 자료: {me['need'] or '이 주제의 자료'}")
            continue
        if on_step:
            on_step(sec["title"])
        scope = brief_for(plans[step], step) if step in plans else ""
        ins = "\n".join(x for x in [instruction.strip(), extra_brief.strip(), scope, f"기준일 {as_of} 까지의 자료만으로 쓴다." if as_of else ""] if x) or None
        try:
            if custom == "market_daily":  # 표·차트는 코드가 채우고 '시장 리뷰' 글만 모델이 쓴다
                from app.market import daily

                res = await daily.write_section(llm, doc, step, as_of)
            else:
                res = await write_section(llm, doc, step, doc_ids=doc_ids, instruction=ins)
        except Exception as e:  # noqa: BLE001 — 한 섹션 실패가 나머지를 막지 않게
            log.exception("headless section failed: %s", step)
            warnings.append(f"{sec['title']}: {str(e)[:120]}")
            continue
        content = res["content"]
        set_section(doc, step, content, {"docIds": token_doc_ids(content), "checks": res["checks"], "warnings": res["warnings"], "calcs": res.get("calcs") or [], "memo": res.get("memo") or "",
                                         "criteria": res.get("criteria") or []})
        mark_ai_draft(doc, step, content)
        log_section(doc, step, f"루틴 작성 · {len(content)}자 · 출처 {res['checks']['citations']}곳")
        written.append(step)
        if res["checks"].get("unitSuspect"):
            warnings.append(f"{sec['title']}: 단위 의심 {len(res['checks']['unitSuspect'])}곳")
        await asyncio.to_thread(_persist_doc, sid, copy.deepcopy(doc))  # 섹션마다 저장(도중에 멈춰도 쓴 것은 남게)
    doc["origin"]["stopped"] = stopped or None
    await asyncio.to_thread(_persist_doc, sid, copy.deepcopy(doc))
    sec_used = round(time.monotonic() - started, 1)
    await asyncio.to_thread(usage.activity, "doc_generated", {"sessionId": sid, "routine": (origin or {}).get("routine")}, {"sec": sec_used, "sections": len(written)}, user=owner_id, ws=workspace_id)
    return {"sessionId": sid, "written": len(written), "sections": len(want), "warnings": warnings, "stopped": stopped or None, "sec": sec_used}
