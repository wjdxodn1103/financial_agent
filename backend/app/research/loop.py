"""AI 채팅 한 턴 — 문서 작성 채팅(agent/loop.run_chat)을 줄인 판. 쓰기·카드 없음, 표 도구가 있다.

이벤트: status · meta · text · text_replace · tool_start · tool_end · table_update · template_saved · error · done.
트랜스크립트(새로고침 복원)는 문서 작성과 같은 모양에 tables([{id, title}]) 가 더해진다 — 화면이 결과 카드로 그린다.
답 속 [S번호] 는 '(문서명, p.n)' 링크(#cite=문서~문단)로 바꿔, 누르면 오른쪽에서 원문이 열린다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.agent.loop import TranscriptBuilder, humanize_error, salvage_json
from app.agent.session import history_messages, push_history
from app.agent.tools import ToolContext
from app.docs.citations import strip_tokens
from app.docs.search_tool import S_REF_RUN, SourceBook, doc_index_lines
from app.ids import id36
from app.llm.base import ChatParams, merge_tool_call_deltas
from app.research.service import template_line
from app.research.tools import TOOL_NAMES, TOOLS, ResearchContext, run_tool

logger = logging.getLogger(__name__)
MAX_TURNS = 8
CHAT_MAX_TOKENS = 3000
DOC_LINES_MAX = 30
_INTERNAL = re.compile(r"\[내부 메모[^\]]*\]\s*")
_TOOL_RX = re.compile("|".join(TOOL_NAMES))
_SPLIT = re.compile(r"(?<=[.!?。]\s)|(?<=\n)")

SYSTEM = """너는 투자·금융 실무자의 리서치 보조다. 워크스페이스에서 쓸 수 있는 자료(사내 공용 데이터 포함)만 근거로 답한다. 오늘은 {today}.
- 수치 질문은 lookup_figures(근거 원장)로 먼저, 문장 근거는 search_documents 로 찾는다. 근거가 된 결과의 [S번호] 를 문장 끝에 단다.
- 증감률·비율은 직접 계산하지 말고 calculate 로.
- 여러 기업·문서·기간을 같은 항목으로 비교하거나 정리해 달라면 바로 build_table 로 표를 만든다(표가 칸마다 자료를 직접 찾으니 미리 lookup_figures·search_documents 를 부르지 않는다). 맞는 표 양식이 있으면 template 에 그 이름을 넣고, 질문 표는 columns 에 질문을 넣는다.
- 표는 오른쪽 패널에 보인다 — 표 내용을 글로 다시 늘어놓지 않는다. 표에 행·열을 더하거나 기간을 바꾸라면 update_table.
- "양식으로 저장·등록" 은 save_template — 기본은 열만 고정(행은 매번), 행도 고정해 달라면 keep_rows. 팀이 같이 쓰게 해 달라면 scope=workspace.
- "드라이브에 저장" 은 save_table_to_drive.
- 자료에 없으면 "자료에서는 확인되지 않습니다"라고 말한다. 숫자를 지어내지 않는다.
- 한국어 존댓말, 짧게. 도구 이름·F번호·D번호·표 id·내부 메모는 말하지 않는다. 마크다운 제목은 쓰지 않는다.

## 표 양식
{templates}

## 지금 보는 표
{current}

