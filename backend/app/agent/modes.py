"""AI 작업 모드 — 하나씩 고른다: 일반 · 리서치 · 문서 작성({research, writing} 중 하나만 참, 둘 다 거짓 = 일반).

일반      = 도구·작업 프롬프트 없는 대화
리서치    = 자료 찾기(수치·근거)로 조사·답변 + 데이터 정리(출처 달린 표·차트·메모 — 대화 안에 두고 저장할지 묻는다) + 정리한 데이터·자료 찾기
문서 작성 = 고른 양식대로 섹션 쓰기·고치기·계획 + 양식 자리 채우기·문서 양식의 표·차트 양식으로 표·차트 넣기(insert_form)·대화에서 정리한 표 넣기, 쓰다가 묻는 질문용 자료 찾기
문서 작성에서 다른 모드로 바꾸면 그 시점 문서를 판으로 남긴다(report_service — 리서치는 문서를 건드리지 않는다).
켜진 모드의 도구만 모델에 보낸다(도구가 많으면 모델이 엉뚱한 것을 고른다).
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.agent.session import Doc

LOOKUP = ("search_documents", "lookup_figures", "calculate", "list_documents", "fetch_dart")
WRITING = ("get_progress", "use_format", "set_report_meta", "write_section", "revise_section", "propose_plan", "continue_plan", "update_outline", "add_block", "remove_block")
# research/tools.py 의 도구(이 대화 루프에서는 research.tools.run_tool 로 보낸다)
FIND = ("find_items", "open_asset")
RESEARCH_ONLY = ("build_table", "update_table", "build_chart", "extract_table", "save_template", "save_table_to_drive", "save_note", *FIND)
WRITING_ONLY_RESEARCH = ("insert_form", "insert_asset", "fill_slots", *FIND)


def has_doc(doc: Doc) -> bool:
    """문서가 붙어 있나 — 양식을 골랐거나(free 가 아님) 섹션이 하나라도 있다."""
    return (doc.get("reportType") or "free") != "free" or bool(doc.get("sections"))


def normalize(raw: Any, doc: Doc) -> Dict[str, bool]:
    """요청의 modes → {research, writing}. 없으면 이 작업에 저장된 값, 그것도 없으면 문서가 있는 옛 작업은 문서 작성만 켠다."""
    src = raw if isinstance(raw, dict) else doc.get("modes")
    if isinstance(src, dict):
        writing = bool(src.get("writing"))
        return {"research": bool(src.get("research")) and not writing, "writing": writing}  # 하나씩 — 둘 다 오면 문서 작성
    return {"research": False, "writing": has_doc(doc)}


def tool_names(modes: Dict[str, bool]) -> List[str]:
    names: List[str] = []
    if modes.get("research"):
        names += [*LOOKUP, *RESEARCH_ONLY]
    if modes.get("writing"):
        names += [*LOOKUP, *WRITING, *WRITING_ONLY_RESEARCH]
    return list(dict.fromkeys(names))


def tool_defs(modes: Dict[str, bool]) -> List[Dict[str, Any]]:
    """켜진 모드의 도구 정의 — 문서 작성 도구(agent/tools) + 리서치 도구(research/tools)."""
    from app.agent.tools import TOOL_DEFS
    from app.research.tools import FIND_TOOLS, NEW_TOOLS, WRITING_TOOLS

    wanted = tool_names(modes)
    pool = {t["function"]["name"]: t for t in [*TOOL_DEFS, *NEW_TOOLS, *FIND_TOOLS, *WRITING_TOOLS]}
    return [pool[n] for n in wanted if n in pool]


def plain_history(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """일반 대화(도구 없음)용 — 도구 호출·결과를 걷고 사람이 본 글만 남긴다(도구를 선언하지 않은 호출에 tool 메시지가 섞이면 거부하는 서버가 있다)."""
    out: List[Dict[str, Any]] = []
    for m in history:
        role = m.get("role")
        if role == "user" and isinstance(m.get("content"), str):
            out.append({"role": "user", "content": m["content"]})
        elif role == "assistant" and isinstance(m.get("content"), str) and m["content"].strip() and not m["content"].startswith("["):
            out.append({"role": "assistant", "content": m["content"]})
    return out
