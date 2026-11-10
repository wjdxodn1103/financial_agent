"""에이전트 루프 — OP `paper/agent/loop.py` 이식(스트리밍 + tool_calls 델타 누적 + 도구 루프).

`run_turn(doc, body, llm, emit, save)` 가 서비스가 부르는 단일 진입점 — body 에 approval 이 있으면 run_approval, 아니면 run_chat.
 - run_chat: 채팅 모델이 도구를 골라 부른다. 작성·수정 요청은 카드 없이 이 턴에서 바로 쓰고(direct) 작업 설명(explain)으로 끝낸다.
 - run_approval: 예전 대화에 남은 카드의 승인 → 서버가 섹션을 쓰고(writer) → 같은 작업 설명.
어떤 경로로 끝나도 transcript·추천 칩·저장·done 을 낸다(빠지면 화면이 멈춘다).
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from app.agent.events import Emit, Event, ev
from app.agent.explain import explain_section
from app.agent.modes import RESEARCH_ONLY, WRITING_ONLY_RESEARCH, normalize as normalize_modes, plain_history, tool_defs
from app.agent.plan import remaining_plan
from app.agent.progress import progress, suggest_next
from app.agent.prompts import chat_system
from app.agent.session import mark_ai_draft
from app.anchors import pin_text
from app.agent.session import Doc, add_section, find_by_title, find_section, history_messages, log_section, push_history, set_section, written_sections
from app.agent.tools import TOOL_NAMES, ToolContext, card_fields, run_tool
from app.agent.writer import write_section
from app.docs.citations import strip_tokens, token_doc_ids
from app.docs.queue import enqueue_cited
from app.docs.search_tool import S_REF_RUN, SourceBook
from app.ids import id36
from app.llm.base import ChatParams, LlmError, merge_tool_call_deltas

logger = logging.getLogger(__name__)

Save = Callable[[], Union[None, Awaitable[None]]]
MAX_TURNS = 8
CHAT_MAX_TOKENS = 4000
# 앞 턴의 작업 설명('**…** 섹션을 고쳐 썼습니다 (1,047자).')을 흉내 내 도구 없이 끝낸 답 — 본문은 그대로인데 고쳤다고 말한다(2026-10-30 실측)
_FAKE_DONE = re.compile(r"섹션을\s*(?:고쳐\s*)?썼습니다")
# 검색·계산 도구만 부르고 작업 설명 꼴('이렇게 쓴 이유'·'사용한 근거')까지 흉내 낸 답도 있다(2026-10-30 실측 10번 중 9번) — 작성 도구를 불렀는지로 가린다
_WRITE_TOOLS = {"write_section", "revise_section", "continue_plan"}


def _wrote(history: List[Dict[str, Any]]) -> bool:
    return any((tc.get("function") or {}).get("name") in _WRITE_TOOLS for m in history if m.get("role") == "assistant" for tc in m.get("tool_calls") or [])


async def _call_save(save: Optional[Save]) -> None:
    if save is None:
        return
    r = save()
    if inspect.isawaitable(r):
        await r


class TranscriptBuilder:
    """화면 트랜스크립트용 assistant 메시지를 이벤트에서 조립한다(서버도 같은 규칙으로 저장 → 새로고침 복원)."""

    def __init__(self, id_: str):
        self.msg: Dict[str, Any] = {"id": id_, "role": "assistant", "text": ""}

    def apply(self, e: Event) -> None:
        m = self.msg
        t = e.get("type")
        if t == "text":
            m["text"] += e.get("delta", "")
        elif t == "text_replace":
            m["text"] = e.get("text", "")
        elif t == "tool_start":
            m.setdefault("tools", []).append({"id": e.get("id"), "name": e.get("name"), "args": e.get("args"), "status": "running"})
        elif t == "tool_end":
            m["tools"] = [{**x, "status": e.get("status"), "summary": e.get("summary")} if x.get("id") == e.get("id") else x for x in m.get("tools") or []]
        elif t == "section_update":
            keep = [u for u in m.get("sectionUpdates") or [] if u.get("step") != e.get("step")]
            m["sectionUpdates"] = [*keep, {k: e[k] for k in ("step", "title", "chars", "checks", "warnings", "covers") if e.get(k) is not None}]
        elif t == "approval":
            keys = ("question", "action", "kind", "steps", "options", "covers", "instruction", "documents", "itemDesc", "inputFields", "inputs", "note", "notes")
            m["approval"] = {**{k: e[k] for k in keys if e.get(k) is not None}, "state": "pending"}
        elif t == "plan_update":
            m["plan"] = {k: e[k] for k in ("items", "done", "note", "proposed") if e.get(k) is not None}
        elif t == "error":
            m["error"] = {"message": e.get("message"), **({"code": e["code"]} if e.get("code") else {})}
        elif t == "table_update":
            # 리서치 표·차트 — 화면이 메시지 아래 결과 카드로 그린다
            tb = e.get("table") or {}
            keep = [x for x in m.get("tables") or [] if x.get("id") != tb.get("id")]
            m["tables"] = [*keep, {"id": tb.get("id"), "title": tb.get("title")}]
        elif t == "proposal":
            # 대화로 등록 — 루틴·수집 소스 확인 카드(사람이 [등록]해야 저장)
            m["proposals"] = [*(m.get("proposals") or []), e.get("proposal") or {}]
        elif t == "item_link":
            # 찾아서 연 문서·데이터 파일 — 화면이 여는 버튼으로 그린다
            m["links"] = [*(m.get("links") or []), e.get("item") or {}]
        elif t in ("import_item", "import_format"):
            # 양식 샘플 카드 — 표·차트 하나씩(등록할까요?) + 리포트 양식(한꺼번에)
            box = m.setdefault("imports", {"id": e.get("importId"), "items": [], "format": None})
            if t == "import_item":
                box["items"].append(e.get("item") or {})
            else:
                box["format"] = e.get("format")


# ── 출력 필터 ─────────────────────────────────────────────────────────────

_TOOL_NAME_RX = re.compile("|".join([*TOOL_NAMES, *RESEARCH_ONLY, *WRITING_ONLY_RESEARCH]))
_RESEARCH_TOOLS = frozenset([*RESEARCH_ONLY, *WRITING_ONLY_RESEARCH])
_CHAT_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。]\s)|(?<=\n)")
_INTERNAL = re.compile(r"\[내부 메모[^\]]*\]\s*")


def clean_chat_text(text: str, book: Optional[SourceBook] = None) -> str:
    """도구 이름이 든 문장은 빼고, 채팅 답의 [S번호] 는 출처 링크 '([문서명, p.12](#cite=문서~문단))' 로 — 누르면 원문, 메모로 남겨도 출처가 이어진다."""
    if not text:
        return ""
    s = "".join(p for p in _CHAT_SENTENCE_SPLIT.split(text) if not _TOOL_NAME_RX.search(p))
    s = _INTERNAL.sub("", s)

    def cite(m: re.Match) -> str:
        links = []
        for n in dict.fromkeys(int(x) for x in re.findall(r"(\d+)", m.group(0))):
            it = book.get(n) if book else None
            if it:
                links.append(f"[{book.label_of(n)}](#cite={it['docId']}~{it['chunk']})")
        return f" ({'; '.join(links)})" if links else ""

    s = S_REF_RUN.sub(cite, s)
    return strip_tokens(s)


def salvage_json(raw: str) -> Optional[Dict[str, Any]]:
    """출력 상한에 걸려 잘린 도구 인자 JSON 을 되살린다(OP 그대로). 못 살리면 None."""
    suffixes = ["", '"', '"]', '"]}', "]}", "}", '"}', "}]}"]
    cut = len(raw)
    while cut > 0:
        head = raw[:cut]
        for suf in suffixes:
            try:
                v = json.loads(head + suf)
            except ValueError:
                continue
            if isinstance(v, dict):
                return {**v, "_truncated": True}
        cut = max(raw.rfind(",", 0, cut), 0)
    return None


def humanize_error(err: BaseException) -> str:
    """사용자에게 보이는 오류 문장 — 서버 내부 메시지를 그대로 내보내지 않는다."""
    msg = str(err) or ""
    if isinstance(err, LlmError):
        if err.code == "RATE_LIMITED":
            return "요청이 몰려 잠시 기다려야 합니다. 조금 뒤에 다시 보내 주세요."
        if err.code == "PROVIDER_AUTH":
            return "모델 서버 인증에 실패했습니다. backend/.env 의 NVIDIA_API_KEY 를 확인해 주세요."
        if err.code == "MODEL_NOT_FOUND":
            return "모델을 찾을 수 없습니다. backend/.env 의 CHAT_MODEL·WRITER_MODEL 을 확인해 주세요."
        if err.code == "PROVIDER_UNREACHABLE":
            return "모델 서버가 제한 시간 안에 응답하지 못했습니다. 같은 내용을 다시 보내 주세요."
        if err.code == "PROVIDER_ERROR" and re.search(r"\(5\d\d\)", msg):
            return "모델 서버가 잠시 응답하지 못했습니다. 같은 내용을 다시 보내 주세요."
    return msg or "알 수 없는 오류"


def _shown_args(args: Dict[str, Any]) -> Dict[str, str]:
    return {k: v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for k, v in args.items()}


def _summary(result: str) -> str:
    return _INTERNAL.sub("", result.split("\n")[0])[:160]


# ── 채팅 턴 ───────────────────────────────────────────────────────────────

_REPEATABLE_ONCE = re.compile(r"^(write_section|revise_section|propose_plan|continue_plan|update_outline|set_report_meta)$")


async def run_chat(doc: Doc, text: str, llm: Any, emit_raw: Emit, save: Optional[Save] = None, modes: Optional[Dict[str, Any]] = None) -> None:
    """한 턴 — 켜진 모드(리서치·문서 작성)의 도구·프롬프트만. 둘 다 끄면 도구 없는 일반 대화."""
    asst_id = id36("m", 5)
    mode = normalize_modes(modes, doc)
    doc["modes"] = mode
    defs = tool_defs(mode)
    allowed = {d["function"]["name"] for d in defs}
    tb = TranscriptBuilder(asst_id)

    def emit(e: Event) -> None:
        tb.apply(e)
        emit_raw(e)

    emit(ev("status", stage="route"))
    emit(ev("meta", sessionId=doc.get("id"), model=llm.chat_model))
    doc.setdefault("transcript", []).append({"id": f"u{asst_id[1:]}", "role": "user", "text": text})
    doc.pop("pendingApproval", None)  # 새 메시지를 보내면 떠 있던 카드는 닫힌 것으로 본다(FE 도 같은 규칙)
    new_history: List[Dict[str, Any]] = [{"role": "user", "content": text}]
    executed: set[str] = set()
    ctx = ToolContext(doc=doc, llm=llm, emit=emit, user_text=text)
    rc: Any = None
    answered = False
    cancelled = False
    pushed = False
    nudged = False
    try:
        past = history_messages(doc) if defs else plain_history(doc.get("history") or [])
        messages: List[Dict[str, Any]] = [{"role": "system", "content": chat_system(doc, mode)}, *past, {"role": "user", "content": text}]
        for _turn in range(MAX_TURNS):
            params = ChatParams(messages=messages, tools=defs or None, tool_choice="auto" if defs else None, temperature=0.3, max_tokens=CHAT_MAX_TOKENS, reasoning_effort="low")
            content = ""
            acc: Dict[int, Dict[str, Any]] = {}
            async for d in llm.stream("chat", params):
                if d.content:
                    content += d.content
                    emit(ev("text", delta=d.content))
                if d.tool_calls:
                    merge_tool_call_deltas(acc, d.tool_calls)
            answered = bool(content or acc) or answered
            cleaned = clean_chat_text(content, ctx.book)
            if cleaned != content:
                emit(ev("text_replace", text=cleaned))
            if not acc:
                if mode.get("writing") and _FAKE_DONE.search(cleaned or "") and not _wrote(new_history):
                    if not nudged:
                        # 지우고 한 번 다시 부른다 — 이번에는 도구를 부르거나 못 하는 이유를 말하게
                        nudged = True
                        emit(ev("text_replace", text=""))
                        messages += [{"role": "assistant", "content": cleaned},
                                     {"role": "user", "content": "[내부 메모] 방금 답은 섹션을 썼다고 했지만 작성 도구(write_section·revise_section)를 부르지 않아 본문은 그대로다. "
                                                                 "작업 설명('이렇게 쓴 이유'·'사용한 근거')은 시스템이 작성 뒤에 붙이는 것이라 직접 쓰지 않는다. 요청대로 하려면 그 도구를 지금 부른다. 할 수 없으면 그 이유만 짧게 말한다."}]
                        continue
                    cleaned = "섹션 본문을 쓰거나 고치지 못했습니다(작성 도구가 실행되지 않았습니다). 같은 요청을 다시 보내 주세요."
                    emit(ev("text_replace", text=cleaned))
                if cleaned:
                    new_history.append({"role": "assistant", "content": cleaned})
                break
            # gpt-oss(NIM) 는 도구 이름에 harmony 채널 토큰("…<|channel|>commentary")을 섞기도 한다 → 정제
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
                emit(ev("tool_start", id=c["id"], name=c["name"], args=_shown_args(args)))
                status = "done"
                try:
                    key = f"{c['name']}:{json.dumps(args, ensure_ascii=False, sort_keys=True)}"
                    if key in executed and _REPEATABLE_ONCE.match(c["name"]):
                        result = "[내부 메모] 같은 인자로 이미 실행했습니다. 앞의 결과를 사용자에게 알리고 끝내세요."
                    elif c["name"] in allowed and c["name"] in _RESEARCH_TOOLS:
                        if rc is None:
                            from app.research.tools import ResearchContext

                            rc = ResearchContext(doc=doc, llm=llm, emit=emit, agent=ctx)
                        from app.research.tools import run_tool as run_research_tool

                        result = await run_research_tool(c["name"], args, rc)
                    elif c["name"] in allowed:
                        result = await run_tool(c["name"], args, ctx)
                    else:
                        result = f"[내부 메모] {c['name']} 은(는) 지금 켜진 모드에 없는 도구입니다. 쓸 수 있는 도구: {', '.join(sorted(allowed)) or '없음'}."
                    executed.add(key)
                except asyncio.CancelledError:
                    raise
                except Exception as err:  # noqa: BLE001
                    logger.exception("tool %s failed", c["name"])
                    status, result = "error", f"도구 오류: {err}"
                emit(ev("tool_end", id=c["id"], name=c["name"], status=status, summary=_summary(result)))
                tool_msg = {"role": "tool", "tool_call_id": c["id"], "content": result}
                messages.append(tool_msg)
                new_history.append(tool_msg)
            pa = doc.get("pendingApproval")
            if pa and pa.get("direct"):
                # 전문가용 — 카드 없이 이 턴에서 바로 쓰고 작업 설명을 보낸다(대화 기록을 먼저 남겨 순서를 지킨다)
                doc.pop("pendingApproval", None)
                new_history.append({"role": "assistant", "content": f"[바로 작성: {pa['question']}]"})
                push_history(doc, new_history)
                pushed = True
                await _write_approved(doc, {"approved": True}, pa, llm, emit, save, pa.get("action") or "plan", ctx.lb.calcs)  # 대화가 먼저 계산한 값도 계산 기록으로
                break
            if pa:
                # 카드가 떴으면 모델을 다시 부르지 않는다(마무리 호출에서 "네, 승인합니다" 같은 역할극이 나온다 — OP 실측)
                new_history.append({"role": "assistant", "content": f"[확인 카드 표시: {pa['question']}]"})
                break
    except asyncio.CancelledError:
        cancelled = True
        raise
    except Exception as err:  # noqa: BLE001
        logger.exception("run_chat failed")
        msg = humanize_error(err)
        emit(ev("error", message=msg, code=getattr(err, "code", None)))
    finally:
        if answered and not cancelled and not pushed:
            push_history(doc, new_history)
        doc.setdefault("transcript", []).append(tb.msg)
        if tb.msg.get("text"):
            try:
                tb.msg["anchors"] = await asyncio.to_thread(pin_text, tb.msg["text"])  # 답의 출처 문단을 지금 원문으로 얼린다
            except Exception:  # noqa: BLE001 — 고정 실패가 답을 막지 않게
                logger.exception("pin answer cites failed")
        emit(ev("suggestions", chips=suggestions_for(doc)))
        await _call_save(save)
        emit_raw(ev("done"))


# ── 승인 → 작성 ───────────────────────────────────────────────────────────

async def run_approval(doc: Doc, approval: Dict[str, Any], llm: Any, emit_raw: Emit, save: Optional[Save] = None) -> None:
    approved = bool(approval.get("approved"))
    action = approval.get("action") or "plan"
    message_id = approval.get("messageId")
    asst_id = id36("m", 5)
    tb = TranscriptBuilder(asst_id)

    def emit(e: Event) -> None:
        tb.apply(e)
        emit_raw(e)

    pending = doc.get("pendingApproval") or {}
    transcript: List[Dict[str, Any]] = doc.setdefault("transcript", [])
    card = next((m for m in transcript if m.get("id") == message_id), None) or next((m for m in reversed(transcript) if (m.get("approval") or {}).get("state") == "pending"), None)
    if card and card.get("approval"):
        card["approval"]["state"] = "approved" if approved else "rejected"
        if approved and approval.get("label"):
            card["approval"]["chosen"] = approval["label"]
    doc.pop("pendingApproval", None)
    emit(ev("meta", sessionId=doc.get("id"), model=llm.writer_model))
    try:
        if not approved:
            line = "고치지 않았습니다. 본문은 그대로입니다." if action == "revise" else ("지금은 쓰지 않습니다. 계획은 남겨 두었습니다." if pending.get("fromPlan") else "지금은 쓰지 않습니다.")
            emit(ev("text", delta=line))
            push_history(doc, [{"role": "user", "content": f"[카드 거절] {action}"}, {"role": "assistant", "content": line}])
            return
        await _write_approved(doc, approval, pending, llm, emit, save, action)
    except asyncio.CancelledError:
        # 중단된 승인 턴: 히스토리에 결과를 남겨 다음 요청이 새 카드를 띄우게 한다(OP 2026-09-29 사고 — "카드가 아직 떠 있다"고 답하는 잠금)
        doc.setdefault("history", []).extend([{"role": "user", "content": f"[카드 승인] {action}"}, {"role": "assistant", "content": "[작성 중단됨] 사용자 요청으로 중단되어 섹션은 쓰이지 않았고 카드는 닫혔습니다."}])
        raise
    except Exception as err:  # noqa: BLE001
        logger.exception("run_approval failed")
        emit(ev("error", message=humanize_error(err), code=getattr(err, "code", None)))
    finally:
        transcript.append(tb.msg)
        emit(ev("suggestions", chips=suggestions_for(doc)))
        await _call_save(save)
        emit_raw(ev("done"))


async def _write_approved(doc: Doc, approval: Dict[str, Any], pending: Dict[str, Any], llm: Any, emit: Emit, save: Optional[Save], action: str, turn_calcs: Optional[List[Dict[str, Any]]] = None) -> None:
    # 카드 2단계에서 받은 사용자 입력 — 세션에 누적(같은 key 는 다음 카드에 미리 채운다)
    inputs = {k: v for k, v in (approval.get("inputs") or {}).items() if isinstance(v, str) and v.strip()}
    if inputs:
        doc["userInputs"] = {**(doc.get("userInputs") or {}), **inputs}
    all_docs = doc.get("documentIds") or []
    chosen = approval.get("documents")
    doc_ids = [d for d in all_docs if d in chosen] if isinstance(chosen, list) else list(all_docs)
    card_instruction = (approval.get("instruction") or "").strip()

    if action == "revise":
        steps = pending.get("steps") or []
        # 카드가 세션에서 사라진 뒤(새 메시지·재시작) 승인이 오면 카드에 실린 제목으로 찾는다
        sec = find_section(doc, steps[0]) if steps else find_by_title(doc, (approval.get("steps") or [""])[0])
        if sec is None or not sec.get("content"):
            emit(ev("text", delta="고칠 섹션을 찾지 못했습니다. 다시 요청해 주세요."))
            return
        instruction = "\n".join(x for x in [(pending.get("instruction") or "").strip(), card_instruction] if x) or "사용자 요청에 따라 고쳐 쓴다"
        previous = sec["content"]
    else:
        items = pending.get("plan") or []
        if not items:
            # 카드가 세션에서 사라진 뒤(재시작) 승인이 오면 카드에 실린 제목으로 되살린다
            items = [{"title": t, "covers": list(approval.get("covers") or [])} for t in (approval.get("steps") or [])[:1]]
        if not items:
            emit(ev("text", delta="작성할 섹션이 없었습니다."))
            return
        it = items[0]
        sec = find_section(doc, it.get("sectionId")) or find_by_title(doc, it["title"])
        if sec is None:
            sec = add_section(doc, it["title"], it.get("covers") or [], after=it.get("after"))
            emit(ev("outline_update", sections=doc["sections"]))
        instruction = "\n".join(x for x in [it.get("instruction") or "", card_instruction] if x) or None
        previous = sec.get("content") or None
    if card_instruction:
        log_section(doc, sec["step"], f"사용자 요청: {card_instruction}")

    tid = id36("t", 4)
    tool_name = "revise_section" if action == "revise" else "write_section"
    emit(ev("tool_start", id=tid, name=tool_name, args={"section": sec["title"], "documents": str(len(doc_ids))}))
    item_keys = {f["key"] for f in card_fields(doc, list(sec.get("covers") or [])).get("inputFields") or []}
    user_info = {k: v for k, v in (doc.get("userInputs") or {}).items() if k in item_keys}
    try:
        res = await write_section(llm, doc, sec["step"], doc_ids=doc_ids, instruction=instruction, user_info=user_info, previous_text=previous, on_stage=lambda stage: emit(ev("status", stage=stage)), extra_calcs=turn_calcs or [])
    except Exception:
        emit(ev("tool_end", id=tid, name=tool_name, status="error", summary=f"{sec['title']} 작성 실패"))  # 화면의 도구 줄이 계속 도는 채로 남지 않게
        raise
    content = res["content"]
    set_section(doc, sec["step"], content, {"docIds": token_doc_ids(content), "checks": res["checks"], "warnings": res["warnings"], "calcs": res.get("calcs") or [], "memo": res.get("memo") or "",
                                            "criteria": res.get("criteria") or []})
    mark_ai_draft(doc, sec["step"], content)  # 사람이 고친 정도(사용자 수정률)·근거 고정
    doc["lastWrittenStep"] = sec["step"]
    log_section(doc, sec["step"], f"{'수정' if action == 'revise' else '작성'} · {len(content)}자 · 출처 {res['checks']['citations']}곳")
    enqueue_cited(content)  # 인용된 문서만 카드 정리(LLM)를 뒤에서 — 업로드 직후에는 LLM 을 쓰지 않는다
    emit(ev("tool_end", id=tid, name=tool_name, status="done", summary=f"{sec['title']} {len(strip_tokens(content))}자"))
    emit(ev("section_update", step=sec["step"], title=sec["title"], chars=len(strip_tokens(content)), content=content, covers=sec.get("covers") or [], checks=res["checks"], warnings=res["warnings"], sections=doc["sections"]))
    if action == "plan" and pending.get("fromPlan") and doc.get("plan"):
        remaining_plan(doc)  # 쓰인 항목만큼 done 을 앞으로
    await _call_save(save)
    emit(ev("status", stage="wrapup"))
    explain(doc, emit, sec, res, action)


def explain(doc: Doc, emit: Emit, sec: Dict[str, Any], res: Dict[str, Any], action: str) -> None:
    """작성 뒤 마무리(전문가용 — 확인 카드 대신) — 작성 이유·사용한 근거·붙인 표를 풀어 쓴다(LLM 추가 호출 없음)."""
    review = checks_text(res.get("checks") or {})
    text = explain_section(doc, sec, res, action)
    rest = remaining_plan(doc)
    nxt = rest[0]["title"] if rest else (suggest_next(doc) or {}).get("title")
    if nxt:
        text += f'\n\n다음으로 쓸 섹션: "{nxt}"'
    if review:
        text = f"{review}\n\n{text}"
    emit(ev("text", delta=text))
    ev_ = (doc.get("evidence") or {}).get(sec["step"])
    if isinstance(ev_, dict):
        doc["evidence"] = {**doc["evidence"], sec["step"]: {**ev_, "explain": text}}  # 근거 탭에서 다시 본다(새 dict 대입)
    # 모델 기록에는 한 줄만 — 작업 설명 전문을 자기 답으로 두면 다음 턴에 도구 없이 그 꼴을 흉내 내 '썼습니다'라고 끝낸다(2026-10-30 실측). 전문은 화면·근거 탭에
    done = f"[시스템 기록] write_section 실행으로 '{sec['title']}' 섹션 {'수정' if action == 'revise' else '작성'} 끝({len(sec.get('content') or '')}자). 작업 설명은 시스템이 붙였다." + (f" 다음 추천: {nxt}" if nxt else "")
    push_history(doc, [{"role": "user", "content": f"[바로 작성] {sec['title']} {'수정' if action == 'revise' else '작성'}"}, {"role": "assistant", "content": done}])


def checks_text(c: Dict[str, Any]) -> str:
    """사용자에게 보이는 검토 문장 — 행동이 필요한 것만(없으면 빈 문자열).
    숫자별 대조 결과는 싣지 않는다 — 본문 숫자는 숫자 출처 탭에서 원본 칸과 바로 맞춰 본다."""
    lines: List[str] = []
    if not c.get("citations"):
        lines.append("출처 — 자료에서 근거 문단을 찾지 못해 출처 표기가 없습니다. 관련 자료를 올리거나 내용을 확인해 주세요.")
    if c.get("removedSources"):
        lines.append(f"출처 — 검색 결과에 없는 출처 번호 {c['removedSources']}개를 지웠습니다.")
    if c.get("truncated"):
        lines.append("길이 — 출력 상한에 걸려 끝부분이 잘렸을 수 있습니다.")
    return ("검토\n" + "\n".join(f"{i + 1}. {x}" for i, x in enumerate(lines))) if lines else ""


# ── 추천 칩 ───────────────────────────────────────────────────────────────

def suggestions_for(doc: Doc) -> List[str]:
    if doc.get("pendingApproval") or not normalize_modes(None, doc)["writing"]:
        return []
    chips: List[str] = []
    if not doc.get("documentIds"):
        return ["어떤 자료를 올리면 좋을까?", "작성 순서 세워줘"]
    rest = remaining_plan(doc)
    if rest:
        chips.append(f'계획대로 진행해줘 ({rest[0]["title"]}부터)' if (doc.get("plan") or {}).get("done", 0) == 0 else f'다음 섹션({rest[0]["title"]}) 이어서 써줘')
    nxt = suggest_next(doc)
    if nxt and not rest:
        chips.append(f"{nxt['title']} 써줘")
    last = find_section(doc, doc.get("lastWrittenStep"))
    if last and last.get("content"):
        chips.append(f"{last['title']} 더 간결하게")
    if not written_sections(doc):
        chips.append("올린 자료 핵심만 요약해줘")
    if not rest and not doc.get("plan") and progress(doc)["remaining"]:
        chips.append("작성 순서 세워줘")
    if progress(doc)["done"]:
        chips.append("리포트 전체 흐름 점검해줘")
    return list(dict.fromkeys(chips))[:4]


# ── 진입점 ────────────────────────────────────────────────────────────────

async def run_turn(doc: Doc, body: Dict[str, Any], llm: Any, emit: Emit, save: Optional[Save] = None) -> None:
    """body = {"text"} 또는 {"approval": {...}}. doc 는 제자리에서 고쳐지고, 저장은 save() 콜백(섹션마다 + 턴 끝)."""
    approval = body.get("approval")
    if body.get("import"):
        from app.templates_import.pipeline import run_import

        async def _save() -> None:
            await _call_save(save)

        await run_import(doc, str(body["import"]), llm, emit, _save)
    elif approval:
        await run_approval(doc, approval, llm, emit, save)
    else:
        await run_chat(doc, (body.get("text") or "").strip(), llm, emit, save, body.get("modes"))


__all__ = ["TranscriptBuilder", "clean_chat_text", "humanize_error", "run_turn", "suggestions_for"]