## 쓸 수 있는 자료
{documents}"""


def research_system(doc: Dict[str, Any]) -> str:
    cur = doc.get("_current") or None
    if cur:
        data = cur.get("data") or {}
        rows = ", ".join(s["label"] for s in data.get("subjects") or [])
        cols = ", ".join(it["label"] for it in data.get("items") or [] if not it.get("hidden"))
        period = (data.get("period") or {}).get("label")
        current = f"'{cur['title']}' — 행: {rows} / 열: {cols}" + (f" / 기준 {period}" if period else "")
    else:
        current = "(없음)"
    docs = doc_index_lines(doc.get("documentIds") or [])
    more = f"\n… 외 {len(docs) - DOC_LINES_MAX}건" if len(docs) > DOC_LINES_MAX else ""
    return SYSTEM.format(
        today=date.today().isoformat(),
        templates="\n".join(template_line(t) for t in doc.get("_templates") or []) or "(없음)",
        current=current,
        documents=("\n".join(docs[:DOC_LINES_MAX]) + more) if docs else "(없음)",
    )


def clean_text(text: str, book: SourceBook) -> str:
    """도구 이름이 든 문장·내부 메모는 빼고, [S번호] 는 눌러서 원문을 여는 링크로."""
    if not text:
        return ""
    s = "".join(p for p in _SPLIT.split(text) if not _TOOL_RX.search(p))
    s = _INTERNAL.sub("", s)

    def cite(m: re.Match) -> str:
        links = []
        for n in dict.fromkeys(int(x) for x in re.findall(r"(\d+)", m.group(0))):
            it = book.get(n)
            if it:
                links.append(f"[{book.label_of(n)}](#cite={it['docId']}~{it['chunk']})")
        return f" ({'; '.join(links)})" if links else ""

    return strip_tokens(S_REF_RUN.sub(cite, s))


def _shown(args: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in args.items():
        if k.startswith("_"):
            continue
        out[k] = ", ".join(str(x.get("label") if isinstance(x, dict) else x) for x in v)[:120] if isinstance(v, list) else str(v)[:120]
    return out


def _first_line(result: str) -> str:
    return _INTERNAL.sub("", result.split("\n")[0])[:160]


async def run_research_turn(doc: Dict[str, Any], text: str, llm: Any, emit_raw: Callable[[Dict[str, Any]], None], save: Callable[[], Awaitable[None]]) -> None:
    asst_id = id36("m", 5)
    tb = TranscriptBuilder(asst_id)  # table_update 를 받으면 메시지에 tables 를 남긴다

    def emit(e: Dict[str, Any]) -> None:
        tb.apply(e)
        emit_raw(e)

    emit({"type": "status", "stage": "route"})
    emit({"type": "meta", "sessionId": doc.get("id"), "model": llm.chat_model})
    doc.setdefault("transcript", []).append({"id": f"u{asst_id[1:]}", "role": "user", "text": text})
    agent_ctx = ToolContext(doc=doc, llm=llm, emit=emit, user_text=text)
    rc = ResearchContext(doc=doc, llm=llm, emit=emit, agent=agent_ctx)
    new_history: List[Dict[str, Any]] = [{"role": "user", "content": text}]
    answered = cancelled = False
    try:
        messages: List[Dict[str, Any]] = [{"role": "system", "content": research_system(doc)}, *history_messages(doc), {"role": "user", "content": text}]
        for _turn in range(MAX_TURNS):
            params = ChatParams(messages=messages, tools=TOOLS, tool_choice="auto", temperature=0.3, max_tokens=CHAT_MAX_TOKENS, reasoning_effort="low")
            content = ""
            acc: Dict[int, Dict[str, Any]] = {}
            async for d in llm.stream("chat", params):
                if d.content:
                    content += d.content
                    emit({"type": "text", "delta": d.content})
                if d.tool_calls:
                    merge_tool_call_deltas(acc, d.tool_calls)
            answered = answered or bool(content or acc)
            cleaned = clean_text(content, agent_ctx.book)
            if cleaned != content:
                emit({"type": "text_replace", "text": tb.msg["text"][: len(tb.msg["text"]) - len(content)] + cleaned})
            if not acc:
                if cleaned:
                    new_history.append({"role": "assistant", "content": cleaned})
                break
            calls = []
            for idx in sorted(acc):
                slot = acc[idx]
                name = re.sub(r"[^A-Za-z0-9_.-]", "", re.sub(r"<\|[\s\S]*$", "", slot.get("name") or ""))
                calls.append({"id": slot.get("id") or id36("t", 4), "name": name, "args": slot.get("arguments") or ""})
            assistant_msg = {"role": "assistant", "content": content or None, "tool_calls": [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["args"] or "{}"}} for c in calls]}
            messages.append(assistant_msg)
            new_history.append(assistant_msg)
            for c in calls:
                try:
                    parsed = json.loads(c["args"]) if c["args"] else {}
                    args = parsed if isinstance(parsed, dict) else {}
                except ValueError:
                    args = salvage_json(c["args"]) or {}
                emit({"type": "tool_start", "id": c["id"], "name": c["name"], "args": _shown(args)})
                status = "done"
                try:
                    result = await run_tool(c["name"], args, rc)
                except asyncio.CancelledError:
                    raise
                except Exception as err:  # noqa: BLE001
                    logger.exception("research tool %s failed", c["name"])
                    status, result = "error", f"도구 오류: {err}"
                emit({"type": "tool_end", "id": c["id"], "name": c["name"], "status": status, "summary": _first_line(result)})
                tool_msg = {"role": "tool", "tool_call_id": c["id"], "content": result}
                messages.append(tool_msg)
                new_history.append(tool_msg)
    except asyncio.CancelledError:
        cancelled = True
        raise
    except Exception as err:  # noqa: BLE001
        logger.exception("research turn failed")
        emit({"type": "error", "message": humanize_error(err), "code": getattr(err, "code", None)})
    finally:
        if answered and not cancelled:
            push_history(doc, new_history)
        doc.setdefault("transcript", []).append(tb.msg)
        await save()
        emit_raw({"type": "done"})
