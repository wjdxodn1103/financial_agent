"""AI 채팅 도구 — 자료 찾기(문서 작성 채팅과 같은 도구) + 표 만들기·고치기·양식 저장·드라이브 저장.
문서 양식의 표·차트 양식(F번호 — research/forms.py): build_table·build_chart·extract_table 의 form, 문서 작성 모드의 insert_form.

표는 도구 안에서 다 채운다(fill.fill_table). 행이 끝날 때마다 저장하고 table_update 이벤트로 오른쪽 패널을 갱신한다.
모델에게는 표 요약만 돌려준다 — 표 내용을 글로 되풀이하지 않게.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from sqlmodel import Session

from app.agent.tools import TOOL_DEFS as AGENT_TOOLS, ToolContext, run_tool as run_agent_tool
from app.db import Repo, ResearchTable, User, engine
from app.docs.store import doc_label, load_meta
from app.ids import id36
from app.research import entities
from app.research.fill import fill_table, new_data
from app.research.service import ResearchService, match_template
from app.research.templates import MAX_ROWS, SUBJECT_KINDS, SpecError, normalize_items, normalize_spec

REUSED = ("search_documents", "lookup_figures", "calculate", "list_documents", "fetch_dart")
_COLUMN = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "열 이름(예: 매출액, 영업이익률, 주요 리스크, 질문 문장)"},
        "type": {"type": "string", "enum": ["number", "text", "calc"], "description": "number=자료의 수치, text=자료 근거가 있는 짧은 답, calc=같은 행 숫자 열로 계산"},
        "metric": {"type": "string", "description": "number 열의 지표 이름(없으면 label)"},
        "unit": {"type": "string", "description": "표기 단위(예: 억원, %) — 선택"},
        "formula": {"type": "string", "description": "calc 열 식 — 앞 열 이름으로. ratio(영업이익, 매출액)·growth(새, 옛)·diff(a, b)"},
        "periodOffset": {"type": "integer", "description": "number 열이 기준 기간보다 몇 해 앞인지(전년=-1) — 선택"},
        "instruction": {"type": "string", "description": "이 열을 채울 때 지침 — 선택"},
    },
    "required": ["label"],
}
NEW_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "build_table",
            "description": "여러 기업·문서·기간을 같은 항목으로 비교·정리하는 표를 만든다(칸마다 원문 연결, 오른쪽 패널에 보인다). 양식이 맞으면 template 에 양식 이름이나 id 를 넣는다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "form": {"type": "string", "description": "문서 양식의 표·차트 양식(F번호·이름) — 쓰면 열·머리 묶음·모양은 양식대로(template·columns 는 무시)"},
                    "template": {"type": "string", "description": "쓸 표 양식 이름 또는 id(선택)"},
                    "title": {"type": "string", "description": "표 제목"},
                    "rows": {"type": "array", "items": {"type": "string"}, "description": "행 — 기업 이름·문서 이름·기간(질문 표에서 비우면 범위 안 문서 전부)"},
                    "row_kind": {"type": "string", "enum": list(SUBJECT_KINDS), "description": "양식 없이 만들 때 행 종류(기업 company·문서 document·기간 period·항목 label)"},
                    "columns": {"type": "array", "items": _COLUMN, "description": "양식 없이 만들 때의 열, 또는 질문 표의 질문들"},
                    "period": {"type": "string", "description": "기준 기간(예: 2024, 2025 1분기) — 비우면 행들이 함께 가진 최신 기간"},
                    "basis": {"type": "string", "enum": ["연결", "별도"], "description": "재무제표 기준 — 선택"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_table",
            "description": "지금 보는 표(또는 table id)에 행·열을 더하거나 빼고, 기준 기간을 바꾼다. 새로 생긴 칸만 채운다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "표 id(비우면 지금 보는 표)"},
                    "add_rows": {"type": "array", "items": {"type": "string"}},
                    "remove_rows": {"type": "array", "items": {"type": "string"}},
                    "add_columns": {"type": "array", "items": _COLUMN},
                    "remove_columns": {"type": "array", "items": {"type": "string"}, "description": "뺄 열 이름"},
                    "period": {"type": "string"},
                    "basis": {"type": "string", "enum": ["연결", "별도"]},
                    "title": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_chart",
            "description": "표의 숫자 열로 차트를 만든다(값은 표에 보인 그 숫자, 점마다 원문 연결). 같은 단위의 열만 한 차트에 넣는다(막대+선은 오른쪽 축 하나 더). form 을 쓰면 종류·계열별 막대/선·축·색이 문서 양식의 차트 양식대로.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "표 id(비우면 지금 보는 표)"},
                    "form": {"type": "string", "description": "문서 양식의 표·차트 양식(F번호·이름) — 쓰면 열·머리 묶음·모양은 양식대로(template·columns 는 무시)"},
                    "type": {"type": "string", "enum": ["bar", "line", "area", "pie", "combo", "band"], "description": "bar=막대, line=꺾은선(기간 추이), area=영역, pie=원, combo=막대+선, band=선+평균·표준편차 띠(계산값) — form 을 쓰면 비운다"},
                    "series": {"type": "array", "items": {"type": "string"}, "description": "그릴 열 이름 — 비우면 첫 숫자 열과 같은 단위의 열 전부"},
                    "rows": {"type": "array", "items": {"type": "string"}, "description": "그릴 행 이름 — 비우면 전부"},
                    "horizontal": {"type": "boolean", "description": "가로 막대(행이 많을 때)"},
                    "title": {"type": "string", "description": "차트 제목(비우면 표 제목)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_table",
            "description": "올린 자료 속 표를 그대로 표로 꺼낸다(칸이 원문 칸에 이어진다, 값은 원문 그대로, 오른쪽 결과에 보인다). table 을 비우면 그 자료의 표 목록을 돌려준다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "document": {"type": "string", "description": "자료 이름 일부 또는 자료 목록 번호(D3)"},
                    "table": {"type": "string", "description": "표 번호('표 2'·'2')나 캡션 일부 — 비우면 목록"},
                    "form": {"type": "string", "description": "문서 양식의 표·차트 양식(F번호·이름) — 꺼낸 표를 그 양식의 열·모양으로 옮긴다(차트 양식이면 차트까지)"},
                },
                "required": ["document"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_note",
            "description": "바로 앞 답이나 정리한 내용을 출처 링크째 메모로 남긴다(보관·검색용, 근거 자료 아님). 바로 앞 답을 남길 때는 text 를 비운다 — 그래야 출처 링크가 그대로 남는다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "메모 제목(선택)"},
                    "text": {"type": "string", "description": "새로 정리한 메모 내용일 때만 — 비우면 바로 앞 답(권장). 이번 턴 검색 결과의 [S번호] 출처를 달 수 있다"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_template",
            "description": "표 양식을 저장한다. 지금 보는 표에서 만들거나(기본 — 열만 고정, 행은 매번), keep_rows 면 행까지 고정. 표 없이 열 목록으로도 만든다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "양식 이름"},
                    "scope": {"type": "string", "enum": ["user", "workspace"], "description": "user=나만, workspace=이 워크스페이스 모두(편집자 이상)"},
                    "keep_rows": {"type": "boolean", "description": "행까지 고정할지"},
                    "table": {"type": "string", "description": "표 id(비우면 지금 보는 표)"},
                    "row_kind": {"type": "string", "enum": list(SUBJECT_KINDS)},
                    "columns": {"type": "array", "items": _COLUMN, "description": "표 없이 만들 때 열"},
                    "rows": {"type": "array", "items": {"type": "string"}, "description": "표 없이 만들면서 행도 고정할 때"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_table_to_drive",
            "description": "대화에서 정리한 표·메모를 드라이브에 '정리한 데이터'로 저장한다(멤버가 본다). 사용자가 저장하자고 했을 때만.",
            "parameters": {"type": "object", "properties": {"table": {"type": "string", "description": "표 id(비우면 지금 보는 표)"}, "folder": {"type": "string", "description": "폴더 이름(선택)"}}},
        },
    },
]
# 찾기 도구 — 리서치·문서 작성 둘 다. 사용자가 만든·올린 것을 이름·종류·날짜로 찾아 열어 준다
FIND_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "find_items",
            "description": "워크스페이스에서 사용자가 만든 표·차트·메모, 문서, 데이터 파일, 폴더를 이름·종류·날짜로 찾는다(예: '지난주 만든 Peer 표', '반도체 차트'). 결과마다 별칭(A1·R1·F1·G1)을 준다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "사용자 말 그대로(종류·날짜·내 것/공유 말도 같이 읽는다)"},
                    "kinds": {"type": "array", "items": {"type": "string", "enum": ["asset", "doc", "file", "folder"]}, "description": "찾을 종류 — 비우면 전부"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_asset",
            "description": "find_items 로 찾은 것을 화면에 연다 — 표·차트(A)는 오른쪽 결과에, 데이터 파일(F)은 문서 보기에, 문서(R)는 여는 버튼을 단다.",
            "parameters": {"type": "object", "properties": {"ref": {"type": "string", "description": "find_items 의 별칭(A1·R2·F1)"}}, "required": ["ref"]},
        },
    },
]
# 문서 작성 모드 도구 — 에셋을 이 작업 문서의 섹션 뒤에 넣는다(대화 중인 doc 을 직접 고친다)
WRITING_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "insert_form",
            "description": "문서 양식의 표·차트 양식(F번호)으로 표·차트를 만들어 섹션 뒤에 넣는다. 값은 자료에서만(못 찾은 칸은 빈 칸). 자료 속 같은 내용의 표가 있으면 document(+table)로 옮기고, 아니면 rows(행 = 대상)로 자료를 찾아 채운다. 차트 양식은 table 에 이미 만든 표 id 를 줘도 된다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "form": {"type": "string", "description": "표·차트 양식 F번호나 이름"},
                    "section": {"type": "string", "description": "넣을 섹션 제목"},
                    "rows": {"type": "array", "items": {"type": "string"}, "description": "행(대상 — 지수·기업·기간 등). 정해지지 않았으면 비우고 사용자에게 묻는다"},
                    "document": {"type": "string", "description": "옮길 표가 든 자료(D번호·이름) — 선택"},
                    "table": {"type": "string", "description": "document 가 있으면 그 자료 속 표 번호·캡션, 없으면(차트 양식) 이미 만든 표 id — 선택"},
                    "period": {"type": "string", "description": "기준 기간 — 선택"},
                    "title": {"type": "string", "description": "표·차트 제목(비우면 양식 이름)"},
                },
                "required": ["form", "section"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fill_slots",
            "description": "등록 양식 섹션의 표·차트 자리를 이 문서의 대상(기업)으로 채워 섹션 뒤에 넣는다. 대상은 리포트 설정(set_report_meta 의 subject)을 쓰고, 없으면 subject 에 넣는다.",
            "parameters": {"type": "object", "properties": {"section": {"type": "string", "description": "섹션 제목"}, "subject": {"type": "string", "description": "대상 기업 이름(리포트 설정에 없을 때)"}}, "required": ["section"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_asset",
            "description": "표·차트를 이 문서의 섹션 뒤에 넣는다. 지금 보는 표가 기본, table 에 다른 표 id. section 은 섹션 제목.",
            "parameters": {"type": "object", "properties": {"table": {"type": "string", "description": "표 id(비우면 지금 보는 표)"}, "section": {"type": "string", "description": "넣을 섹션 제목"}}, "required": ["section"]},
        },
    }
]
TOOLS: List[Dict[str, Any]] = [t for t in AGENT_TOOLS if t["function"]["name"] in REUSED] + NEW_TOOLS
TOOL_NAMES: List[str] = [t["function"]["name"] for t in TOOLS]


@dataclass
class ResearchContext:
    doc: Dict[str, Any]
    llm: Any
    emit: Callable[[Dict[str, Any]], None]
    agent: ToolContext


def _arg(v: Any) -> str:
    s = str(v or "").strip()
    return "" if s.lower() in ("null", "none", "undefined") else s


def _user(session: Session, rc: ResearchContext) -> User:
    u = Repo(session).user(rc.doc["ownerId"])
    assert u is not None
    return u


def _view(table_id: str, rc: ResearchContext) -> Dict[str, Any]:
    with Session(engine) as s:
        svc = ResearchService(s)
        return svc.table_view(svc.table_row(table_id, _user(s, rc)), _user(s, rc))


async def _emit_table(table_id: str, rc: ResearchContext) -> None:
    rc.emit({"type": "table_update", "table": await asyncio.to_thread(_view, table_id, rc)})


def _save_data(table_id: str, data: Dict[str, Any], status: str, title: Optional[str] = None) -> None:
    with Session(engine) as s:
        row = s.get(ResearchTable, table_id)
        if row is None:
            return
        row.data = copy.deepcopy(data)
        row.status = status
        if title:
            row.title = title
        Repo(s).save(row)


def _summary(title: str, data: Dict[str, Any]) -> str:
    """모델에게 돌려줄 표 요약 — 값은 보여 주되(질문에 답할 수 있게) 다시 쓰지 말라고 한다."""
    items = [it for it in data.get("items") or [] if not it.get("hidden")]
    cols = data.get("columns") or {}
    head = [(data.get("spec") or {}).get("subject", {}).get("label") or "행", *[f"{it['label']}({cols.get(it['key'], {}).get('unit')})" if cols.get(it["key"], {}).get("unit") else it["label"] for it in items]]
    lines = [" | ".join(head)]
    blanks = 0
    for s, row in zip(data.get("subjects") or [], data.get("cells") or []):
        vals = []
        for it in items:
            c = row.get(it["key"]) or {}
            if c.get("type") == "empty" or not c:
                blanks += 1
                vals.append("—")
            else:
                vals.append(str(c.get("text") or "")[:60])
        lines.append(" | ".join([s["label"], *vals]))
    period = (data.get("period") or {}).get("label")
    return (
        f"표 '{title}' 완료(오른쪽 패널) — 행 {len(data.get('subjects') or [])} × 열 {len(items)}"
        + (f", 기준 {period}" if period else "")
        + (f", 빈 칸 {blanks}" if blanks else "")
        + "\n"
        + "\n".join(lines)[:2500]
        + "\n[내부 메모] 표 내용을 글로 되풀이하지 말고, 무엇을 만들었는지 한두 문장으로 말한다. 빈 칸은 자료에서 찾지 못한 것이라고만 말한다."
    )


def _doc_subjects(rows: List[str], doc_ids: List[str]) -> List[Dict[str, Any]]:
    """문서 행 — 이름으로 범위 안 문서를 찾는다. 비었으면 범위 안 문서 전부(최대 MAX_ROWS)."""
    if not rows:
        return [{"label": doc_label(load_meta(d), d), "docId": d} for d in doc_ids[:MAX_ROWS]]
    out = []
    for r in rows:
        m = re.match(r"^\s*D\s*(\d+)\b\.?\s*", r)
        if m and 0 < int(m.group(1)) <= len(doc_ids):  # 자료 목록 번호(D5)로 가리킨 경우
            d = doc_ids[int(m.group(1)) - 1]
            out.append({"label": doc_label(load_meta(d), d), "docId": d})
            continue
        r = r[m.end():] if m else r
        key = entities.norm(r)
        hit = next((d for d in doc_ids if key and key in entities.norm(doc_label(load_meta(d), d) + " " + ((load_meta(d) or {}).get("fileName") or ""))), None)
        out.append({"label": doc_label(load_meta(hit), hit) if hit else r, **({"docId": hit} if hit else {})})
    return out


async def _fill_and_store(table_id: str, data: Dict[str, Any], rc: ResearchContext, title: str) -> Dict[str, Any]:
    async def progress(d: Dict[str, Any]) -> None:
        await asyncio.to_thread(_save_data, table_id, d, "running")
        await _emit_table(table_id, rc)

    try:
        out = await fill_table(data, rc.doc.get("documentIds") or [], rc.doc.get("ledgerChoices") or {}, rc.llm, progress)
    except Exception:
        await asyncio.to_thread(_save_data, table_id, data, "error")
        await _emit_table(table_id, rc)
        raise
    await asyncio.to_thread(_save_data, table_id, out, "done", title)
    await _emit_table(table_id, rc)
    for chart_id in await asyncio.to_thread(_refresh_charts, table_id):
        await _emit_table(chart_id, rc)
    rc.doc["currentTableId"] = table_id
    if table_id not in (rc.doc.get("tableIds") or []):
        rc.doc["tableIds"] = [*(rc.doc.get("tableIds") or []), table_id]
    rc.doc["_current"] = {"id": table_id, "title": title, "data": out}
    return out


def _title_entity(title: str, doc_ids: List[str]) -> str:
    """표 제목에 든 기업 이름 — 자료 카드의 회사명 가운데 제목에 그대로 든 가장 긴 것(없으면 빈 문자열)."""
    t = entities.norm(title)
    names = {str(((load_meta(d) or {}).get("card") or {}).get("company") or "").strip() for d in doc_ids}
    hits = [n for n in names if len(entities.norm(n)) >= 2 and entities.norm(n) in t]
    return max(hits, key=len) if hits else ""


async def _build_table(args: Dict[str, Any], rc: ResearchContext) -> str:
    title = _arg(args.get("title"))
    rows = [str(x).strip() for x in args.get("rows") or [] if str(x).strip()]
    if _arg(args.get("form")):
        asset, why = _form_of(rc, _arg(args.get("form")))
        if asset is None:
            return why
        _id, msg = await _use_form(asset, rc, rows=_list_arg(args.get("rows")), document="", table_ref="", period=_arg(args.get("period")), title=title)
        return msg
    columns = args.get("columns") or []
    tpl = match_template(rc.doc.get("_templates") or [], _arg(args.get("template")))
    try:
        if tpl:
            spec = copy.deepcopy(tpl["spec"])
            items = normalize_items(columns) if spec.get("itemsOpen") else spec.get("items") or []
            if not items:
                return "이 양식은 열(질문)을 정해야 한다 — columns 에 넣어 다시 부른다."
        else:
            kind = args.get("row_kind") if args.get("row_kind") in SUBJECT_KINDS else "company"
            spec = normalize_spec({"name": title or "표", "subject": {"kind": kind}, "items": columns})
            items = spec["items"]
    except SpecError as e:
        return f"표를 만들지 못함: {e}"
    kind = spec["subject"]["kind"]
    doc_ids = rc.doc.get("documentIds") or []
    if kind == "document":
        subjects = _doc_subjects(rows or [r["label"] for r in spec.get("rows") or []], doc_ids)
    else:
        subjects = [{"label": r} for r in rows] or [dict(r) for r in spec.get("rows") or []]
    if not subjects:
        return "행(기업·문서·기간)을 rows 에 넣어 다시 부른다."
    title = title or spec.get("name") or "표"
    inputs: Dict[str, Any] = {"period": _arg(args.get("period")), "basis": _arg(args.get("basis"))}
    if kind == "period":  # 기간 표('에스비비테크 연도별 실적') — 제목의 기업을 대상으로(행마다 그 기업·그 기간을 코드가 원장에서 찾는다)
        ent = _title_entity(title, doc_ids)
        if ent:
            inputs["entity"] = ent
    table_id, out = await _create_and_fill(spec, subjects, inputs, tpl["id"] if tpl else None, items, title, rc)
    note = ""
    if spec.get("chart"):  # 차트 양식 — 채운 표로 차트도
        chart = await _chart_from_spec(table_id, spec, title, rc)
        note = f"\n차트 '{chart['title']}' 도 만들었다(오른쪽 결과)." if chart else ""
    return _summary(title, out) + note


async def _create_and_fill(spec: Dict[str, Any], subjects: List[Dict[str, Any]], inputs: Dict[str, Any], template_id: Optional[str], items: List[Dict[str, Any]], title: str, rc: ResearchContext, form: Optional[Dict[str, Any]] = None) -> tuple:
    data = new_data(spec, subjects, inputs, template_id, items)
    if form:
        data["form"] = form
    table_id = id36("rt", 4)

    def create() -> None:
        with Session(engine) as s:
            Repo(s).save(ResearchTable(id=table_id, workspace_id=rc.doc["workspaceId"], chat_id=rc.doc["id"], created_by=rc.doc["ownerId"], title=title, status="running", data=data))

    await asyncio.to_thread(create)
    await _emit_table(table_id, rc)
    return table_id, await _fill_and_store(table_id, data, rc, title)


async def _chart_from_spec(table_id: str, spec: Dict[str, Any], title: str, rc: ResearchContext) -> Optional[Dict[str, Any]]:
    """차트 양식의 차트 — 같은 이름의 열을 계열로. 그릴 숫자가 없으면 None."""
    from fastapi import HTTPException

    ch = spec.get("chart") or {}

    def make() -> Dict[str, Any]:
        with Session(engine) as s:
            row = ResearchService(s).make_chart(table_id, _user(s, rc), {"type": ch.get("type"), "series": ch.get("seriesLabels") or [], "horizontal": ch.get("horizontal"), "title": title}, chat_id=rc.doc["id"])
            return {"id": row.id, "title": row.title}

    try:
        made = await asyncio.to_thread(make)
    except HTTPException:
        return None
    await _emit_table(made["id"], rc)
    rc.doc["currentTableId"] = made["id"]
    rc.doc["tableIds"] = [*(rc.doc.get("tableIds") or []), made["id"]]
    return made


def _refresh_charts(table_id: str) -> List[str]:
    """원 표를 다시 채웠으면 딸린 차트도 다시 — 다시 만든 차트 id."""
    from app.research.chart import refresh_dependents

    with Session(engine) as s:
        row = s.get(ResearchTable, table_id)
        return refresh_dependents(s, row) if row is not None else []


def _current(rc: ResearchContext, ref: str) -> Optional[ResearchTable]:
    tid = ref or rc.doc.get("currentTableId") or ""
    if not tid:
        return None
    with Session(engine) as s:
        try:
            row = ResearchService(s).table_row(tid, _user(s, rc))
        except Exception:  # noqa: BLE001 — 없는 표·남의 표
            return None
        s.expunge(row)
        return row


async def _update_table(args: Dict[str, Any], rc: ResearchContext) -> str:
    row = await asyncio.to_thread(_current, rc, _arg(args.get("table")))
    if row is not None and row.kind == "chart":  # 차트를 보며 고치라면 원 표를 고친다(차트는 따라 바뀐다)
        row = await asyncio.to_thread(_current, rc, ((row.data or {}).get("chart") or {}).get("source") or "")
    if row is not None and row.kind == "note":
        return "메모는 표가 아니다 — 표를 고치려면 표를 열거나 build_table 로 만든다."
    if row is None:
        return "고칠 표가 없다 — 먼저 build_table 로 만든다."
    if row.created_by != rc.doc["ownerId"]:
        return "다른 사람이 만든 표는 고칠 수 없다 — build_table 로 새로 만든다."
    data = copy.deepcopy(row.data or {})
    cells: List[Dict[str, Any]] = list(data.get("cells") or [])
    subjects: List[Dict[str, Any]] = list(data.get("subjects") or [])
    items: List[Dict[str, Any]] = list(data.get("items") or [])
    drop_rows = {entities.norm(x) for x in args.get("remove_rows") or []}
    keep = [i for i, s in enumerate(subjects) if entities.norm(s["label"]) not in drop_rows]
    subjects, cells = [subjects[i] for i in keep], [cells[i] if i < len(cells) else {} for i in keep]
    drop_cols = {entities.norm(x) for x in args.get("remove_columns") or []}
    items = [it for it in items if entities.norm(it["label"]) not in drop_cols]
    try:
        if args.get("add_columns"):
            merged = normalize_items([*items, *args["add_columns"]])
            items = merged
    except SpecError as e:
        return f"열을 더하지 못함: {e}"
    kind = ((data.get("spec") or {}).get("subject") or {}).get("kind") or "company"
    new_rows = [str(x).strip() for x in args.get("add_rows") or [] if str(x).strip()]
    if new_rows:
        subjects += _doc_subjects(new_rows, rc.doc.get("documentIds") or []) if kind == "document" else [{"label": r} for r in new_rows]
    inputs = dict(data.get("inputs") or {})
    changed = False
    for k in ("period", "basis"):
        v = _arg(args.get(k))
        if v and v != inputs.get(k):
            inputs[k], changed = v, True
    keys = {it["key"] for it in items}
    cells = [{} for _ in subjects] if changed else [{k: v for k, v in (c or {}).items() if k in keys} for c in cells] + [{} for _ in range(len(subjects) - len(cells))]
    data.update({"subjects": subjects[:MAX_ROWS], "items": items, "inputs": inputs, "cells": cells[:MAX_ROWS]})
    title = _arg(args.get("title")) or row.title
    out = await _fill_and_store(row.id, data, rc, title)
    return _summary(title, out)


async def _save_template(args: Dict[str, Any], rc: ResearchContext) -> str:
    from fastapi import HTTPException

    name = _arg(args.get("name"))
    scope = "workspace" if args.get("scope") == "workspace" else "user"
    body: Dict[str, Any] = {"name": name, "scope": scope}
    if args.get("columns"):
        body["spec"] = {"name": name, "subject": {"kind": args.get("row_kind") if args.get("row_kind") in SUBJECT_KINDS else "company"}, "items": args["columns"], "rows": [{"label": r} for r in args.get("rows") or []] or None}
    else:
        row = await asyncio.to_thread(_current, rc, _arg(args.get("table")))
        if row is None:
            return "양식으로 만들 표가 없다 — 열 목록(columns)으로 만들거나 먼저 표를 만든다."
        if row.kind in ("chart", "note"):
            return "차트·메모는 표 양식으로 저장하지 않는다 — 원 표를 보고 다시 부른다."
        body.update({"fromTableId": row.id, "keepRows": str(args.get("keep_rows")).strip().lower() in ("true", "1", "yes")})

    def save() -> Dict[str, Any]:
        with Session(engine) as s:
            return ResearchService(s).create_template(rc.doc["workspaceId"], _user(s, rc), body)

    try:
        t = await asyncio.to_thread(save)
    except HTTPException as e:
        return f"양식을 저장하지 못함: {e.detail}"
    rc.doc["_templates"] = [*(rc.doc.get("_templates") or []), t]
    rc.emit({"type": "template_saved", "template": t})
    spec = t["spec"]
    rows = "행 고정" if spec.get("rows") else "행은 매번 정함"
    return f"양식 '{t['name']}' 저장({'워크스페이스' if scope == 'workspace' else '나만'}, {rows}, 열 {len([i for i in spec['items'] if not i.get('hidden')])}개)\n[내부 메모] 저장했다고 한 문장으로 알린다."


async def _save_table_to_drive(args: Dict[str, Any], rc: ResearchContext) -> str:
    row = await asyncio.to_thread(_current, rc, _arg(args.get("table")))
    if row is None:
        return "저장할 표가 없다."

    def save() -> str:
        with Session(engine) as s:
            _view_, where = ResearchService(s).save_to_drive(row.id, _user(s, rc), _arg(args.get("folder")))
            return where

    try:
        where = await asyncio.to_thread(save)
    except Exception as e:  # noqa: BLE001
        return f"드라이브에 저장하지 못함: {getattr(e, 'detail', e)}"
    await _emit_table(row.id, rc)
    return f"'{row.title}' 를 {where}에 저장\n[내부 메모] 저장했다고 한 문장으로 알린다."


async def _build_chart(args: Dict[str, Any], rc: ResearchContext) -> str:
    from fastapi import HTTPException

    if _arg(args.get("form")):
        asset, why = _form_of(rc, _arg(args.get("form")), kind="chart")
        if asset is None:
            return why
        _id, msg = await _form_chart(asset, _arg(args.get("table")), rc, _arg(args.get("title")))
        return msg
    row = await asyncio.to_thread(_current, rc, _arg(args.get("table")))
    if row is not None and row.kind == "chart":
        row = await asyncio.to_thread(_current, rc, ((row.data or {}).get("chart") or {}).get("source") or "")
    if row is None:
        return "차트로 그릴 표가 없다 — 먼저 build_table 로 표를 만든다."
    body = {"type": _arg(args.get("type")) or "bar", "series": args.get("series") or [], "rows": args.get("rows") or [], "horizontal": str(args.get("horizontal")).strip().lower() in ("true", "1", "yes"), "title": _arg(args.get("title"))}

    def make() -> Dict[str, Any]:
        with Session(engine) as s:
            ch = ResearchService(s).make_chart(row.id, _user(s, rc), body, chat_id=rc.doc["id"])
            return {"id": ch.id, "title": ch.title, "data": ch.data}

    try:
        ch = await asyncio.to_thread(make)
    except HTTPException as e:
        return f"차트를 만들지 못함: {e.detail}"
    await _emit_table(ch["id"], rc)
    rc.doc["currentTableId"] = ch["id"]
    rc.doc["tableIds"] = [*(rc.doc.get("tableIds") or []), ch["id"]]
    data = ch["data"]
    kind = "꺾은선" if data["chart"]["type"] == "line" else "막대"
    names = ", ".join(s["name"] for s in data["series"])
    note = f" — 단위가 달라 뺀 열: {', '.join(data['dropped'])}" if data.get("dropped") else ""
    return f"{kind} 차트 '{ch['title']}' 완료(오른쪽 결과) — 계열 {names}, 범주 {len(data['categories'])}개{note}\n[내부 메모] 만들었다고 한 문장으로 알린다. 뺀 열이 있으면 따로 차트를 만들 수 있다고만 덧붙인다."


async def _insert_asset(args: Dict[str, Any], rc: ResearchContext) -> str:
    from app.agent.session import find_by_title, find_section, log_section
    from app.research.block import table_entry

    row = await asyncio.to_thread(_current, rc, _arg(args.get("table")))
    if row is None:
        return "넣을 표가 없다 — 먼저 표를 만들거나 찾는다."
    if row.status != "done":
        return "표를 아직 만드는 중이다."
    ref = _arg(args.get("section"))
    sec = find_section(rc.doc, ref) or find_by_title(rc.doc, ref) or next((s for s in rc.doc.get("sections") or [] if ref and ref in s.get("title", "")), None)
    if sec is None:
        names = ", ".join(s["title"] for s in rc.doc.get("sections") or []) or "없음"
        return f"'{ref}' 섹션이 없다. 지금 섹션: {names}"
    if row.kind == "note":
        from app.services.report_service import note_into_section

        note_into_section(rc.doc, sec, row)
        rc.emit({"type": "outline_update", "sections": rc.doc.get("sections") or []})
        return f"메모 '{row.title}' 를 '{sec['title']}' 섹션 끝에 넣음(출처는 원문 문단 인용으로)\n[내부 메모] 넣었다고 한 문장으로 알린다."
    entry = await asyncio.to_thread(table_entry, row)
    sec["tables"] = [*(sec.get("tables") or []), entry]
    log_section(rc.doc, sec["step"], f"{'차트' if row.kind == 'chart' else '표'} 넣기: {row.title}")
    rc.emit({"type": "outline_update", "sections": rc.doc.get("sections") or []})
    return f"'{row.title}' 를 '{sec['title']}' 섹션 뒤에 넣음\n[내부 메모] 넣었다고 한 문장으로 알린다."


def _attach(rc: ResearchContext, row_id: str, title: str, data: Dict[str, Any]) -> None:
    """이 작업의 에셋 목록에 두고 '지금 보는 것'으로."""
    if row_id not in (rc.doc.get("tableIds") or []):
        rc.doc["tableIds"] = [*(rc.doc.get("tableIds") or []), row_id]
    rc.doc["currentTableId"] = row_id
    rc.doc["_current"] = {"id": row_id, "title": title, "data": data}


def _pick_doc(rc: ResearchContext, ref: str) -> Optional[str]:
    """'D3'·자료 이름 일부 → 이 작업 범위의 자료 id."""
    ids = rc.doc.get("documentIds") or []
    m = re.match(r"^\s*D\s*(\d+)\b", ref or "")
    if m and 0 < int(m.group(1)) <= len(ids):
        return ids[int(m.group(1)) - 1]
    key = entities.norm(re.sub(r"^\s*D\s*\d+\.?\s*", "", ref or ""))
    return next((d for d in ids if key and key in entities.norm(doc_label(load_meta(d), d) + " " + ((load_meta(d) or {}).get("fileName") or ""))), None)


async def _extract_table(args: Dict[str, Any], rc: ResearchContext) -> str:
    from app.research.doc_tables import create_from_doc, table_list

    if _arg(args.get("form")):
        asset, why = _form_of(rc, _arg(args.get("form")))
        if asset is None:
            return why
        _id, msg = await _use_form(asset, rc, rows=[], document=_arg(args.get("document")), table_ref=_arg(args.get("table")), period="", title="")
        return msg
    doc_id = _pick_doc(rc, _arg(args.get("document")))
    if doc_id is None:
        return "그 자료를 이 작업의 데이터에서 찾지 못했다 — 자료 목록 번호(D번호)나 이름으로 다시."
    tables = await asyncio.to_thread(table_list, doc_id)
    if not tables:
        return "이 자료에는 칸 구조 표가 없다."
    ref = _arg(args.get("table"))
    pick = None
    if ref:
        # 캡션 일부가 먼저, 아니면 표 번호('표 2'·'2')
        key = entities.norm(ref)
        pick = next((t for t in tables if key and key in entities.norm(t["caption"])), None)
        m = re.search(r"\d+", ref)
        if pick is None and m:
            pick = next((t for t in tables if t["no"] == int(m.group(0))), None)
    if pick is None:

        def line(t: Dict[str, Any]) -> str:
            page = f" (p.{t['page']})" if t["page"] else ""
            return f"표 {t['no']}{page} {t['caption'] or '(제목 없음)'} — {t['rows']}행, 머리: {' | '.join(t['header'][:6])}"

        return "이 자료의 표:\n" + "\n".join(line(t) for t in tables[:15]) + "\n[내부 메모] 어느 표인지 분명하면 table 에 번호를 넣어 다시 부르고, 아니면 사용자에게 묻는다."

    def make() -> Dict[str, Any]:
        with Session(engine) as s:
            row = create_from_doc(s, rc.doc["workspaceId"], _user(s, rc), doc_id, pick["chunk"], chat_id=rc.doc["id"])
            return {"id": row.id, "title": row.title, "data": row.data}

    made = await asyncio.to_thread(make)
    _attach(rc, made["id"], made["title"], made["data"])
    await _emit_table(made["id"], rc)
    return _summary(made["title"], made["data"]).replace("완료(오른쪽 패널)", "꺼냄(원문 칸 그대로, 오른쪽 결과)")


def _overlap(a: str, b: str) -> float:
    """a 의 낱말 중 b(링크 글 뺀)에 있는 비율."""
    from app.research.notes import plain

    wa = set(re.findall(r"[가-힣A-Za-z0-9.,%]+", a))
    wb = set(re.findall(r"[가-힣A-Za-z0-9.,%]+", plain(b)))
    return len(wa & wb) / len(wa) if wa else 0.0


async def _save_note(args: Dict[str, Any], rc: ResearchContext) -> str:
    from app.agent.loop import clean_chat_text
    from app.research.notes import note_data, note_title

    text = _arg(args.get("text"))
    msgs = rc.doc.get("transcript") or []
    question = rc.agent.user_text or ""
    last = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].get("role") == "assistant" and (msgs[i].get("text") or "").strip()), None)
    prev = msgs[last]["text"] if last is not None else ""
    if text and prev and _overlap(text, prev) >= 0.6:
        text = ""  # 앞 답을 옮겨 적은 것 — 출처 링크가 있는 원래 답을 쓴다
    if text:
        text = clean_chat_text(text, rc.agent.book)
    else:
        if last is None:
            return "메모로 남길 앞 답이 없다 — text 에 내용을 넣어 다시 부른다."
        text = prev
        question = next((m.get("text") or "" for m in reversed(msgs[:last]) if m.get("role") == "user"), "")
    title = _arg(args.get("title")) or note_title(text, question)
    data = note_data(text, question)

    def make() -> str:
        with Session(engine) as s:
            row = Repo(s).save(ResearchTable(id=id36("rt", 4), workspace_id=rc.doc["workspaceId"], chat_id=rc.doc["id"], created_by=rc.doc["ownerId"], title=title[:80], status="done", kind="note", data=data))
            return row.id

    nid = await asyncio.to_thread(make)
    _attach(rc, nid, title, data)
    await _emit_table(nid, rc)
    return f"메모 '{title}' 저장(출처 {len(data['cites'])}개, 오른쪽 결과)\n[내부 메모] 저장했다고 한 문장으로 알린다."


_KIND_KO = {"asset": "표·차트", "doc": "문서", "file": "데이터 파일", "folder": "폴더"}
_ALIAS = {"asset": "A", "doc": "R", "file": "F", "folder": "G"}


async def _find_items(args: Dict[str, Any], rc: ResearchContext) -> str:
    from app.db import Workspace
    from app.drive import name_hits
    from app.search import asset_hits, doc_hits

    query = _arg(args.get("query"))
    raw = args.get("kinds") or []
    kinds = {k for k in (raw if isinstance(raw, list) else [raw]) if k in _ALIAS} or set(_ALIAS)

    def find() -> List[Dict[str, Any]]:
        from app.auth import display_name

        with Session(engine) as s:
            user = _user(s, rc)
            ws = s.get(Workspace, rc.doc["workspaceId"])
            names = {u.id: display_name(u) for u in Repo(s).users()}
            out: List[Dict[str, Any]] = []
            if "asset" in kinds:
                out += asset_hits(s, rc.doc["workspaceId"], user, query, limit=5)
            terms = [t for t in query.lower().split() if t]
            if "doc" in kinds and terms:
                out += [d for d in doc_hits(s, rc.doc["workspaceId"], user, terms, names) if d.get("reportId") != rc.doc.get("id")][:3]
            if ("file" in kinds or "folder" in kinds) and ws is not None and terms:
                named = name_hits(s, ws, user, query, folder_max=2, data_max=3)
                out += [{"kind": "file", "docId": d["id"], "title": d["label"], "sub": d["path"]} for d in named["data"]] if "file" in kinds else []
                out += [{"kind": "folder", "id": f["id"], "title": f["name"], "sub": f["path"]} for f in named["folders"]] if "folder" in kinds else []
            return out[:8]

    hits = await asyncio.to_thread(find)
    if not hits:
        return f"'{query}' 로 찾은 것이 없다.\n[내부 메모] 찾지 못했다고 한 문장으로 말하고, 다른 이름·기간을 물어본다."
    found: Dict[str, Dict[str, str]] = {}
    counts: Dict[str, int] = {}
    lines = []
    for h in hits:
        counts[h["kind"]] = counts.get(h["kind"], 0) + 1
        alias = f"{_ALIAS[h['kind']]}{counts[h['kind']]}"
        found[alias] = {"kind": h["kind"], "id": h.get("id") or h.get("reportId") or h.get("docId") or "", "title": h["title"]}
        lines.append(f"{alias}. [{_KIND_KO[h['kind']]}] {h['title']}" + (f" — {h['sub']}" if h.get("sub") else "") + (f" ({str(h['at'])[:10]})" if h.get("at") else ""))
    rc.doc["found"] = found
    return "\n".join(lines) + "\n[내부 메모] 찾은 것을 제목으로 짧게 알려 준다(별칭·id 는 말하지 않는다). 하나로 정해지면 open_asset 으로 바로 연다. 여럿이면 어느 것인지 묻는다."


async def _open_asset(args: Dict[str, Any], rc: ResearchContext) -> str:
    ref = _arg(args.get("ref")).upper().strip(".")
    it = (rc.doc.get("found") or {}).get(ref)
    if it is None:
        return "그런 별칭이 없다 — 먼저 find_items 로 찾는다."
    if it["kind"] == "asset":
        row = await asyncio.to_thread(_current, rc, it["id"])
        if row is None:
            return "이제 볼 수 없는 표다(지웠거나 드라이브 저장을 껐다)."
        if row.id not in (rc.doc.get("tableIds") or []):
            rc.doc["tableIds"] = [*(rc.doc.get("tableIds") or []), row.id]
        rc.doc["currentTableId"] = row.id
        rc.doc["_current"] = {"id": row.id, "title": row.title, "data": row.data}
        await _emit_table(row.id, rc)
        return f"'{row.title}' 를 오른쪽 결과에 열었다.\n[내부 메모] 열었다고 한 문장으로 알린다. 이제 '이 표'는 이것을 가리킨다."
    if it["kind"] in ("file", "doc"):
        rc.emit({"type": "item_link", "item": {"kind": it["kind"], "id": it["id"], "title": it["title"]}})
        where = "문서 보기에 열었다" if it["kind"] == "file" else "여는 버튼을 달았다"
        return f"'{it['title']}' — {where}.\n[내부 메모] 한 문장으로 알린다."
    return f"'{it['title']}' 는 폴더다 — 드라이브에서 연다고 알려 준다."


async def _fill_slots(args: Dict[str, Any], rc: ResearchContext) -> str:
    """등록 양식의 자리 — 표 양식으로 표를 채우고(차트 양식이면 차트까지) 섹션 뒤에 넣는다. 기간 표는 대상 기업을 entity 로(행마다 그 기업·그 기간)."""
    from app.agent.session import find_by_title, find_section, log_section
    from app.research.block import table_entry

    ref = _arg(args.get("section"))
    sec = find_section(rc.doc, ref) or find_by_title(rc.doc, ref) or next((s for s in rc.doc.get("sections") or [] if ref and ref in s.get("title", "")), None)
    if sec is None:
        return f"'{ref}' 섹션이 없다. 지금 섹션: {', '.join(s['title'] for s in rc.doc.get('sections') or []) or '없음'}"
    slots = [x for x in sec.get("slots") or [] if x.get("templateId")]
    if not slots:
        return f"'{sec['title']}' 섹션에는 채울 표·차트 자리가 없다."
    subject = _arg((rc.doc.get("setup") or {}).get("subject")) or _arg(args.get("subject"))
    if not subject:
        return "[내부 메모] 대상(기업)을 모른다 — 사용자에게 어느 기업인지 한 문장으로 묻는다."
    done: List[str] = []
    for slot in slots:
        tpl = match_template(rc.doc.get("_templates") or [], slot["templateId"])
        if tpl is None:
            done.append(f"'{slot.get('title')}' — 양식이 지워졌거나 볼 수 없음")
            continue
        spec = copy.deepcopy(tpl["spec"])
        kind = spec["subject"]["kind"]
        items = spec.get("items") or []
        if spec.get("rows"):
            subjects = [dict(r) for r in spec["rows"]]
        elif kind == "period":
            subjects = [{"label": r} for r in slot.get("rows") or []]  # 샘플의 기간 — 행마다 (대상 기업, 그 기간)
        else:
            subjects = [{"label": subject}]
        if not subjects:
            done.append(f"'{slot.get('title')}' — 행(기간)을 정하지 못함")
            continue
        title = slot.get("title") or spec.get("name") or "표"
        table_id, _out = await _create_and_fill(spec, subjects, {"entity": subject} if kind == "period" else {}, tpl["id"], items, f"{subject} {title}" if kind == "period" else title, rc)
        asset_id = table_id
        if slot.get("kind") == "chart" and spec.get("chart"):
            chart = await _chart_from_spec(table_id, spec, f"{subject} {title}" if kind == "period" else title, rc)
            asset_id = chart["id"] if chart else table_id
        row = await asyncio.to_thread(_current, rc, asset_id)
        if row is None:
            continue
        sec["tables"] = [*(sec.get("tables") or []), await asyncio.to_thread(table_entry, row)]
        log_section(rc.doc, sec["step"], f"양식 자리 채우기: {row.title}")
        done.append(f"'{row.title}' 넣음")
    rc.emit({"type": "outline_update", "sections": rc.doc.get("sections") or []})
    return f"'{sec['title']}' 섹션 자리: " + "; ".join(done) + "\n[내부 메모] 넣은 것을 한 문장으로 알린다. 빈 칸은 자료에서 찾지 못한 것이라고만 말한다."


async def _insert_form(args: Dict[str, Any], rc: ResearchContext) -> str:
    """문서 양식의 표·차트 양식 → 표·차트 → 섹션 뒤에."""
    from app.agent.session import find_by_title, find_section, log_section
    from app.research.block import table_entry

    asset, why = _form_of(rc, _arg(args.get("form")))
    if asset is None:
        return why
    ref = _arg(args.get("section"))
    sec = find_section(rc.doc, ref) or find_by_title(rc.doc, ref) or next((s for s in rc.doc.get("sections") or [] if ref and ref in s.get("title", "")), None)
    if sec is None:
        return f"'{ref}' 섹션이 없다. 지금 섹션: {', '.join(s['title'] for s in rc.doc.get('sections') or []) or '없음'}"
    rows = _list_arg(args.get("rows"))
    document = _arg(args.get("document"))
    table = _arg(args.get("table"))
    if asset["kind"] == "chart" and table and not document and not rows:
        made, msg = await _form_chart(asset, table, rc, _arg(args.get("title")))
    else:
        made, msg = await _use_form(asset, rc, rows=rows, document=document, table_ref=table, period=_arg(args.get("period")), title=_arg(args.get("title")))
    if made is None:
        return msg
    row = await asyncio.to_thread(_current, rc, made)
    if row is None or row.status != "done":
        return msg
    sec["tables"] = [*(sec.get("tables") or []), await asyncio.to_thread(table_entry, row)]
    log_section(rc.doc, sec["step"], f"양식 {'차트' if row.kind == 'chart' else '표'} 넣기: {row.title}")
    rc.emit({"type": "outline_update", "sections": rc.doc.get("sections") or []})
    return f"{msg}\n→ '{sec['title']}' 섹션 뒤에 넣음\n[내부 메모] 넣었다고 한두 문장으로 알린다. 빈 칸은 자료에서 찾지 못한 것이라고만 말한다."


# ── 문서 양식의 표·차트 양식(research/forms.py) ─────────────────────────────

FORM_ROWS = 60  # 자료 속 표를 옮길 때 행 상한(채우지 않으니 채우는 표의 MAX_ROWS 보다 길게 — 기간 차트용)


def _list_arg(v: Any) -> List[str]:
    """행 목록 — 모델이 배열을 글로 보내는 일이 있다('["기술", "금융"]'·'기술, 금융')."""
    if isinstance(v, str):
        t = v.strip()
        if t.startswith("["):
            try:
                v = json.loads(t)
            except ValueError:
                v = t.strip("[]").split(",")
        else:
            v = t.split(",") if t else []
    return [str(x).strip().strip("'\"") for x in v or [] if str(x).strip().strip("'\"")]


def _form_of(rc: ResearchContext, ref: str, kind: str = "") -> tuple:
    """F번호·이름 → (양식, None) 또는 (None, 모델에게 줄 말)."""
    from app.research.forms import form_line, match_form

    forms = rc.doc.get("_forms") or []
    if not forms:
        return None, "이 작업의 문서 양식에는 표·차트 양식이 없다 — 양식 없이 표·차트를 만든다."
    asset = match_form(forms, ref)
    if asset is None or (kind and asset["kind"] != kind):
        return None, "그런 표·차트 양식이 없다. 이 문서 양식의 표·차트 양식:\n" + "\n".join(form_line(i, a) for i, a in enumerate(forms))
    return asset, None


def _doc_table_pick(tables: List[Dict[str, Any]], ref: str) -> Optional[Dict[str, Any]]:
    if not ref:
        return tables[0] if len(tables) == 1 else None
    key = entities.norm(ref)
    pick = next((t for t in tables if key and key in entities.norm(t["caption"])), None)
    m = re.search(r"\d+", ref)
    return pick or (next((t for t in tables if t["no"] == int(m.group(0))), None) if m else None)


async def _use_form(asset: Dict[str, Any], rc: ResearchContext, *, rows: List[str], document: str, table_ref: str, period: str, title: str) -> tuple:
    """양식으로 표(차트 양식이면 계열을 열로 한 표 → 차트)를 만든다. → (만든 에셋 id 또는 None, 모델에게 줄 말).
    document 가 있으면 그 자료 속 표를 양식 열로 옮기고(원문 칸 그대로), 아니면 rows 로 자료를 찾아 채운다."""
    from app.ledger.figures import looks_like_period
    from app.research.doc_tables import create_from_doc, doc_tables
    from app.research.forms import form_chart_table_spec, form_meta, form_period_table, form_table_spec, map_columns, period_columns, shift_years

    chart = asset["kind"] == "chart"
    spec, groups = (form_chart_table_spec(asset), []) if chart else form_table_spec(asset)
    meta = form_meta(asset, rc.doc.get("reportType") or "", groups)
    title = title or asset["name"]
    if document:
        doc_id = _pick_doc(rc, document)
        if doc_id is None:
            return None, "그 자료를 이 작업의 데이터에서 찾지 못했다 — 자료 목록 번호(D번호)나 이름으로 다시."
        tables = await asyncio.to_thread(doc_tables, doc_id)
        if not tables:
            return None, "이 자료에는 칸 구조 표가 없다."
        pick = _doc_table_pick(tables, table_ref)
        if pick is None:
            def line(t: Dict[str, Any]) -> str:
                page = f" (p.{t['page']})" if t.get("page") else ""
                return f"표 {t['no']}{page} {t['caption'] or '(제목 없음)'} — {len(t['rows']) - 1}행, 머리: {' | '.join(t['rows'][0][:6])}"

            return None, "이 자료의 표:\n" + "\n".join(line(t) for t in tables[:15]) + "\n[내부 메모] 어느 표를 옮길지 분명하면 table 에 번호를 넣어 다시 부르고, 아니면 사용자에게 묻는다."
        col_map = await map_columns(spec["items"], pick["rows"], rc.llm)
        if not col_map:
            return None, f"'{pick['caption'] or '그 표'}' 에는 양식 '{asset['name']}' 의 열과 이어지는 열이 없다 — 다른 표를 고르거나 rows 로 자료를 찾아 채운다."

        def make() -> Dict[str, Any]:
            with Session(engine) as s:
                row = create_from_doc(s, rc.doc["workspaceId"], _user(s, rc), doc_id, pick["chunk"], chat_id=rc.doc["id"], spec=spec, title=title, col_map=col_map, max_rows=FORM_ROWS, form=meta)
                return {"id": row.id, "title": row.title, "data": row.data}

        made = await asyncio.to_thread(make)
        _attach(rc, made["id"], made["title"], made["data"])
        await _emit_table(made["id"], rc)
        empty = [it["label"] for it in spec["items"] if it["key"] not in col_map]
        msg = _summary(made["title"], made["data"]).replace("완료(오른쪽 패널)", "양식 모양으로 옮김(원문 칸 그대로)") + (f" — 원 표에 없어 빈 열: {', '.join(empty)}" if empty else "")
        table_id = made["id"]
    else:
        pcols = [] if chart else period_columns(asset)
        if not rows:
            what = "행(계정·지표 — 예: 매출액, 영업이익)" if pcols else "행(대상)"
            return None, f"[내부 메모] {what}이 정해지지 않았다 — 자료 목록·대화에서 분명하면 rows 에 넣어 다시 부르고, 아니면 어떤 {what}으로 채울지 사용자에게 한 문장으로 묻는다. 자료 속에 같은 내용의 표가 있으면 document 로 옮길 수 있다."
        if pcols and all(looks_like_period(r) and not re.search(r"[가-힣A-Za-z]{2,}", re.sub(r"분기|반기|상반기|하반기|FY", "", r)) for r in rows):
            return None, f"[내부 메모] '{asset['name']}' 양식은 열이 기간({', '.join(pcols)})이다 — rows 에는 기간이 아니라 계정·지표(예: 매출액, 영업이익)를 넣어 다시 부른다(연도는 코드가 자료의 최근 실적 연도에 맞춘다)."
        if pcols:
            # 재무표 양식(행 = 계정, 열 = 연도) — 대상 기업의 기간마다 계정을 찾는다. 연도는 자료의 최근 실적 연도에 맞춰 옮긴다
            entity = _arg((rc.doc.get("setup") or {}).get("subject")) or _title_entity(title, rc.doc.get("documentIds") or [])
            years = [int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", period or "")]  # '2023~2025' → 마지막 실적 2025
            base = max(years) if years else await asyncio.to_thread(_latest_year, rc, entity)
            pspec, subjects, items = form_period_table(asset, rows, shift_years(pcols, base))
            table_id, out = await _create_and_fill(pspec, subjects, {"entity": entity} if entity else {}, None, items, title, rc, form=meta)
        else:
            table_id, out = await _create_and_fill(spec, [{"label": r} for r in rows], {"period": period}, None, spec["items"], title, rc, form=meta)
        msg = _summary(title, out)
    if not chart:
        return table_id, msg
    chart_id, cmsg = await _form_chart(asset, table_id, rc, title)
    return (chart_id or table_id), f"{msg}\n{cmsg}"


def _latest_year(rc: ResearchContext, entity: str) -> Optional[int]:
    """이 작업 자료(대상 기업 자료가 있으면 그것만)의 원장에서 가장 최근 연간 실적 연도 — 없으면 None(양식 연도 그대로)."""
    from app.ledger.figures import load_figures

    docs = rc.doc.get("documentIds") or []
    if entity:
        mine = [d for d in docs if entities.norm(str(((load_meta(d) or {}).get("card") or {}).get("company") or "")) == entities.norm(entity)]
        docs = mine or docs
    years = [int(f["periodKey"]) for d in docs for f in load_figures(d) if re.fullmatch(r"(?:19|20)\d{2}", str(f.get("periodKey") or ""))]
    return max(years) if years else None


async def _form_chart(asset: Dict[str, Any], source: str, rc: ResearchContext, title: str) -> tuple:
    """차트 양식 + 원 표(지금 보는 표·표 id) → 차트. (차트 id 또는 None, 모델에게 줄 말)."""
    from fastapi import HTTPException

    from app.research.forms import CHART_LABEL, chart_body, form_meta

    row = await asyncio.to_thread(_current, rc, source)
    if row is not None and row.kind == "chart":
        row = await asyncio.to_thread(_current, rc, ((row.data or {}).get("chart") or {}).get("source") or "")
    if row is None:
        return None, "차트로 그릴 표가 없다 — 먼저 표를 만들거나(rows) 자료 속 표를 옮긴다(document)."
    body = {**chart_body(asset, row.data or {}, title or asset["name"]), "form": form_meta(asset, rc.doc.get("reportType") or "")}

    def make() -> Dict[str, Any]:
        with Session(engine) as s:
            ch = ResearchService(s).make_chart(row.id, _user(s, rc), body, chat_id=rc.doc["id"])
            return {"id": ch.id, "title": ch.title, "data": ch.data}

    try:
        ch = await asyncio.to_thread(make)
    except HTTPException as e:
        return None, f"차트를 만들지 못함: {e.detail}"
    _attach(rc, ch["id"], ch["title"], ch["data"])
    await _emit_table(ch["id"], rc)
    data = ch["data"]
    names = ", ".join(s["name"] for s in data["series"] if not s.get("computed"))
    note = f" — 단위가 달라 뺀 열: {', '.join(data['dropped'])}" if data.get("dropped") else ""
    band = " 평균·표준편차 띠선은 그린 값으로 코드가 계산했다(계산값)." if data["chart"]["type"] == "band" else ""
    return ch["id"], f"{CHART_LABEL.get((asset.get('chart') or {}).get('type'), '')} 차트 '{ch['title']}' 완료(양식 모양) — 계열 {names}, 범주 {len(data['categories'])}개{note}.{band}"


_HANDLERS = {"insert_form": _insert_form, "extract_table": _extract_table, "save_note": _save_note, "fill_slots": _fill_slots, "find_items": _find_items, "open_asset": _open_asset, "build_table": _build_table, "update_table": _update_table, "build_chart": _build_chart, "save_template": _save_template, "save_table_to_drive": _save_table_to_drive, "insert_asset": _insert_asset}


async def run_tool(name: str, args: Dict[str, Any], rc: ResearchContext) -> str:
    if name in _HANDLERS:
        return await _HANDLERS[name](args, rc)
    if name in REUSED:
        return await run_agent_tool(name, args, rc.agent)
    return f"[내부 메모] {name} 은(는) 없는 도구입니다. 쓸 수 있는 도구: {', '.join(TOOL_NAMES)}."
