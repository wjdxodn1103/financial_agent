"""채팅 모델의 도구 — OP `paper/agent/tools.py` 에서 리포트에 필요한 것만 옮겼다.

카드 원칙(OP 와 같다): 쓰기·고치기는 바로 하지 않고 확인 카드(approval 이벤트)를 띄운 뒤 턴을 끝낸다.
사용자가 카드에서 승인하면 loop.run_approval 이 쓴다. 카드는 한 번에 하나.
도구 결과의 지시문은 "[내부 메모]" 로 시작한다(모델이 사용자에게 베끼지 않게 — loop.clean_chat_text 가 한 번 더 지운다).
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.agent.events import Emit, ev
from app.agent.ledger_brief import CALC_TOOL_NAME, CALC_TOOL_SCHEMA, LedgerBook, select_figures
from app.agent.plan import PlanItem, queue_plan_item, remaining_plan
from app.agent.progress import progress, status_text
from app.agent.session import Doc, Section, add_section, find_by_title, find_section, written_sections
from app.agent.template import item_of, match_item, write_order
from app.config import LIVE_CONNECTOR_TOOLS
from app.docs.search_tool import SEARCH_TOOL_NAME, SEARCH_TOOL_SCHEMA, SourceBook, doc_index_lines, run_search
from app.docs.store import doc_label, has_vectors, load_meta
from app.formats.registry import default_blocks, doc_block_spec, doc_catalog, has_blocks, label, section_blocks_of
from app.records.service import scope_matches


@dataclass
class ToolContext:
    doc: Doc
    llm: Any
    emit: Emit
    user_text: str = ""
    book: SourceBook = field(default_factory=SourceBook)
    lb: LedgerBook = field(default_factory=LedgerBook)  # 이 턴에 lookup_figures 로 보인 원장 수치(F번호) — calculate 가 쓴다


def _str(desc: str) -> Dict[str, Any]:
    return {"type": "string", "description": desc}


TOOL_DEFS: List[Dict[str, Any]] = [
    SEARCH_TOOL_SCHEMA,
    CALC_TOOL_SCHEMA,
    {"type": "function", "function": {"name": "list_documents", "description": "올린 자료 목록(문서 번호·제목·종류·날짜·검색 준비 상태)을 본다.", "parameters": {"type": "object", "properties": {}}}},
    {
        "type": "function",
        "function": {
            "name": "lookup_figures",
            "description": "근거 원장(자료의 표에서 코드가 뽑은 수치)에서 지표·기간을 찾는다. 매출·이익·자산 같은 수치 질문에는 search_documents 보다 먼저 쓴다. 결과의 [S번호] 를 답 문장 끝에 단다. [충돌] 은 자료마다 값이 다르다는 뜻이다.",
            "parameters": {"type": "object", "properties": {"query": _str("찾을 지표와 기간(예: 매출액 2024, 영업이익률)")}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_dart",
            "description": "DART 전자공시에서 국내 회사의 재무제표(재무상태표·손익·현금흐름)를 가져와 워크스페이스 자료로 붙인다. 사용자가 가져오자고 했을 때만 부른다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": _str("회사 이름(예: 삼성전자)"),
                    "year": {"type": "integer", "description": "사업연도(예: 2024)"},
                    "report": {"type": "string", "enum": ["annual", "half", "q1", "q3"], "description": "사업보고서(annual)·반기(half)·1분기(q1)·3분기(q3). 기본 annual"},
                    "fs": {"type": "string", "enum": ["CFS", "OFS"], "description": "연결(CFS, 기본)·별도(OFS)"},
                },
                "required": ["company", "year"],
            },
        },
    },
    {"type": "function", "function": {"name": "get_progress", "description": "리포트 섹션 목록([id]·작성 여부)과 진행, 다음 추천을 본다.", "parameters": {"type": "object", "properties": {}}}},
    {
        "type": "function",
        "function": {
            "name": "read_section",
            "description": "이 문서 섹션의 본문을 읽는다(문장 끝 [출처: 자료 이름 #문단]). '이 문서에 ~가 반영됐나'·'이 숫자 근거가 뭐야'처럼 쓴 문장을 짚어야 할 때.",
            "parameters": {
                "type": "object",
                "properties": {"section_id": _str("섹션 id(get_progress 의 [id])"), "query": _str("섹션 id 를 모를 때 본문에서 찾을 말(예: '발표 시각', '22:30')")},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "use_format",
            "description": "이 작업에 문서 양식을 붙인다(목차·섹션 안내가 깔린다). 사용자가 양식을 말했을 때만 — '기업 분석 양식으로 써줘', '반기 운용보고서 양식으로'. 쓸 수 있는 양식은 '## 문서 양식' 목록. 이미 쓴 섹션이 있으면 바꿀 수 없다.",
            "parameters": {"type": "object", "properties": {"format": _str("양식 이름(목록 그대로) 또는 id")}, "required": ["format"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_report_meta",
            "description": "대화에서 정한 리포트 설정을 저장한다(준 항목만 바꾼다).",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": _str("리포트 제목"),
                    "subject": _str("대상 — 기업명·산업명·검토 주제(예: 삼성전자, 2차전지 소재 산업, 출장비 규정)"),
                    "as_of": _str("기준일(예: 2025-06-30, 2Q25)"),
                    "audience": _str("독자(예: 투자위원회, 내부 보고)"),
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_section",
            "description": "섹션 하나를 바로 쓴다(전문가용 — 확인 카드 없이 쓰고, 쓴 뒤 이유·근거를 시스템이 설명한다). 사용자가 쓰자고 했을 때만 — '무엇부터 쓰면 좋을까?' 같은 질문에는 부르지 말고 답한다. 원고에 있는 섹션이면 section_id, 새 섹션이면 title(사용자가 부른 이름 그대로).",
            "parameters": {
                "type": "object",
                "properties": {
                    "section_id": _str("원고 섹션 id(get_progress 의 [id]). 새 섹션이면 생략"),
                    "title": _str("섹션 제목(새 섹션일 때 필수)"),
                    "instruction": _str("사용자가 이 턴에 말한 강조점·구성 요청만 그대로(선택). 사용자가 말하지 않은 분량·문체 지시를 지어 넣지 않는다"),
                    "after": _str("새 섹션을 이 섹션 id 뒤에 넣는다(선택)"),
                    "question": _str("이 작성 요청을 한 문장으로(선택, 대화 기록용)"),
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "revise_section",
            "description": "작성된 섹션을 사용자 요청대로 바로 고친다.",
            "parameters": {"type": "object", "properties": {"section_id": _str("섹션 id"), "instruction": _str("사용자가 말한 수정 요청 그대로")}, "required": ["section_id", "instruction"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_plan",
            "description": "남은 섹션의 작성 순서를 제안한다(저장 없이 후보로만). 사용자가 동의하면 continue_plan 이 확정한다.",
            "parameters": {
                "type": "object",
                "properties": {"items": {"type": "array", "items": {"type": "string"}, "description": "섹션 제목을 작성 순서대로"}, "note": _str("왜 이 순서인지 한 줄(선택)")},
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "continue_plan",
            "description": "제안한 작성 순서에 사용자가 동의하면 확정하고, 순서대로 다음 섹션 하나를 바로 쓴다('다음', '이어서', '계획대로').",
            "parameters": {"type": "object", "properties": {"question": _str("한 문장 질문(선택)")}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_outline",
            "description": "원고 구성을 편집한다: rename(section_id, title) / remove(section_id) / move(section_id, after) / reorder(order=섹션 id 전체 순서) / add(title, part=장 제목, after) — add 는 틀이 있는 문서의 장에 소주제를 더한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["rename", "remove", "move", "reorder", "add"]},
                    "section_id": _str("대상 섹션 id"),
                    "title": _str("새 제목(rename·add)"),
                    "part": _str("장 제목(add)"),
                    "after": _str("이 섹션 뒤로(move·add — 생략 시 move 는 맨 앞, add 는 그 장의 끝)"),
                    "order": {"type": "array", "items": {"type": "string"}, "description": "섹션 id 전체 순서(reorder)"},
                },
                "required": ["op"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_block",
            "description": "고정 양식 리포트에서 양식에 딸린 표·그림을 섹션 뒤에 붙인다(양식 목록 안에서만, 숫자는 코드가 데이터에서 채운다). '○○ 섹션에 ○○ 표/그래프 넣어줘'.",
            "parameters": {"type": "object", "properties": {"block": _str("블록 id 또는 '<표 4>'·'그림 2'·제목"), "section_id": _str("붙일 섹션 id(생략하면 양식의 기본 섹션)")}, "required": ["block"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_block",
            "description": "고정 양식 리포트에서 섹션 뒤의 표·그림을 뺀다. '○○ 그래프 빼줘'.",
            "parameters": {"type": "object", "properties": {"block": _str("블록 id 또는 '<표 4>'·'그림 2'·제목"), "section_id": _str("섹션 id(생략하면 그 블록이 붙은 섹션)")}, "required": ["block"]},
        },
    },
]
if not LIVE_CONNECTOR_TOOLS:
    # 외부 API 직접 가져오기는 끈다 — 데이터는 사내 공용 데이터로 미리 들어온다(config.LIVE_CONNECTOR_TOOLS 로 다시 켠다)
    TOOL_DEFS = [t for t in TOOL_DEFS if t["function"]["name"] != "fetch_dart"]
from app.agent.proposals import PROPOSAL_TOOLS  # noqa: E402 — 대화로 등록(루틴·수집 소스) 확인 카드

TOOL_DEFS += PROPOSAL_TOOLS
TOOL_NAMES: List[str] = [t["function"]["name"] for t in TOOL_DEFS]
_NULL_ID = re.compile(r"^(null|none|undefined|new|)$", re.I)


def _arg(v: Any) -> str:
    if isinstance(v, str):
        return v.strip()
    if v is None:
        return ""
    return json.dumps(v, ensure_ascii=False) if not isinstance(v, (int, float)) else str(v)


def _as_list(v: Any) -> List[str]:
    """모델이 배열을 JSON 문자열로 주는 일(gpt-oss)·쉼표 문자열을 받아 준다."""
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("["):
            try:
                return _as_list(json.loads(s))
            except ValueError:
                pass
        return [x.strip() for x in re.split(r"[\n,]", s) if x.strip()]
    return []


# ── 카드 공통 필드 ──────────────────────────────────────────────────────

def card_fields(doc: Doc, covers: List[str], guide: Optional[str] = None) -> Dict[str, Any]:
    """확인 카드가 그리는 것 — 참고할 자료(전부 기본 선택), 섹션 지침, 2단계 입력칸과 미리 채운 값.
    섹션 지침은 등록한 사내 양식의 안내문(섹션 guide)이 있으면 그것, 없으면 리포트 유형의 항목 설명."""
    item = item_of(covers[0], doc.get("reportType")) if covers else None
    if guide is None and covers:
        guide = next((s.get("guide") for s in doc.get("sections") or [] if (s.get("covers") or [])[:1] == covers[:1] and s.get("guide")), None)
    documents = []
    for did in doc.get("documentIds") or []:
        m = load_meta(did)
        if m:
            c = m.get("card") or {}
            documents.append({"id": did, "label": doc_label(m, did), "docType": c.get("docType") or "", "embedded": has_vectors(did)})
    fields = (item or {}).get("inputs") or []
    saved = doc.get("userInputs") or {}
    title = (item or {}).get("title") or ""
    sec_title = next((s.get("title") or "" for s in doc.get("sections") or [] if covers and (s.get("covers") or [])[:1] == covers[:1]), "")
    notes = [
        {"typeKo": n["typeKo"], "text": n["text"], "author": n.get("author") or "", "quote": n.get("quote") or "", "at": (n.get("at") or "")[:10]}
        for n in doc.get("teamNotes") or []
        if scope_matches(n.get("scope") or "", sec_title or title)
    ][:5]
    out: Dict[str, Any] = {
        "documents": documents,
        "itemDesc": (guide or "").strip() or (item or {}).get("desc") or "",
        "inputFields": fields,
        "inputs": {f["key"]: saved[f["key"]] for f in fields if saved.get(f["key"])},
        "notes": notes or None,
    }
    pending = sum(1 for d in documents if not d["embedded"])
    if pending:
        out["note"] = f"자료 {pending}건은 아직 벡터 색인 중이라 키워드(BM25) 검색으로 찾습니다. 색인이 끝나면 더 정확해집니다."
    return out


# ── 도구 실행 ───────────────────────────────────────────────────────────

async def run_tool(name: str, args: Dict[str, Any], ctx: ToolContext) -> str:
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"알 수 없는 도구: {name}"
    return await handler(args, ctx)


async def _search(args: Dict[str, Any], ctx: ToolContext) -> str:
    return (await asyncio.to_thread(run_search, ctx.book, ctx.doc.get("documentIds") or [], args))["text"]


async def _list_documents(args: Dict[str, Any], ctx: ToolContext) -> str:
    ids = ctx.doc.get("documentIds") or []
    if not ids:
        return "[내부 메모] 올린 자료가 없습니다. 오른쪽 '자료' 패널에서 PDF·DOCX·TXT·MD 파일을 올릴 수 있다고 안내하세요."
    lines = doc_index_lines(ids)
    waiting = sum(1 for d in ids if not has_vectors(d))
    tail = f"\n(벡터 색인 중 {waiting}건 — 그동안은 키워드 검색)" if waiting else ""
    return "\n".join(lines) + tail


async def _lookup_figures(args: Dict[str, Any], ctx: ToolContext) -> str:
    ids = ctx.doc.get("documentIds") or []
    query = _arg(args.get("query"))
    if not ids or not query:
        return "원장에 수치가 없습니다(표가 든 자료가 없거나 질의가 비었습니다). search_documents 로 찾는다."
    lines = await asyncio.to_thread(select_figures, ids, ctx.doc.get("ledgerChoices") or {}, [query], ctx.book, ctx.lb)
    if not lines:
        return f"근거 원장에 '{query}' 와 맞는 수치가 없습니다. search_documents 로 본문을 찾는다."
    return f"근거 원장 {len(lines)}건(표 칸에서 뽑은 값 — 표기 그대로 쓴다)\n[내부 메모] 값을 쓴 문장 끝에 그 줄의 [S번호] 를 단다. 증감률·비율은 calculate 에 F번호로 식을 넣는다. F번호는 사용자에게 말하지 않는다.\n\n" + "\n".join(lines)


async def _calculate(args: Dict[str, Any], ctx: ToolContext) -> str:
    if not ctx.lb.refs:
        return "먼저 lookup_figures 로 계산에 쓸 원장 수치를 찾는다(F번호가 필요하다)."
    return ctx.lb.calculate(args)


async def _fetch_dart(args: Dict[str, Any], ctx: ToolContext) -> str:
    from sqlmodel import Session

    from app.connectors import dart
    from app.connectors.base import ConnectorError
    from app.db import engine
    from app.docs import queue as docs_queue
    from app.services.document_service import attach_document

    workspace_id = ctx.doc.get("workspaceId")
    company = _arg(args.get("company"))
    try:
        year = int(args.get("year") or 0)
    except (TypeError, ValueError):
        year = 0
    report = _arg(args.get("report")) or "annual"
    fs = _arg(args.get("fs")) or "CFS"
    if not workspace_id or not company or not year:
        return "회사 이름과 사업연도가 필요합니다."
    try:
        found = await asyncio.to_thread(dart.search_companies, company, 5)
        if not found:
            return f"DART 에서 '{company}' 회사를 찾지 못했습니다. 정확한 회사 이름을 물어보세요."
        corp = next((c for c in found if c["listed"]), found[0])
        snap = await asyncio.to_thread(dart.fetch_financials, corp["corpCode"], corp["corpName"], year, report, fs)
    except ConnectorError as e:
        return f"[내부 메모] DART 가져오기 실패: {e.message} 사용자에게 그대로 알린다."

    def attach() -> None:
        with Session(engine) as s:
            attach_document(s, workspace_id, snap["id"])

    await asyncio.to_thread(attach)
    docs_queue.schedule_embed(snap["id"])
    ids = list(ctx.doc.get("documentIds") or [])
    if snap["id"] not in ids:
        ctx.doc["documentIds"] = [*ids, snap["id"]]
    others = ", ".join(c["corpName"] for c in found if c["corpCode"] != corp["corpCode"])[:80]
    return f"[내부 메모] '{snap['title']}' 을 DART 에서 가져와 워크스페이스 자료로 붙였다(원장 수치 {snap['figures']}개, 오늘 조회 스냅샷)." + (f" 비슷한 이름의 다른 회사: {others} — 다른 회사였다면 알려 달라고 한다." if others else "")


async def _get_progress(args: Dict[str, Any], ctx: ToolContext) -> str:
    return status_text(ctx.doc)


async def _read_section(args: Dict[str, Any], ctx: ToolContext) -> str:
    """섹션 본문 — 인용 표지([@문서#문단])를 [출처: 자료 이름 · 그 문단 제목] 으로 풀어 어느 문장이 어느 자료에 기대는지 보이게.
    섹션 id·문단 번호는 내부 메모로만(답에 'p1'·섹션 id 가 새지 않게)."""
    from app.docs.citations import TOKEN
    from app.docs.store import paragraphs

    sid, q = _arg(args.get("section_id")), _arg(args.get("query"))
    secs = [s for s in ctx.doc.get("sections") or [] if s.get("content")]
    if sid:
        pick = [s for s in secs if s["step"] == sid]
    elif q:
        words = [w for w in re.split(r"\s+", q) if len(w) >= 2]
        pick = [s for s in secs if any(w in f"{s.get('title', '')} {s.get('content') or ''}" for w in words)][:3]
    else:
        pick = secs[:2]
    if not pick:
        return "그 섹션을 찾지 못했다(아직 비어 있을 수 있다). get_progress 의 [id] 로 다시 부른다."
    names: Dict[str, str] = {}
    heads: Dict[str, Dict[str, str]] = {}

    def src(m: "re.Match[str]") -> str:
        d, c = m.group(1), m.group(2)
        names.setdefault(d, doc_label(load_meta(d) or {}, d))
        if d not in heads:
            heads[d] = {str(p.get("id")): str(p.get("heading") or p.get("sheet") or "") for p in paragraphs(d)}
        h = heads[d].get(c, "")
        return f"[출처: {names[d]}{' · ' + h[:40] if h and h != names[d] else ''}]"

    body = "\n\n".join(f"섹션 「{s['title']}」\n{TOKEN.sub(src, s.get('content') or '')[:2500]}" for s in pick)
    ids = ", ".join(f"「{s['title']}」={s['step']}" for s in pick)
    return body + f"\n[내부 메모] 본문을 사용자에게 다시 옮겨 적지 않는다 — 짚을 문장만 짧게 인용한다. 섹션은 제목으로 말한다(고칠 때 쓸 id: {ids} — 사용자에게 id 를 말하지 않는다)."


async def _set_report_meta(args: Dict[str, Any], ctx: ToolContext) -> str:
    setup = ctx.doc.setdefault("setup", {})
    changed = []
    for key, arg in (("title", "title"), ("subject", "subject"), ("asOf", "as_of"), ("audience", "audience")):
        v = _arg(args.get(arg))
        if v:
            setup[key] = v
            changed.append(f"{key}={v}")
    if not changed:
        return "바꿀 항목이 없습니다."
    ctx.emit(ev("setup_update", setup=dict(setup)))
    return f"[내부 메모] 리포트 설정을 저장했습니다({', '.join(changed)}). 사용자에게 한 문장으로 확인해 주세요."


def _resolve_section(doc: Doc, args: Dict[str, Any]) -> tuple[Optional[Section], str, List[str], str]:
    """→ (기존 섹션|None, 제목, covers, via). via = section(원고 섹션) | template(유형 항목) | new(사용자 정의)."""
    raw_id = _arg(args.get("section_id"))
    title = _arg(args.get("title"))
    sec = find_section(doc, raw_id) if raw_id and not _NULL_ID.match(raw_id) else None
    # 모델이 다른 섹션의 id 를 재사용하는 일이 있다 — 제목이 다르면 그 id 를 믿지 않는다.
    # 단 틀 문서의 아직 안 쓴 소주제 자리는 id 를 믿고 제목을 주장 한 줄로 바꾼다(소제목은 쓰면서 정한다 — 안 그러면 자리 밖 끝에 새 섹션이 생겼다, 2026-10-30 실측)
    if sec is not None and title and title != sec["title"].strip():
        if doc.get("layout") and sec.get("role") == "subsection" and sec.get("status") != "written":
            sec["title"] = title
        else:
            sec = None
    if sec is None and title:
        sec = find_by_title(doc, title)
    if sec is not None:
        return sec, sec["title"], list(sec.get("covers") or []), "section"
    item = match_item(title, doc.get("reportType")) if title else None
    if item:
        same = [s for s in doc.get("sections") or [] if item["id"] in (s.get("covers") or [])]
        target = next((s for s in same if s.get("status") != "written"), None) or (same[0] if same else None)
        if target is not None:
            return target, target["title"], list(target.get("covers") or []), "template"
        return None, item["title"], [item["id"]], "template"
    return None, title, [], "new"


async def _write_section(args: Dict[str, Any], ctx: ToolContext) -> str:
    doc = ctx.doc
    if doc.get("pendingApproval"):
        return "[내부 메모] 이미 확인 카드가 떠 있습니다. 더 말하지 말고 끝내세요."
    sec, title, covers, _via = _resolve_section(doc, args)
    if not title:
        return '새 섹션에는 title 이 필요합니다(예: "실적 분석").'
    instruction = _arg(args.get("instruction")) or None
    rewrite = bool(sec and sec.get("content"))
    q = _arg(args.get("question"))
    if len(q) >= 6 and title in q:
        question = q
    elif rewrite:
        question = f'"{title}" 섹션을 다시 작성할까요? 지금 본문은 카드의 되돌리기로 복구할 수 있습니다.'
    else:
        question = f'"{title}" 섹션을 작성할까요?'
    item: PlanItem = {"title": title, "covers": covers}
    if sec is not None:
        item["sectionId"] = sec["step"]
    if instruction:
        item["instruction"] = instruction
    after = _arg(args.get("after"))
    if after and sec is None:
        item["after"] = after
    # 전문가용 — 확인 카드 없이 바로 쓴다(loop.run_chat 이 이어서 작성하고 '작업 설명'을 보낸다)
    doc["pendingApproval"] = {"action": "plan", "steps": [title], "question": question, "plan": [item], "fromPlan": False, "direct": True}
    return f'[내부 메모] "{title}" 섹션을 바로 씁니다. 더 말하지 말고 끝내세요.'


async def _revise_section(args: Dict[str, Any], ctx: ToolContext) -> str:
    doc = ctx.doc
    sec = find_section(doc, _arg(args.get("section_id")))
    if sec is None:
        return f"없는 섹션 id: {_arg(args.get('section_id'))}. get_progress 의 [id] 를 쓰세요."
    if not sec.get("content"):
        return f"{sec['title']} 섹션은 아직 본문이 없습니다. write_section 을 쓰세요."
    if doc.get("pendingApproval"):
        return "[내부 메모] 이미 확인 카드가 떠 있습니다. 더 말하지 말고 끝내세요."
    instruction = _arg(args.get("instruction"))
    question = f'"{sec["title"]}" 섹션을 고칠까요?'
    doc["pendingApproval"] = {"action": "revise", "steps": [sec["step"]], "question": question, "instruction": instruction, "direct": True}
    return f'[내부 메모] "{sec["title"]}" 섹션을 바로 고칩니다(요청: {instruction or "없음"}). 더 말하지 말고 끝내세요.'


def _plan_item_for(doc: Doc, title: str) -> Optional[PlanItem]:
    sec = find_by_title(doc, title)
    if sec is None:
        item = match_item(title, doc.get("reportType"))
        if item:
            sec = next((s for s in doc.get("sections") or [] if item["id"] in (s.get("covers") or [])), None)
            if sec is None:
                return {"title": item["title"], "covers": [item["id"]]}
    if sec is None:
        return {"title": title, "covers": []}
    return {"title": sec["title"], "covers": list(sec.get("covers") or []), "sectionId": sec["step"]}


def _default_plan(doc: Doc) -> List[PlanItem]:
    left = {e["item"]["id"] for e in progress(doc)["entries"] if not e["covered"]}
    out: List[PlanItem] = []
    for item_id in write_order(doc.get("reportType")):
        if item_id in left:
            it = item_of(item_id, doc.get("reportType"))
            if it:
                pi = _plan_item_for(doc, it["title"])
                if pi:
                    out.append(pi)
    return out


async def _propose_plan(args: Dict[str, Any], ctx: ToolContext) -> str:
    doc = ctx.doc
    written = {s["step"] for s in written_sections(doc)}
    plan = [p for p in (_plan_item_for(doc, t) for t in _as_list(args.get("items"))) if p and p.get("sectionId") not in written]
    if not plan:
        plan = _default_plan(doc)
    if not plan:
        return "[내부 메모] 남은 섹션이 없습니다. 모든 섹션이 쓰였다고 알리세요."
    doc["pendingPlan"] = plan
    ctx.emit(ev("plan_update", items=[p["title"] for p in plan], done=0, proposed=True, note=_arg(args.get("note")) or None))
    return "[내부 메모] 작성 순서 후보를 카드로 보였습니다: " + " → ".join(p["title"] for p in plan) + ". 이 순서의 이유를 한두 문장으로 설명하고, 이대로 시작할지 물어보세요."


async def _continue_plan(args: Dict[str, Any], ctx: ToolContext) -> str:
    doc = ctx.doc
    if doc.get("pendingApproval"):
        return "[내부 메모] 이미 확인 카드가 떠 있습니다. 더 말하지 말고 끝내세요."
    if doc.get("pendingPlan") and not remaining_plan(doc):
        doc["plan"] = {"items": doc.pop("pendingPlan"), "done": 0}
        ctx.emit(ev("plan_update", items=[p["title"] for p in doc["plan"]["items"]], done=0))
    elif not doc.get("plan") or not remaining_plan(doc):
        items = _default_plan(doc)
        if not items:
            return "[내부 메모] 남은 섹션이 없습니다. 모든 섹션이 쓰였다고 알리세요."
        doc["plan"] = {"items": items, "done": 0}
        ctx.emit(ev("plan_update", items=[p["title"] for p in items], done=0))
    rest = queue_plan_item(doc)
    return f'[내부 메모] "{rest[0]["title"]}" 섹션을 바로 씁니다(남은 섹션 {len(rest)}개). 더 말하지 말고 끝내세요.'


async def _update_outline(args: Dict[str, Any], ctx: ToolContext) -> str:
    doc = ctx.doc
    sections: List[Section] = list(doc.get("sections") or [])
    op = _arg(args.get("op"))
    sid = _arg(args.get("section_id"))
    sec = find_section(doc, sid)
    if op == "rename" and sec and _arg(args.get("title")):
        sec["title"] = _arg(args.get("title"))
        msg = f"이름을 '{sec['title']}' 로 바꿨습니다."
    elif op == "remove" and sec:
        doc["sections"] = [s for s in sections if s["step"] != sid]
        (doc.get("evidence") or {}).pop(sid, None)
        msg = f"'{sec['title']}' 섹션을 지웠습니다."
    elif op == "move" and sec:
        rest = [s for s in sections if s["step"] != sid]
        after = _arg(args.get("after"))
        i = next((k for k, s in enumerate(rest) if s["step"] == after), -1)
        rest.insert(i + 1, sec)
        doc["sections"] = rest
        msg = f"'{sec['title']}' 섹션을 옮겼습니다."
    elif op == "reorder":
        order = _as_list(args.get("order"))
        by = {s["step"]: s for s in sections}
        doc["sections"] = [by[x] for x in order if x in by] + [s for s in sections if s["step"] not in order]
        msg = "순서를 바꿨습니다."
    elif op == "add" and doc.get("layout") and _arg(args.get("title")):
        # 틀 문서 — 장(part) 아래 소주제 섹션. 자리 = 지정한 섹션 뒤, 없으면 그 장의 끝(장이 비었으면 앞 장들의 끝)
        chapters = [p for p in doc["layout"].get("parts") or [] if p.get("role") == "chapter"]
        want = _arg(args.get("part")).replace(" ", "")
        part = next((p for p in chapters if want and (want == p["id"] or want in p["title"].replace(" ", ""))), None)
        if part is None:
            return "그런 장이 없습니다. 장: " + ", ".join(p["title"] for p in chapters)
        before = {p["id"] for p in chapters[: chapters.index(part) + 1]}
        after = _arg(args.get("after")) or next((s["step"] for s in reversed(sections) if s.get("part") == part["id"]), "") \
            or next((s["step"] for s in reversed(sections) if s.get("part") in before), "")
        node = add_section(doc, _arg(args.get("title")), [], after=after or None)
        node.update({"part": part["id"], "role": "subsection", "depth": 2, "blocks": []})
        msg = f"'{part['title']}' 장에 '{node['title']}' 소주제를 더했습니다."
    else:
        return "op/인자가 잘못됐습니다. get_progress 의 [id] 를 쓰세요."
    ctx.emit(ev("outline_update", sections=doc["sections"]))
    return f"{msg}\n\n{status_text(doc)}"


# ── 고정 양식의 표·그림(양식에 딸린 도구) ──────────────────────────────

_BLOCK_NO = re.compile(r"(표|그림|table|chart|figure)\s*(\d+)", re.I)


def _find_block(doc: Doc, ref: str) -> Optional[Dict[str, Any]]:
    """'<표 4>'·'그림 2'·블록 id·제목 일부 → 블록 정의."""
    ref = (ref or "").strip()
    spec = doc_block_spec(doc, ref)
    if spec:
        return spec
    m = _BLOCK_NO.search(ref)
    if m:
        kind = "table" if m.group(1).lower() in ("표", "table") else "chart"
        return next((b for b in doc_catalog(doc) if b["kind"] == kind and b.get("no") == int(m.group(2))), None)
    low = ref.lower().replace(" ", "")
    return next((b for b in doc_catalog(doc) if low and low in (b.get("title") or "").replace(" ", "").lower()), None)


def _block_section(doc: Doc, args: Dict[str, Any], spec: Dict[str, Any], *, holding: bool) -> Optional[Section]:
    raw = _arg(args.get("section_id"))
    if raw and not _NULL_ID.match(raw):
        return find_section(doc, raw) or find_by_title(doc, raw)
    secs = doc.get("sections") or []
    if holding:  # 빼기 — 지금 그 블록이 붙은 섹션
        return next((s for s in secs if spec["id"] in section_blocks_of(doc, s)), None)
    home = next((s for s in secs if spec["id"] in default_blocks(doc.get("reportType"), (s.get("covers") or [None])[0])), None)
    return home or find_section(doc, doc.get("lastWrittenStep") or "") or (secs[0] if secs else None)


def _catalog_text(doc: Doc) -> str:
    return ", ".join(f"{label(b)}[{b['id']}]" for b in doc_catalog(doc))


async def _add_block(args: Dict[str, Any], ctx: ToolContext) -> str:
    doc = ctx.doc
    if not has_blocks(doc):
        return "이 리포트는 고정 양식이 아니라 붙일 표·그림 목록이 없습니다."
    spec = _find_block(doc, _arg(args.get("block")))
    if spec is None:
        return f"양식에 없는 표·그림입니다. 이 양식의 목록: {_catalog_text(doc)}"
    sec = _block_section(doc, args, spec, holding=False)
    if sec is None:
        return "붙일 섹션을 찾지 못했습니다. get_progress 의 [id] 로 section_id 를 주세요."
    current = section_blocks_of(doc, sec)
    if spec["id"] in current:
        return f"{label(spec)} 은(는) 이미 '{sec['title']}' 섹션 뒤에 있습니다."
    sec["blocks"] = [*current, spec["id"]]
    ctx.emit(ev("outline_update", sections=doc["sections"]))
    return f"'{sec['title']}' 섹션 뒤에 {label(spec)} 을(를) 붙였습니다(양식 그대로, 숫자는 자료에서 채움). 사용자에게 한 문장으로 알린다."


async def _remove_block(args: Dict[str, Any], ctx: ToolContext) -> str:
    doc = ctx.doc
    if not has_blocks(doc):
        return "이 리포트는 고정 양식이 아니라 뺄 표·그림이 없습니다."
    spec = _find_block(doc, _arg(args.get("block")))
    if spec is None:
        return f"양식에 없는 표·그림입니다. 이 양식의 목록: {_catalog_text(doc)}"
    sec = _block_section(doc, args, spec, holding=True)
    current = section_blocks_of(doc, sec) if sec else []
    if sec is None or spec["id"] not in current:
        return f"{label(spec)} 은(는) 지금 어느 섹션에도 붙어 있지 않습니다."
    sec["blocks"] = [b for b in current if b != spec["id"]]
    ctx.emit(ev("outline_update", sections=doc["sections"]))
    return f"'{sec['title']}' 섹션에서 {label(spec)} 을(를) 뺐습니다. 사용자에게 한 문장으로 알린다."


async def _use_format(args: Dict[str, Any], ctx: ToolContext) -> str:
    from app.agent.session import seed_sections

    doc = ctx.doc
    ref = _arg(args.get("format"))
    formats = doc.get("_formats") or []
    key = re.sub(r"\s+", "", ref).lower()
    hit = next((f for f in formats if f["id"] == ref or re.sub(r"\s+", "", f["title"]).lower() == key), None) or next(
        (f for f in formats if key and (key in re.sub(r"\s+", "", f["title"]).lower() or re.sub(r"\s+", "", f["title"]).lower() in key)), None
    )
    if hit is None:
        return f"그런 양식이 없다. 쓸 수 있는 양식: {', '.join(f['title'] for f in formats) or '없음'}"
    if (doc.get("reportType") or "free") != "free" or written_sections(doc):
        return "이 문서는 이미 양식이 정해졌다 — 양식은 바꾸지 않는다. 다른 양식이 필요하면 새 AI 작업에서 시작하자고 한 문장으로 알린다."
    doc["reportType"] = hit["id"]
    seed_sections(doc)
    doc.pop("plan", None)
    doc.pop("pendingPlan", None)
    ctx.emit(ev("outline_update", sections=doc["sections"]))
    names = ", ".join(s["title"] for s in doc["sections"])
    return f"'{hit['title']}' 양식을 붙였다 — 섹션 {len(doc['sections'])}개: {names}\n[내부 메모] 붙였다고 한 문장으로 알린다. 사용자가 쓸 섹션을 말했으면 이어서 write_section, 아니면 어디부터 쓸지 한 번 묻는다."


async def _proposal(name: str, args: Dict[str, Any], ctx: ToolContext) -> str:
    from app.agent.proposals import run

    return await run(name, args, ctx.doc, ctx.emit)


_HANDLERS: Dict[str, Callable[[Dict[str, Any], ToolContext], Awaitable[str]]] = {
    "propose_routine": lambda a, c: _proposal("propose_routine", a, c),
    "propose_source": lambda a, c: _proposal("propose_source", a, c),
    "propose_event_alert": lambda a, c: _proposal("propose_event_alert", a, c),
    SEARCH_TOOL_NAME: _search,
    "list_documents": _list_documents,
    "lookup_figures": _lookup_figures,
    CALC_TOOL_NAME: _calculate,
    "fetch_dart": _fetch_dart,
    "get_progress": _get_progress,
    "read_section": _read_section,
    "use_format": _use_format,
    "set_report_meta": _set_report_meta,
    "write_section": _write_section,
    "revise_section": _revise_section,
    "propose_plan": _propose_plan,
    "continue_plan": _continue_plan,
    "update_outline": _update_outline,
    "add_block": _add_block,
    "remove_block": _remove_block,
}
