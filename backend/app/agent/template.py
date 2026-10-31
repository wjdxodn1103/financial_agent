"""리포트 유형별 틀 — 논문의 "가이드라인 맵 + 템플릿 소절"(OP paper/bundle/coverage.py·template.py)을 대신한다.

유형마다 섹션 항목(items)을 정의한다. 새 세션은 항목을 빈 섹션으로 깔고(seed_sections), 진행률은 "쓰인 섹션이 다룬 항목"으로 센다.
항목 필드:
  id·title     섹션 이름(별칭 aliases 로도 찾는다)
  phase        front(요약) | body | back — 리포트 안 위치는 items 순서가 정한다
  level        required | recommended
  desc         작성기에게 주는 섹션 지침(한두 문장)
  queries      작성 전 미리 찾기 질의({company} 는 대상 기업·산업으로 바꾼다)
  inputs       확인 카드 2단계 입력칸(자료에 없는 사용자 판단 — 투자의견·기준 주가 등). 값은 근거로 인정된다
order 는 권장 작성 순서(본문 먼저, 요약은 마지막).

틀만 옮긴 단계라 항목·지침은 출발점이다 — 실제 서비스 기획에 맞춰 이 파일만 고치면 된다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.formats.registry import FORMATS, label

Item = Dict[str, Any]

_OPINION = {"key": "opinion", "label": "투자의견(선택)", "placeholder": "예: 매수 / 중립 / 의견 제시 안 함"}
_TARGET = {"key": "target_price", "label": "목표주가와 산정 근거(선택)", "placeholder": "예: 85,000원 — 12개월 선행 PER 12배", "multiline": True}
_PRICE = {"key": "price_basis", "label": "기준 주가·기준일(선택)", "placeholder": "예: 72,300원 (2025-06-30 종가)"}
_PEERS = {"key": "peers", "label": "비교 대상 기업(선택)", "placeholder": "예: SK하이닉스, Micron, TSMC"}
_QUESTION = {"key": "question", "label": "검토 질의(선택)", "placeholder": "예: 해외 출장 시 법인카드 사용 한도 초과분 처리 기준", "multiline": True}

REPORT_TYPES: Dict[str, Dict[str, Any]] = {
    "equity": {
        "title": "기업 분석 리포트",
        "desc": "사업보고서·IR·실적 자료로 한 기업의 사업·실적·밸류에이션·리스크를 정리합니다.",
        "items": [
            {"id": "summary", "title": "투자 요약", "phase": "front", "level": "required", "aliases": ["요약", "핵심 요약", "투자 포인트", "investment summary"],
             "desc": "핵심 투자 포인트 3가지를 글머리표로 먼저 제시하고, 이어서 실적·밸류에이션·리스크를 한 문단으로 묶는다. 다른 섹션의 결론과 어긋나지 않게 쓴다.",
             "queries": ["{company} 핵심 성장 동력", "{company} 실적 개선 요인", "{company} 주요 리스크"], "inputs": [_OPINION, _TARGET]},
            {"id": "company", "title": "기업 개요", "phase": "body", "level": "required", "aliases": ["회사 개요", "사업 개요", "company overview"],
             "desc": "주요 사업·제품, 사업부문별 매출 구성, 지배구조·주요 주주 등 기업을 이해하는 데 필요한 사실을 정리한다.",
             "queries": ["{company} 주요 사업 및 제품", "{company} 사업부문별 매출 구성", "{company} 최대주주 및 지배구조"], "inputs": []},
            {"id": "industry", "title": "산업 및 경쟁 환경", "phase": "body", "level": "required", "aliases": ["산업 환경", "경쟁 환경", "산업 분석", "시장 환경"],
             "desc": "시장 규모·성장률·수요 동인과 주요 경쟁사 대비 위치(점유율·기술·원가)를 정리한다.",
             "queries": ["{company} 시장 동향 및 수요", "{company} 경쟁사 점유율", "{company} 산업 성장 전망"], "inputs": [_PEERS]},
            {"id": "performance", "title": "실적 분석", "phase": "body", "level": "required", "aliases": ["실적", "재무 분석", "실적 리뷰", "earnings"],
             "desc": "최근 실적(매출·영업이익·순이익·이익률)의 증감과 원인을 부문별로 분석한다. 전년·전분기 대비 변화를 수치로 쓴다.",
             "queries": ["{company} 매출액 영업이익 증감", "{company} 부문별 실적", "{company} 영업이익률 변화 원인"], "inputs": []},
            {"id": "valuation", "title": "밸류에이션", "phase": "body", "level": "recommended", "aliases": ["가치 평가", "valuation", "목표주가"],
             "desc": "자료의 재무 수치와 사용자가 준 기준 주가·배수로 PER·PBR 등 상대가치를 정리한다. 자료에 없는 추정치는 쓰지 않는다.",
             "queries": ["{company} 주당순이익 자본총계", "{company} 배당 및 주주환원"], "inputs": [_PRICE, _TARGET]},
            {"id": "risks", "title": "리스크 요인", "phase": "back", "level": "required", "aliases": ["리스크", "위험 요인", "투자 위험", "risk"],
             "desc": "실적·재무·규제·시장 측면의 하방 리스크와 점검 지표를 정리한다.",
             "queries": ["{company} 위험 요인", "{company} 소송 및 우발채무", "{company} 환율 원자재 민감도"], "inputs": []},
        ],
        "order": ["company", "industry", "performance", "valuation", "risks", "summary"],
    },
    "industry": {
        "title": "산업 동향 리포트",
        "desc": "산업·경제 자료로 시장 구조와 최근 동향, 주요 기업 움직임, 전망을 정리합니다.",
        "items": [
            {"id": "summary", "title": "핵심 요약", "phase": "front", "level": "required", "aliases": ["요약", "summary"],
             "desc": "이 산업의 지금 상황과 앞으로의 방향을 핵심 메시지 3가지로 요약한다.", "queries": ["{company} 핵심 동향", "{company} 전망"], "inputs": []},
            {"id": "overview", "title": "산업 개요", "phase": "body", "level": "required", "aliases": ["산업 구조", "시장 개요"],
             "desc": "산업의 정의·가치사슬·시장 규모와 성장률을 정리한다.", "queries": ["{company} 시장 규모 성장률", "{company} 가치사슬 구조"], "inputs": []},
            {"id": "trends", "title": "최근 동향", "phase": "body", "level": "required", "aliases": ["동향", "주요 이슈", "시장 동향"],
             "desc": "최근 수요·가격·정책·기술 변화와 그 원인을 정리한다.", "queries": ["{company} 최근 수요 가격 변화", "{company} 정책 규제 변화", "{company} 기술 변화"], "inputs": []},
            {"id": "players", "title": "주요 기업 동향", "phase": "body", "level": "recommended", "aliases": ["주요 기업", "경쟁 구도", "기업 동향"],
             "desc": "주요 기업의 실적·투자·전략 변화를 비교한다.", "queries": ["{company} 주요 기업 실적", "{company} 설비 투자 계획"], "inputs": [_PEERS]},
            {"id": "outlook", "title": "전망 및 시사점", "phase": "body", "level": "required", "aliases": ["전망", "시사점", "outlook"],
             "desc": "자료가 제시하는 전망과 투자 관점의 시사점을 정리한다(자료의 전망과 분석가 해석을 구분한다).", "queries": ["{company} 향후 전망", "{company} 성장 기회"], "inputs": []},
            {"id": "risks", "title": "리스크 및 점검 지표", "phase": "back", "level": "recommended", "aliases": ["리스크", "점검 지표"],
             "desc": "하방 리스크와 앞으로 확인할 지표를 정리한다.", "queries": ["{company} 위험 요인", "{company} 불확실성"], "inputs": []},
        ],
        "order": ["overview", "trends", "players", "outlook", "risks", "summary"],
    },
    "peer": {
        "title": "Peer 비교 분석",
        "desc": "대상 기업과 경쟁사(Peer Group)의 사업·재무·밸류에이션을 나란히 비교합니다.",
        "items": [
            {"id": "summary", "title": "비교 요약", "phase": "front", "level": "required", "aliases": ["요약"],
             "desc": "대상 기업이 Peer 대비 어디서 강하고 약한지 핵심 3가지로 요약한다.", "queries": ["{company} 경쟁 우위", "{company} 경쟁 열위"], "inputs": []},
            {"id": "selection", "title": "비교 대상과 기준", "phase": "body", "level": "required", "aliases": ["peer group", "비교 대상", "비교 기준"],
             "desc": "비교 대상 기업과 선정 이유, 비교 기간·기준(연결/별도, 회계연도)을 밝힌다.", "queries": ["{company} 경쟁사", "{company} 동종 업체"], "inputs": [_PEERS]},
            {"id": "business", "title": "사업 구조 비교", "phase": "body", "level": "required", "aliases": ["사업 비교", "사업 구조"],
             "desc": "제품·고객·지역 매출 구성과 사업 모델 차이를 비교한다.", "queries": ["{company} 매출 구성", "{company} 주요 고객 지역"], "inputs": []},
            {"id": "financials", "title": "재무 지표 비교", "phase": "body", "level": "required", "aliases": ["재무 비교", "수익성 비교", "재무 지표"],
             "desc": "성장성·수익성·안정성 지표를 같은 기준으로 비교한다(기준이 다르면 밝힌다).", "queries": ["{company} 매출 성장률 영업이익률", "{company} 부채비율 ROE"], "inputs": []},
            {"id": "valuation", "title": "밸류에이션 비교", "phase": "body", "level": "recommended", "aliases": ["밸류에이션", "가치 평가 비교"],
             "desc": "PER·PBR·EV/EBITDA 등 배수를 비교하고 격차의 이유를 해석한다.", "queries": ["{company} PER PBR", "{company} 주가 배수"], "inputs": [_PRICE]},
            {"id": "implications", "title": "시사점", "phase": "back", "level": "required", "aliases": ["결론", "투자 시사점"],
             "desc": "비교에서 나온 투자 시사점과 추가로 확인할 점을 정리한다.", "queries": ["{company} 시사점"], "inputs": []},
        ],
        "order": ["selection", "business", "financials", "valuation", "implications", "summary"],
    },
    "memo": {
        "title": "내부 문서 검토 메모",
        "desc": "내부 규정·지침·계약서를 찾아 질의에 대한 근거와 검토 의견을 정리합니다.",
        "items": [
            {"id": "summary", "title": "검토 요약", "phase": "front", "level": "required", "aliases": ["요약", "결론"],
             "desc": "질의에 대한 결론을 두세 문장으로 먼저 쓴다.", "queries": [], "inputs": []},
            {"id": "background", "title": "검토 배경", "phase": "body", "level": "required", "aliases": ["배경", "질의 내용"],
             "desc": "무엇을 왜 검토하는지(질의·상황)를 정리한다.", "queries": [], "inputs": [_QUESTION]},
            {"id": "rules", "title": "관련 규정 및 근거", "phase": "body", "level": "required", "aliases": ["관련 규정", "근거 규정", "규정"],
             "desc": "질의와 관련된 조항을 찾아 조항 번호·요지를 정리한다(원문 표현을 살린다).", "queries": ["{company} 관련 조항", "{company} 적용 기준"], "inputs": []},
            {"id": "opinion", "title": "검토 의견", "phase": "body", "level": "required", "aliases": ["의견", "판단"],
             "desc": "규정을 질의에 적용한 판단과 해석의 여지, 예외를 정리한다.", "queries": ["{company} 예외 조항", "{company} 승인 절차"], "inputs": []},
            {"id": "actions", "title": "후속 조치", "phase": "back", "level": "recommended", "aliases": ["조치 사항", "후속 절차"],
             "desc": "필요한 승인·절차·담당 부서를 정리한다.", "queries": ["{company} 승인 권한 담당 부서"], "inputs": []},
        ],
        "order": ["background", "rules", "opinion", "actions", "summary"],
    },
}
# 양식 없는 작업 — AI 작업을 새로 열면 이것(문서는 아직 없다. 섹션은 쓰면서 생긴다)
REPORT_TYPES["free"] = {"title": "양식 없음", "desc": "양식 없이 필요한 섹션만 씁니다.", "kind": "free", "items": [], "order": []}
# 고정 양식(app/formats) — 같은 틀(items·order)에 섹션마다 표·그림 블록이 붙는 리포트 종류
REPORT_TYPES.update(FORMATS)
DEFAULT_TYPE = "equity"


REGISTERED = "rt:"  # 샘플에서 등록한 리포트 양식(DB ReportTemplate) — 'rt:<id>'
_registered: Dict[str, Dict[str, Any]] = {}


def blueprint_items(bp: Dict[str, Any]) -> List[Item]:
    """양식 2.0 틀 → 쓰는 단위 항목 — 요약 1칸 + 장마다 소주제 칸(장 띠·부록·표지는 문서 layout 메타로 그린다).
    소주제 칸은 required(진행률이 처음부터 '완료'로 보이지 않게). part·role·depth·blocks 는 섹션에 그대로 실린다(session.seed_sections)."""
    rules = bp.get("rules") or {}
    items: List[Item] = []
    for p in bp.get("parts") or []:
        if p.get("role") == "summary":
            blocks = list(p.get("blocks") or []) + list(p.get("sidebar") or [])
            items.append({"id": "summary", "title": "요약", "phase": "front", "level": "required", "aliases": ["요약", "투자 요약"],
                          "desc": f"{rules.get('claim') or ''} 주장 {p.get('claims') or 3}개를 '[제목] 주장' 줄로 시작하는 문단으로.",
                          "queries": [], "inputs": [], "part": "summary", "role": "summary", "depth": 1, "blocks": blocks})
        elif p.get("role") == "chapter":
            for k, s in enumerate(p.get("subtopics") or []):
                items.append({"id": f"{p['id']}_{k + 1}", "title": s.get("title") or f"{p['title']} {k + 1}", "phase": "body", "level": "required",
                              "aliases": [x for x in [s.get("example")] if x], "desc": " ".join(x for x in [s.get("guide"), p.get("guide")] if x),
                              "queries": [], "inputs": [], "part": p["id"], "role": "subsection", "depth": 2, "blocks": list(s.get("blocks") or [])})
    return items


def registered_to_type(row: Any) -> Dict[str, Any]:
    """ReportTemplate → REPORT_TYPES 와 같은 모양(섹션 = 항목, 안내 = desc, 자리 = slots). 양식 2.0 틀이 있으면 틀에서(blueprint_items)."""
    bp = (row.spec or {}).get("blueprint")
    if isinstance(bp, dict) and bp.get("version") == 2:
        items = blueprint_items(bp)
        order = [it["id"] for it in items if it["id"] != "summary"] + [it["id"] for it in items if it["id"] == "summary"]  # 장 먼저, 요약은 맨 뒤
        forms = [{"id": f["id"], "kind": f["kind"], "name": f.get("title") or "", "desc": "", "chartType": ""} for f in (bp.get("forms") or {}).values() if f.get("kind") == "table"]
        return {"title": row.name, "desc": (row.spec or {}).get("desc") or bp.get("desc") or "", "style": (row.spec or {}).get("style") or bp.get("style") or "", "kind": "registered",
                "items": items, "order": order, "scope": row.scope, "workspaceId": row.workspace_id, "ownerId": row.owner_id, "assets": forms, "blueprint": bp}
    secs = (row.spec or {}).get("sections") or []
    items = [
        {"id": s.get("id") or f"s{i + 1}", "title": s["title"], "phase": "body", "level": "recommended", "aliases": [], "desc": s.get("guide") or "", "queries": [], "inputs": [], "slots": s.get("slots") or []}
        for i, s in enumerate(secs)
    ]
    # assets = 샘플에서 뽑은 표·차트 양식(templates_import/forms.py) — 문서 화면의 '표·차트 넣기' 목록(report/view.py forms)
    assets = [{"id": a["id"], "kind": a["kind"], "name": a["name"], "desc": a.get("desc") or "", "chartType": (a.get("chart") or {}).get("type") or ""} for a in (row.spec or {}).get("assets") or []]
    return {"title": row.name, "desc": (row.spec or {}).get("desc") or "", "style": (row.spec or {}).get("style") or "", "kind": "registered", "items": items, "order": [it["id"] for it in items], "scope": row.scope, "workspaceId": row.workspace_id, "ownerId": row.owner_id, "assets": assets}


def registered_type(type_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not type_id or not type_id.startswith(REGISTERED):
        return None
    if type_id not in _registered:
        from sqlmodel import Session

        from app.db import ReportTemplate, engine

        with Session(engine) as s:
            row = s.get(ReportTemplate, type_id[len(REGISTERED):])
            if row is None:
                return None
            _registered[type_id] = registered_to_type(row)
    return _registered[type_id]


def forget_registered(type_id: str) -> None:
    _registered.pop(type_id, None)


def known_type(type_id: Optional[str]) -> bool:
    return bool(type_id) and (type_id in REPORT_TYPES or registered_type(type_id) is not None)


def report_type(type_id: Optional[str]) -> Dict[str, Any]:
    reg = registered_type(type_id)
    if reg is not None:
        return reg
    return REPORT_TYPES.get(type_id or DEFAULT_TYPE) or REPORT_TYPES[DEFAULT_TYPE]


def items_of(type_id: Optional[str]) -> List[Item]:
    return report_type(type_id)["items"]


def item_of(item_id: str, type_id: Optional[str]) -> Optional[Item]:
    return next((it for it in items_of(type_id) if it["id"] == item_id), None)


def _norm(s: str) -> str:
    return re.sub(r"[\s·・,/()\[\]]+", "", (s or "").lower())


def match_item(title: str, type_id: Optional[str]) -> Optional[Item]:
    """섹션 제목 → 항목(제목·별칭 일치, 없으면 None = 사용자 정의 섹션)."""
    t = _norm(title)
    if not t:
        return None
    for it in items_of(type_id):
        if t == _norm(it["title"]) or any(t == _norm(a) for a in it.get("aliases") or []):
            return it
    for it in items_of(type_id):
        names = [it["title"], *(it.get("aliases") or [])]
        if any(len(_norm(n)) >= 2 and (_norm(n) in t or t in _norm(n)) for n in names):
            return it
    return None


def rank_of(covers: List[str], type_id: Optional[str]) -> int:
    ids = [it["id"] for it in items_of(type_id)]
    return min((ids.index(c) for c in covers if c in ids), default=len(ids))


def write_order(type_id: Optional[str]) -> List[str]:
    return report_type(type_id)["order"]


def public_types() -> List[Dict[str, Any]]:
    """FE meta — 유형 선택 칩·진행 맵·카드 입력칸. 고정 양식은 kind=format + 태그·표/그림 블록 요약(양식 찾기 화면)."""
    out = []
    for tid, t in REPORT_TYPES.items():
        blocks = t.get("blocks") or {}
        out.append(
            {
                "id": tid,
                "title": t["title"],
                "desc": t["desc"],
                "kind": t.get("kind", "type"),
                "tags": t.get("tags") or [],
                "sample": t.get("sample") or "",
                "dataNote": t.get("dataNote") or "",
                "items": [
                    {k: it[k] for k in ("id", "title", "phase", "level", "desc")}
                    | {"inputs": it.get("inputs") or [], "blocks": [{"id": b, "kind": blocks[b]["kind"], "no": blocks[b]["no"], "label": label(blocks[b])} for b in it.get("blocks") or [] if b in blocks]}
                    for it in t["items"]
                ],
                "order": t["order"],
                "tables": sum(1 for b in blocks.values() if b["kind"] == "table"),
                "charts": sum(1 for b in blocks.values() if b["kind"] == "chart"),
            }
        )
    return out
