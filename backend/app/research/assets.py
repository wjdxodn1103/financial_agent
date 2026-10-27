"""에셋(리서치 표·차트) 찾기 — 드라이브 ▸ 에셋 화면과 AI 의 find_items 가 같은 규칙을 쓴다.

보이는 것: 내가 만든 것 전부(자동으로 '내 에셋') + 남이 공유한(saved) 것 중 내가 볼 수 있는 폴더에 있는 것.
질의: parse_query 가 종류(표·차트)·범위(내 것·공유)·날짜(오늘·어제·이번 주·지난주·이번 달·지난달·최근 n일)를 떼고 군말을 뺀다.
순위: 모든 낱말이 맞은 것 → 점수(제목 5, 양식 이름 3, 행·열·계열 3, 기간 2, 출처 자료 1, 만든 사람 1) → 최근.
낱말은 entities.norm 으로 맞추고 끝 조사를 뗀다. 붙여 쓴 질의('반도체peer')도 이어 붙인 필드에서 맞춘다.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app.auth import display_name
from app.db import ReportSession, Repo, ResearchTable, User, iso
from app.docs.store import doc_label, load_meta
from app.drive import hidden_items
from app.research.entities import norm

KST = timezone(timedelta(hours=9))
_FILLER = {
    "찾아줘", "찾아", "줘", "보여줘", "보여", "열어줘", "열어", "가져와", "가져와줘", "만든", "만들었던", "만들어둔", "만들어", "저번에", "저번", "아까", "예전에", "전에",
    "우리", "그", "그거", "관련", "관련된", "거", "것", "좀", "있던", "했던", "에셋", "자료",
}
_PARTICLE = re.compile(r"(으로|에서|이랑|하고|까지|부터|은|는|이|가|을|를|의|에|로|과|와|도|랑)$")
_KIND = {"표": "table", "테이블": "table", "차트": "chart", "그래프": "chart", "그림": "chart", "메모": "note", "노트": "note"}
_MINE = {"내", "내가", "제가", "내것", "내거", "나만"}
_SHARED = {"공유", "공유된", "공유한", "팀", "남이"}


def _strip(word: str) -> str:
    return _PARTICLE.sub("", word) if len(word) > 2 else word


def parse_query(q: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """→ {terms:[낱말], kind?, scope?, since?, until?(UTC naive), label?(사람이 읽는 조건)}."""
    now = (now or datetime.now(KST)).astimezone(KST)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    text = " " + (q or "").strip() + " "
    out: Dict[str, Any] = {}
    dates = [
        (r"\s오늘\s", day0, None, "오늘"),
        (r"\s어제\s", day0 - timedelta(days=1), day0, "어제"),
        (r"\s(이번\s?주|금주)\s", day0 - timedelta(days=day0.weekday()), None, "이번 주"),
        (r"\s(지난\s?주|저번\s?주)\s", day0 - timedelta(days=day0.weekday() + 7), day0 - timedelta(days=day0.weekday()), "지난주"),
        (r"\s이번\s?달\s", day0.replace(day=1), None, "이번 달"),
        (r"\s(지난\s?달|저번\s?달)\s", (day0.replace(day=1) - timedelta(days=1)).replace(day=1), day0.replace(day=1), "지난달"),
    ]
    for rx, since, until, label in dates:
        if re.search(rx, text):
            text = re.sub(rx, " ", text)
            out.update({"since": since, "until": until, "dateLabel": label})
            break
    m = re.search(r"\s최근\s?(\d{1,3})\s?일\s", text)
    if m:
        out.update({"since": day0 - timedelta(days=int(m.group(1)) - 1), "until": None, "dateLabel": f"최근 {m.group(1)}일"})
        text = text.replace(m.group(0), " ")
    terms: List[str] = []
    for raw in text.split():
        w = raw.strip(".,?!'\"")
        base = _strip(w)
        kind = _KIND.get(w) or _KIND.get(base) or _KIND.get(_PARTICLE.sub("", w))  # '표를'·'차트는'
        if kind:
            out["kind"] = kind
        elif base in _MINE or w in _MINE:
            out["scope"] = "mine"
        elif base in _SHARED or w in _SHARED:
            out["scope"] = "shared"
        elif w in _FILLER or base in _FILLER:
            continue
        elif norm(base):
            terms.append(norm(base))
    out["terms"] = terms
    for k in ("since", "until"):  # 저장 시각(UTC naive)과 비교
        if out.get(k) is not None:
            out[k] = out[k].astimezone(timezone.utc).replace(tzinfo=None)
    return out


def visible_assets(session: Session, workspace_id: str, user: User) -> List[ResearchTable]:
    rows = session.exec(select(ResearchTable).where(ResearchTable.workspace_id == workspace_id, (ResearchTable.created_by == user.id) | (ResearchTable.saved == True))).all()  # noqa: E712
    hidden = hidden_items(session, workspace_id, user.id)
    return [r for r in rows if r.created_by == user.id or r.id not in hidden]


def _fields(row: ResearchTable, names: Dict[str, str], templates: Dict[str, str], sources: Dict[str, str]) -> List[Tuple[str, int]]:
    data = row.data or {}
    if row.kind == "chart":
        labels = [*(data.get("categories") or []), *[s.get("name") or "" for s in data.get("series") or []]]
        docs = data.get("docIds") or []
        src = sources.get((data.get("chart") or {}).get("source") or "", "")
    elif row.kind == "note":
        labels = [(data.get("question") or ""), (data.get("text") or "")[:2000]]
        docs = list(dict.fromkeys(c.get("docId") for c in data.get("cites") or [] if c.get("docId")))
        src = ""
    else:
        labels = [*[s.get("label") or "" for s in data.get("subjects") or []], *[it.get("label") or "" for it in data.get("items") or [] if not it.get("hidden")]]
        docs = list(dict.fromkeys(c.get("docId") for r in data.get("cells") or [] for c in (r or {}).values() if c.get("docId")))
        src = ""
    return [
        (row.title, 5),
        (templates.get(data.get("templateId") or "", ""), 3),
        (src, 3),
        (" ".join(labels), 3),
        ((data.get("period") or {}).get("label") or "", 2),
        (" ".join(doc_label(load_meta(d), d) for d in docs[:12]), 1),
        (names.get(row.created_by, ""), 1),
    ]


def search_assets(session: Session, workspace_id: str, user: User, q: str = "", kind: Optional[str] = None, scope: Optional[str] = None, limit: int = 200, min_weight: int = 1) -> Tuple[List[ResearchTable], Dict[str, Any]]:
    """→ (순서대로 에셋, 해석한 조건). kind·scope 인자는 질의에서 읽은 것보다 앞선다.
    min_weight=2 면 출처 자료·만든 사람으로만 맞은 것은 뺀다(통합 검색·AI 찾기 — 자료 이름을 찾는데 그 자료로 만든 에셋이 다 끼지 않게)."""
    from app.research.service import visible_templates

    parsed = parse_query(q)
    kind = kind or parsed.get("kind")
    scope = scope or parsed.get("scope")
    rows = visible_assets(session, workspace_id, user)
    if kind in ("table", "chart", "note"):
        rows = [r for r in rows if (r.kind or "table") == kind]
    if scope == "mine":
        rows = [r for r in rows if r.created_by == user.id]
    elif scope == "shared":
        rows = [r for r in rows if r.saved]
    if parsed.get("since") is not None:
        rows = [r for r in rows if r.created_at >= parsed["since"]]
    if parsed.get("until") is not None:
        rows = [r for r in rows if r.created_at < parsed["until"]]
    terms = parsed["terms"]
    if not terms:
        return sorted(rows, key=lambda r: r.updated_at, reverse=True)[:limit], parsed
    names = {u.id: display_name(u) for u in Repo(session).users()}
    templates = {t["id"]: t["name"] for t in visible_templates(session, workspace_id, user.id)}
    sources = {r.id: r.title for r in rows if (r.kind or "table") == "table"}
    joined_q = "".join(terms)
    scored = []
    for r in rows:
        fields = [(norm(text), w) for text, w in _fields(r, names, templates, sources) if text and w >= min_weight]
        hit = 0
        score = 0
        for t in terms:
            ws = [w for text, w in fields if t in text]
            if ws:
                hit += 1
                score += max(ws)
        if len(terms) > 1 and any(joined_q in text for text, _w in fields):  # 붙여 쓴 질의
            score += 2
            hit = len(terms)
        if hit:
            scored.append((hit == len(terms), score, r.updated_at, r))
    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return [x[3] for x in scored][:limit], parsed


def asset_item(session: Session, row: ResearchTable, user: User, names: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """목록 한 줄(가벼운 모양) — 미리보기는 /research/tables/{id} 로 따로 연다."""
    data = row.data or {}
    task = session.get(ReportSession, row.chat_id) if row.chat_id else None
    if row.kind == "chart":
        src = session.get(ResearchTable, (data.get("chart") or {}).get("source") or "")
        shape = {"chartType": (data.get("chart") or {}).get("type") or "bar", "rows": len(data.get("categories") or []), "cols": len(data.get("series") or []), "sourceTitle": src.title if src else None}
    elif row.kind == "note":
        shape = {"rows": 0, "cols": 0, "cites": len(data.get("cites") or [])}
    else:
        rows, cols = len(data.get("subjects") or []), len([it for it in data.get("items") or [] if not it.get("hidden")])
        # 보이는 방향대로(지표가 행인 표는 뒤집어 센다)
        shape = {"rows": cols, "cols": rows} if (data.get("spec") or {}).get("orientation") == "items_as_rows" else {"rows": rows, "cols": cols}
    return {
        "id": row.id,
        "kind": row.kind or "table",
        "title": row.title,
        "status": row.status,
        "saved": row.saved,
        "mine": row.created_by == user.id,
        "createdBy": (names or {}).get(row.created_by) or row.created_by,
        "createdAt": iso(row.created_at),
        "updatedAt": iso(row.updated_at),
        "period": (data.get("period") or {}).get("label"),
        # 이 에셋을 만든 내 AI 작업(있으면 거기서 연다)
        "taskId": task.id if task is not None and task.created_by == user.id else None,
        # 올린 문서에서 꺼낸 표면 그 문서
        "sourceDoc": ((data.get("source") or {}).get("docLabel")) or None,
        **shape,
    }


__all__ = ["asset_item", "parse_query", "search_assets", "visible_assets"]
