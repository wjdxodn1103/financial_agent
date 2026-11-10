"""사내 공통 '예시' 문서 양식 — KIC 업무 이름의 양식 틀(실제 KIC 양식이 아니라 공개된 구조로 만든 예시).
재심의 안건(가정 감시)·IC 심의 요약(회의록 정리)·해외주식 동향 브리핑(루틴)·월간 투자분석·대체투자 검토·리스크 보고서.
id 를 고정해 두어 서버를 다시 켜도 한 번만 들어간다(사용자가 지웠으면 다시 넣지 않는다 — 처음 한 번만).
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from sqlmodel import Session

from app.db import ReportTemplate, engine

S = Tuple[str, str]  # (섹션 제목, 작성 안내)

EXAMPLES: List[Tuple[str, str, str, List[S]]] = [
    ("kicrereview", "재심의 안건(예시)", "감시 중인 가정이 깨졌을 때 재심의를 올리는 안건", [
        ("안건 개요", "어떤 투자 결정(대상·결정 기구·날짜·규모)의 어떤 가정이 깨졌는지 두세 문장."),
        ("깨진 가정과 근거", "가정 문장, 조건, 당시 근거 값과 지금 값을 나란히 — 숫자마다 원문 인용."),
        ("당시 심의 쟁점", "당시 안건·회의록의 찬반 논거와 미해결 질문(원문 인용)."),
        ("영향과 선택지", "유지·축소·재검토 같은 선택지와 각각 확인할 점 — 판단은 사람이 한다."),
        ("제안", "재심의에서 결정할 것과 필요한 추가 자료."),
    ]),
    ("kicicminutes", "IC 심의 요약(예시)", "투자위원회 회의록을 안건별로 정리(보조 멤버 관점)", [
        ("회의 개요", "날짜·참석·안건 목록."),
        ("안건별 핵심 쟁점", "안건마다 쟁점을 발언 인용과 함께."),
        ("찬성 논거", "발언 인용."),
        ("반대 논거", "발언 인용."),
        ("리스크 요인", "언급된 리스크와 완화 방안."),
        ("추가 검토 질문", "다음 회의 전에 확인할 질문."),
        ("결정 사항", "결정·조건·담당 — 결정 문장은 감시할 가정 후보가 된다."),
    ]),
    ("kicusbrief", "해외주식 동향 브리핑(예시)", "매일 아침 해외주식 운용역용 브리핑(루틴용)", [
        ("오늘의 시장 요약", "금리·환율·지수 움직임 — 숫자는 시장 데이터 문서 인용."),
        ("금리·환율·원자재", "전일·1주·1달 변화와 출처."),
        ("오늘·이번 주 발표 일정", "경제 일정 문서의 '이번 주 발표 일정' 표에서 중요한 지표의 한국 시각·현지 시각·이전 값을 그대로(시각은 기억으로 쓰지 않는다). "
                                 "서머타임 등 시간대가 바뀌는 주면 바뀌는 한국 시각을 한 줄로 — 경제 일정 문서의 시간대 규칙·시간대 변경 표 인용."),
        ("주요 공시·보도자료", "밤사이 들어온 공시·중앙은행 보도자료 요점(원문 인용). 시장·거시 데이터와 경제 일정 문서는 다른 섹션이 쓴다."),
        ("감시 중인 가정", "판정이 바뀐 가정과 지금 값."),
        ("확인할 점", "오늘 확인할 것 세 가지 이내. 발표 시각은 '오늘·이번 주 발표 일정' 섹션에 있으니 되풀이하지 않고 지표 이름만 가리킨다."),
    ]),
    ("kicmonthly", "월간 투자분석(예시)", "월간 투자분석 보고서 초안", [
        ("시장 환경", "한 달 동안의 금리·환율·지수 변화."),
        ("자산군별 성과", "자산군별 수익률과 벤치마크 대비(자료 인용)."),
        ("주요 변동 요인", "성과를 움직인 요인 — 자료에 근거한 것만."),
        ("포트폴리오 시사점", "확인할 노출·가정."),
        ("다음 달 점검 사항", "일정과 지표."),
    ]),
    ("kicaltreview", "대체투자 검토(예시)", "대체투자(PE·부동산·인프라) 검토보고서 초안", [
        ("투자 개요", "펀드·자산·규모·약정 조건."),
        ("운용사 역량", "트랙레코드·팀·전략(자료 인용)."),
        ("성과", "IRR·TVPI 등 — 숫자는 원문 칸 인용."),
        ("주요 리스크", "리스크와 완화 방안."),
        ("검토 사항", "실사·계약에서 확인할 것."),
    ]),
    ("kicrisk", "리스크 보고서(예시)", "리스크 보고서 초안", [
        ("요약", "주요 위험지표 변화 세 줄."),
        ("주요 위험지표 변동", "지표별 값과 변화(출처)."),
        ("변동 요인", "자료에 근거한 요인."),
        ("한도·가이드라인 점검", "한도 대비 위치와 위반·근접 항목."),
        ("검토 필요 항목", "담당과 기한."),
    ]),
]


def _spec(desc: str, secs: List[S]) -> Dict[str, Any]:
    return {"desc": desc, "style": "", "example": True, "sections": [{"id": f"s{i + 1}", "title": t, "level": 1, "guide": g, "slots": []} for i, (t, g) in enumerate(secs)], "assets": []}


# 예시 양식을 고쳤을 때 — DB 의 섹션(제목·안내)이 예전 판과 글자까지 같을 때만(사용자가 고치지 않음) 새 판으로 바꾼다
_BRIEF_V1: List[S] = [
    ("오늘의 시장 요약", "금리·환율·지수 움직임 — 숫자는 시장 데이터 문서 인용."),
    ("금리·환율·원자재", "전일·1주·1달 변화와 출처."),
    ("주요 공시·보도자료", "밤사이 들어온 공시·중앙은행 보도자료 요점(원문 인용)."),
    ("감시 중인 가정", "판정이 바뀐 가정과 지금 값."),
    ("확인할 점", "오늘 확인할 것 세 가지 이내."),
]
_BRIEF_V2: List[S] = [  # 2026-10-31 1차 — '오늘·이번 주 발표 일정' 추가
    *_BRIEF_V1[:2],
    ("오늘·이번 주 발표 일정", "경제 일정 문서의 '이번 주 발표 일정' 표에서 중요한 지표의 한국 시각·현지 시각·이전 값을 그대로(시각은 기억으로 쓰지 않는다). "
                             "서머타임 등 시간대가 바뀌는 주면 바뀌는 한국 시각을 한 줄로 — 경제 일정 문서의 시간대 규칙·시간대 변경 표 인용."),
    *_BRIEF_V1[2:],
]
PREVIOUS: Dict[str, List[List[S]]] = {"kicusbrief": [_BRIEF_V1, _BRIEF_V2]}  # 2026-10-31 2차 — 공시·확인할 점 안내에 범위


def _market_form(fid: str, title: str, table: str, position: str, kind: str = "table") -> Dict[str, Any]:
    return {"id": fid, "kind": kind, "title": title, "position": position, "market": {"table": table}, **({"chart": {"type": "bar", "color": "#2E75B6"}} if kind == "figure" else {})}


# 전일 증시 요약 — 증권사 아침 데일리 한 쪽 짜임(왼쪽: 글로벌 주식·채권/환율/원자재 표 + 시장 리뷰, 오른쪽: 업종별 등락률 차트 + 주요 체크 포인트).
# 표·차트는 그날의 '증시 요약 데이터' 자료로 코드가 채우고(app/market/daily.py), '글로벌 시장 리뷰'만 모델이 쓴다. 틀(양식 2.0) 꼴이라 한 번 고치면 새 문서부터 적용된다.
MARKET_DAILY_ID = "kicmarketdaily"
MARKET_DAILY: Dict[str, Any] = {
    "desc": "매일 아침 전일 증시 요약 — 지수·금리·환율·원자재 표, 업종별 등락률, 경제지표 일정, 시장 리뷰(루틴용)",
    "style": "증권사 데일리 문체: 개조식, 명사형 종결('~상승 마감', '~하락', '~기록'). 숫자는 자료의 표기 그대로, 원인은 기사 근거가 있을 때만.",
    "example": True, "sections": [], "assets": [],
    "blueprint": {
        "version": 2, "name": "전일 증시 요약", "desc": "전일 증시 요약(아침 데일리)", "prepare": "market_daily", "writer": "market_daily",
        "theme": {"accent": "#2E75B6", "bandFill": "#2E75B6", "bandText": "#FFFFFF", "sidebarFill": "#F5F8FC", "sidebarWidth": 46, "captionColor": "#1F4E79"},
        "rules": {"claim": "", "keyline": "", "para": "", "caption": "", "source": ""},
        "style": "증권사 데일리 문체: 개조식, 명사형 종결('~상승 마감', '~하락', '~기록'). 숫자는 자료의 표기 그대로, 원인은 기사 근거가 있을 때만.",
        "parts": [{"id": "summary", "role": "summary", "title": "전일 증시 요약", "heading": "전일 증시 요약", "layout": "main+sidebar", "sidebarWidth": 46, "claims": 0,
                   "guide": "표(글로벌 주식, 채권/환율/원자재) 아래에 '글로벌 시장 리뷰'를 글머리표 4~5줄로.",
                   "blocks": ["t_equity", "t_macro"], "sidebar": ["f_sector", "t_prev", "t_today"]}],
        "forms": {
            "t_equity": _market_form("t_equity", "글로벌 주식", "equity", "main"),
            "t_macro": _market_form("t_macro", "채권/환율/원자재", "macro", "main"),
            "f_sector": _market_form("f_sector", "S&P500 업종별 등락률", "sector", "sidebar", kind="figure"),
            "t_prev": _market_form("t_prev", "전일 주요 경제지표", "prev", "sidebar"),
            "t_today": _market_form("t_today", "오늘 주요 경제지표", "today", "sidebar"),
        },
    },
}


def seed() -> None:
    with Session(engine) as s:
        t = s.get(ReportTemplate, MARKET_DAILY_ID)
        if t is None:
            s.add(ReportTemplate(id=MARKET_DAILY_ID, scope="company", workspace_id="", owner_id="", name="전일 증시 요약(예시)", source_name="", spec=MARKET_DAILY))
        elif (t.spec or {}).get("example") and (t.spec or {}).get("blueprint") != MARKET_DAILY["blueprint"]:
            t.spec = MARKET_DAILY  # 예시 양식은 코드가 정본(사용자가 고칠 수 없는 사내 예시)
            s.add(t)
        for rid, name, desc, secs in EXAMPLES:
            t = s.get(ReportTemplate, rid)
            if t is None:
                s.add(ReportTemplate(id=rid, scope="company", workspace_id="", owner_id="", name=name, source_name="", spec=_spec(desc, secs)))
            elif [(x.get("title"), x.get("guide")) for x in (t.spec or {}).get("sections") or []] in [list(v) for v in PREVIOUS.get(rid, [])]:
                t.spec = {**t.spec, "sections": _spec(desc, secs)["sections"]}
                s.add(t)
        s.commit()


def type_id(key: str) -> str:
    return f"rt:{key}"
