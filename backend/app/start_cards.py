"""AI 작업 시작 화면의 추천 카드 4개 — 이 사람의 기록만으로 코드가 고른다(LLM 없음, 없는 일을 지어내지 않는다, 대화는 개인 원칙대로 내 것만).

후보(위에서부터 하나씩, 4개가 차면 끝):
  due       내 할 일 중 기한 지남·오늘 마감 → 할 일 화면
  review    받은 검토 요청(아직 안 끝낸 것) → 그 문서
  continue  쓰다 만 내 문서(작성 < 섹션, 최근) → 그 문서
  routine   같은 요일에 다른 주 두 번 이상 시작한 같은 질문 → 그 질문 보내기
  same      새로 올라온 자료 속 표가 비슷한 문서에서 만든 에셋과 같은 모양 → 자료 속 표 창(같은 모양으로 만들기)
  template  최근 30일 두 번 이상 쓴 표 양식 → 그때 행으로 다시
  format    두 번 이상 쓴 문서 양식 → 그 양식으로 문서 시작
  new       지난 3일 새 자료 → 핵심 요약(리서치)
  default   기본 카드 — 평소 많이 켠 모드(리서치·문서 작성) 쪽을 앞에
카드 = {id, kind, title, sub, action: {type: send(text, modes?) | open(reportId) | tables(docId, label) | view(view) | format(reportType) | pick}}
pick = 양식 고르기 창(문서 작성 시작). same 은 에셋(FE FEATURES.assets)을 끈 동안 쉰다(SAME_SHAPE).
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.agent.modes import has_doc
from app.agent.template import report_type
from app.db import ReportSession, ResearchTable, Task, User, scope_ids
from app.docs.store import document_cards
from app.drive import hidden_items

KST = timezone(timedelta(hours=9))
SAME_SHAPE = False  # 같은 모양 표 카드 — 에셋을 다시 켜면 True
DAYS = "월화수목금토일"


def _short(s: str, n: int = 34) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _first_ask(r: ReportSession) -> str:
    return next((m.get("text") or "" for m in (r.doc or {}).get("transcript") or [] if m.get("role") == "user" and (m.get("text") or "").strip() and not m.get("attachment")), "")


def _local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone(KST)


def start_cards(session: Session, row: ReportSession, user: User, limit: int = 4) -> List[Dict[str, Any]]:
    from app.db import Workspace
    from app.research.doc_tables import asset_hints
    from app.research.service import visible_templates

    ws_id = row.workspace_id
    now = datetime.now(KST)
    today = now.date().isoformat()
    cards: List[Dict[str, Any]] = []

    def add(kind: str, title: str, sub: str, action: Dict[str, Any]) -> None:
        if len(cards) < limit and not any(c["kind"] == kind for c in cards):
            cards.append({"id": f"{kind}{len(cards)}", "kind": kind, "title": _short(title), "sub": sub, "action": action})

    tasks = list(session.exec(select(Task).where(Task.workspace_id == ws_id, Task.assignee_id == user.id, Task.status != "done")))
    mine = [r for r in session.exec(select(ReportSession).where(ReportSession.workspace_id == ws_id, ReportSession.created_by == user.id)) if r.id != row.id]

    # 급한 것 — 할 일 마감·받은 검토 요청
    due = sorted((t for t in tasks if (t.source or {}).get("kind", "manual") == "manual" and t.due and t.due <= today), key=lambda t: t.due)
    if due:
        add("due", due[0].title, "기한 지남" if due[0].due < today else "오늘 마감", {"type": "view", "view": "tasks"})
    reports = {r.id: r for r in session.exec(select(ReportSession).where(ReportSession.workspace_id == ws_id))}
    asked = [t for t in tasks if (t.source or {}).get("kind") == "report" and (t.source or {}).get("reportId") in reports]
    if asked:
        r = reports[asked[0].source["reportId"]]
        add("review", f"'{r.title or '제목 없는 리포트'}' 검토", "검토 요청", {"type": "open", "reportId": r.id})

    # 하던 일 — 쓰다 만 내 문서
    unfinished = sorted((r for r in mine if has_doc(r.doc or {}) and 0 < r.written < len((r.doc or {}).get("sections") or [])), key=lambda r: r.updated_at, reverse=True)
    if unfinished:
        r = unfinished[0]
        add("continue", f"'{r.title or '제목 없는 리포트'}' 이어 쓰기", f"{r.written}/{len((r.doc or {}).get('sections') or [])} 섹션", {"type": "open", "reportId": r.id})

    # 같은 요일에 되풀이한 질문(다른 주 두 번 이상)
    weekday = now.weekday()
    groups: Dict[str, List[ReportSession]] = {}
    for r in mine:
        at = _local(r.created_at)
        if at.weekday() != weekday or at.date() == now.date() or (now - at).days > 35:
            continue
        ask = _first_ask(r)
        key = re.sub(r"[\d\s]+", "", ask)[:14]
        if key:
            groups.setdefault(key, []).append(r)
    routine = max((g for g in groups.values() if len({_local(r.created_at).isocalendar()[1] for r in g}) >= 2), key=len, default=None)
    if routine:
        last = max(routine, key=lambda r: r.created_at)
        add("routine", _first_ask(last), f"매주 {DAYS[weekday]}요일", {"type": "send", "text": _first_ask(last), "modes": (last.doc or {}).get("modes")})

    # 새 자료 — 같은 모양 표가 있는 것 먼저, 아니면 요약
    ws = session.get(Workspace, ws_id)
    hidden = hidden_items(session, ws_id, user.id)
    cards_docs = [c for c in document_cards([d for d in scope_ids(ws) if d not in hidden])] if ws is not None else []
    fresh = sorted((c for c in cards_docs if c.get("createdAt") and (now - datetime.fromisoformat(str(c["createdAt"]).replace("Z", "+00:00")).astimezone(KST)).days <= 14), key=lambda c: c["createdAt"], reverse=True)
    if fresh:
        hints = asset_hints(session, ws_id, user, [c["id"] for c in fresh[:8]])
        hit = next((c for c in fresh[:8] if (hints.get(c["id"]) or {}).get("similar")), None) if SAME_SHAPE else None
        if hit:
            add("same", f"'{hit['label']}' 같은 모양 표 {hints[hit['id']]['similar']}개", "새 자료", {"type": "tables", "docId": hit["id"], "label": hit["label"]})

    # 자주 하는 일 — 표 양식(최근 30일 두 번 이상), 문서 양식(두 번 이상)
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
    used = [t for t in session.exec(select(ResearchTable).where(ResearchTable.workspace_id == ws_id, ResearchTable.created_by == user.id, ResearchTable.created_at >= since)) if (t.kind or "table") == "table" and (t.data or {}).get("templateId")]
    top = Counter((t.data or {})["templateId"] for t in used).most_common(1)
    if top and top[0][1] >= 2:
        names = {x["id"]: x["name"] for x in visible_templates(session, ws_id, user.id)}
        tid, n = top[0]
        if tid in names:
            last = max((t for t in used if t.data["templateId"] == tid), key=lambda t: t.created_at)
            rows = "·".join(s["label"] for s in (last.data or {}).get("subjects") or [])[:40]
            add("template", f"{rows} {names[tid]}".strip(), f"최근 {n}번", {"type": "send", "text": f"{rows} {names[tid]} 최신 기간으로 만들어줘".strip(), "modes": {"research": True}})
    fmt = Counter(r.report_type for r in mine if has_doc(r.doc or {}) and r.report_type and r.report_type != "free").most_common(1)
    if fmt and fmt[0][1] >= 2:
        title = report_type(fmt[0][0])["title"]
        add("format", f"'{title}' 새 문서", "자주 쓰는 양식", {"type": "format", "reportType": fmt[0][0]})
    new3 = [c for c in fresh if (now - datetime.fromisoformat(str(c["createdAt"]).replace("Z", "+00:00")).astimezone(KST)).days <= 3]
    if new3:
        add("new", f"'{new3[0]['label']}' 핵심 요약", "새 자료", {"type": "send", "text": f"'{new3[0]['label']}' 자료의 핵심 내용을 요약해줘", "modes": {"research": True}})

    # 기본 — 평소 많이 켠 모드 쪽을 앞에
    modes = Counter(k for r in mine for k, v in ((r.doc or {}).get("modes") or {}).items() if v)
    defaults = [
        ("d_research", "자료 핵심 요약", "리서치", {"type": "send", "text": "이 작업 데이터의 핵심 내용을 요약해줘", "modes": {"research": True}}),
        ("d_peer", "Peer 비교표 만들기", "리서치", {"type": "send", "text": "Peer 비교표 만들어줘", "modes": {"research": True}}),
        ("d_writing", "문서 쓰기 시작", "문서 작성", {"type": "pick"}),
        ("d_numbers", "주요 수치 표로 정리", "리서치", {"type": "send", "text": "이 작업 데이터의 주요 재무 수치를 기간별 표로 정리해줘", "modes": {"research": True}}),
    ]
    if modes.get("writing", 0) > modes.get("research", 0):
        defaults.insert(0, defaults.pop(2))
    for kind, title, sub, action in defaults:
        add(kind, title, sub, action)
    return cards


__all__ = ["start_cards"]
