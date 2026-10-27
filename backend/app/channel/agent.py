"""채널 에이전트 — "@에이전트" 질문에 워크스페이스 자료·근거 원장·팀 기록만으로 답한다(리포트 작성·카드 없음).

도구: search_documents(문단) · lookup_figures(원장 수치) · calculate(코드 계산). 답의 [S번호] 는 그대로 두고 메시지 meta.cites 에
{번호: 문서·문단·이름} 을 실어 화면이 눌러서 원문을 열게 한다. 팀 기록을 말할 때는 작성자·날짜·원문을 그대로.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List

from sqlmodel import Session, select

from app.agent.ledger_brief import CALC_TOOL_NAME, CALC_TOOL_SCHEMA, LedgerBook, select_figures
from app.db import ChannelMessage, Repo, User, engine, evidence_ids
from app.drive import hidden_items
from app.docs.search_tool import S_REF, SEARCH_TOOL_NAME, SEARCH_TOOL_SCHEMA, SourceBook, doc_index_lines, run_search
from app.ledger.service import choices_of
from app.llm.base import ChatParams
from app.records.service import confirmed_notes, notes_lines

ROUNDS = 5
LOOKUP_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "lookup_figures",
        "description": "근거 원장(자료의 표에서 코드가 뽑은 수치)에서 지표·기간을 찾는다. 수치 질문에는 먼저 이것.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "지표와 기간(예: 매출액 2024)"}}, "required": ["query"]},
    },
}
SYSTEM = """너는 투자 실무 팀의 워크스페이스 채널에 있는 리서치 에이전트다. 팀원이 "@에이전트"로 물으면 워크스페이스 자료만 근거로 답한다.
- 수치는 lookup_figures(근거 원장)로 먼저 찾고, 문장 근거는 search_documents 로 찾는다. 근거가 된 결과의 [S번호] 를 문장 끝에 단다.
- 증감률·비율은 직접 계산하지 말고 calculate 에 원장의 F번호로 식을 넣는다. 받은 값과 계산식을 같이 말한다.
- 자료에 없으면 "워크스페이스 자료에서는 확인되지 않습니다"라고 말한다. 지어내지 않는다.
- 팀 기록(결정·지시·방침)이 질문과 관련 있으면 누가 언제 남겼는지와 원문을 그대로 알려 준다.
- 한국어 존댓말, 3~6문장. 도구 이름·F번호·D번호·내부 메모는 말하지 않는다(자료는 이름으로 부른다).
- 출처 표기는 검색·원장 결과의 [S번호] 만 쓴다. 【…】 같은 다른 괄호 표기나 마크다운(**굵게**, 제목)은 쓰지 않는다 — 채팅 화면은 글자 그대로 보인다."""
_INTERNAL = re.compile(r"\[내부 메모[^\]]*\]\s*")
AGENT_STRIP = re.compile(r"@(에이전트|agent|AI)", re.I)


def _context(workspace_id: str, question_id: str) -> Dict[str, Any]:
    with Session(engine) as s:
        ws = Repo(s).workspace(workspace_id)
        q = s.get(ChannelMessage, question_id)
        names = {u.id: f"{u.name} {u.title}".strip() for u in s.exec(select(User)).all()}
        q_thread = q.thread_id if q else None
        where = [ChannelMessage.workspace_id == workspace_id, ChannelMessage.kind == "user"]
        if q_thread:  # 스레드 안 질문이면 그 스레드 대화가 문맥
            where.append((ChannelMessage.thread_id == q_thread) | (ChannelMessage.id == q_thread))  # type: ignore[operator]
        recent = list(s.exec(select(ChannelMessage).where(*where).order_by(ChannelMessage.created_at.desc()).limit(8)).all())  # type: ignore[attr-defined]
        restricted = hidden_items(s, workspace_id, None)  # 모두가 보는 대화 — 멤버 전체 공개가 아닌 폴더 속 데이터는 쓰지 않는다
        return {
            "docIds": [d for d in evidence_ids(ws) if d not in restricted],
            "question": (q.text if q else "").strip(),
            "asker": names.get(q.user_id or "", "") if q else "",
            "recent": [f"{names.get(m.user_id or '', '')}: {m.text[:200]}" for m in reversed(recent) if m.id != question_id],
            "notes": confirmed_notes(s, workspace_id),
            "choices": choices_of(s, workspace_id),
        }


async def answer_question(workspace_id: str, question_id: str) -> Dict[str, Any]:
    from app.llm.client import ReportLlm, provider_ready

    ctx = await asyncio.to_thread(_context, workspace_id, question_id)
    if not provider_ready():
        return {"text": "모델 키가 설정되지 않아 답할 수 없습니다(backend/.env 의 NVIDIA_API_KEY).", "cites": {}}
    doc_ids: List[str] = ctx["docIds"]
    book, lb = SourceBook(), LedgerBook()
    notes = notes_lines(ctx["notes"])
    system = "\n\n".join(
        [
            SYSTEM,
            "## 워크스페이스 자료\n" + ("\n".join(doc_index_lines(doc_ids)) or "없음"),
            *(["## 팀 기록(확정)\n" + "\n".join(notes[:12])] if notes else []),
            *(["## 최근 채널 대화\n" + "\n".join(ctx["recent"])] if ctx["recent"] else []),
        ]
    )
    question = AGENT_STRIP.sub("", ctx["question"]).strip() or ctx["question"]
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": f"{ctx['asker']}: {question}"}]
    llm = ReportLlm()
    tools = [SEARCH_TOOL_SCHEMA, LOOKUP_SCHEMA, CALC_TOOL_SCHEMA]
    content = ""
    for r in range(ROUNDS):
        res = await llm.complete("chat", ChatParams(messages=messages, tools=tools, tool_choice="auto" if r < ROUNDS - 1 else "none", temperature=0.2, max_tokens=2500, reasoning_effort="low", timeout_s=180))
        tcs = res.tool_calls or []
        content = res.content or content
        if not tcs:
            break
        messages.append({"role": "assistant", "content": res.content or None, "tool_calls": tcs})
        for tc in tcs:
            fn = tc.get("function") or {}
            name = re.sub(r"<\|[\s\S]*$", "", fn.get("name") or "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            if name == SEARCH_TOOL_NAME:
                out = (await asyncio.to_thread(run_search, book, doc_ids, args))["text"] if doc_ids else "근거 없음 — 자료가 없습니다."
            elif name == "lookup_figures":
                lines = await asyncio.to_thread(select_figures, doc_ids, ctx["choices"], [str(args.get("query") or "")], book, lb) if doc_ids else []
                out = "\n".join(lines) or "원장에 맞는 수치가 없습니다."
            elif name == CALC_TOOL_NAME:
                out = lb.calculate(args) if lb.refs else "먼저 lookup_figures 로 F번호를 얻는다."
            else:
                out = "없는 도구"
            messages.append({"role": "tool", "tool_call_id": tc.get("id") or f"call_{r}", "content": out})
    text = _INTERNAL.sub("", content or "").strip() or "답을 만들지 못했습니다. 질문을 조금 바꿔 다시 물어봐 주세요."
    cites: Dict[str, Any] = {}
    for m in S_REF.finditer(text):
        for n in re.findall(r"(\d+)", m.group(0)):
            it = book.get(int(n))
            if it:
                cites[n] = {"docId": it["docId"], "chunk": it["chunk"], "label": it["label"], "page": it.get("page")}
    # 번호표에 없는 [S번호] 는 지운다(지어낸 출처 방지)
    text = S_REF.sub(lambda m: "".join(f"[S{n}]" for n in re.findall(r"(\d+)", m.group(0)) if n in cites), text)
    return {"text": text, "cites": cites}
