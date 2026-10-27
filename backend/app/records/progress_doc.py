"""경과 문서(DOCX) — 워크스페이스에서 무엇을 정했고 누가 무엇을 했는지 날짜순으로 묶는다. **LLM 없이 코드로**.

재료(전부 DB·자료 메타에 이미 있는 것): 확정된 팀 기록(원문 인용·발언자·확인자) · 바뀐 결정(superseded) · 검수(지적 수·재검수 해소) ·
자료 올림·새 판 · 리포트 검토 요청 · 작업 항목(상태·담당·기한). 인수인계·보고용 — "왜 이 숫자인가"를 원문으로 따라갈 수 있게.
보낼 곳(sink) 자리: 지금은 DOCX 내려받기. 사내 문서함·결재 첨부는 이 함수의 출력을 넘기면 된다.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from sqlmodel import Session, select

from app.auth import ROLE_KO, require_member
from app.db import ChannelMessage, DocVersion, IngestJob, Membership, ReportSession, Review, Task, TeamRecord, User, utcnow
from app.docs.store import doc_label, load_meta
from app.records.service import RECORD_TYPES
from app.review.rules import RULE_KO
from app.scheduler import local_tz

_FONT = "맑은 고딕"
_GRAY = RGBColor(0x60, 0x60, 0x60)
_WEEK = "월화수목금토일"
TASK_KO = {"todo": "할 일", "doing": "진행", "review": "검토", "done": "완료"}


def _local(dt: Optional[datetime]) -> Optional[datetime]:
    return dt.replace(tzinfo=timezone.utc).astimezone(local_tz()) if dt else None


def _hm(dt: Optional[datetime]) -> str:
    d = _local(dt)
    return d.strftime("%m.%d %H:%M") if d else ""


def _day(dt: datetime) -> str:
    d = _local(dt)
    assert d is not None
    return f"{d.strftime('%Y-%m-%d')} ({_WEEK[d.weekday()]})"


def _iso_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.rstrip("Z"))
    except ValueError:
        return None


def _quote_line(q: Dict[str, Any]) -> str:
    return f"{q.get('author') or ''} ({_hm(_iso_dt(q.get('at')))}): “{q.get('text') or ''}”"


def collect(session: Session, workspace_id: str) -> Dict[str, Any]:
    """문서에 넣을 것을 모은다(화면 미리보기에도 쓸 수 있게 dict 로)."""
    names = {u.id: f"{u.name} {u.title}".strip() for u in session.exec(select(User)).all()}
    recs = list(session.exec(select(TeamRecord).where(TeamRecord.workspace_id == workspace_id)).all())
    tasks = list(session.exec(select(Task).where(Task.workspace_id == workspace_id)).all())
    task_of_record = {(t.source or {}).get("recordId"): t for t in tasks if (t.source or {}).get("recordId")}
    events: List[Tuple[datetime, str, str]] = []  # (시각, 종류, 한 줄)

    for r in recs:
        if r.status in ("confirmed", "superseded") and r.confirmed_at:
            how = "충돌 값 채택" if (r.source or {}).get("card") == "ledger_choice" else ("직접 남김" if (r.source or {}).get("kind") == "manual" else "기록 비서 후보 확인")
            events.append((r.confirmed_at, RECORD_TYPES.get(r.type, r.type), f"{r.text} — {how}, 확인 {names.get(r.confirmed_by or '', '')}"))
    for v in session.exec(select(Review).where(Review.workspace_id == workspace_id, Review.status == "done")).all():
        c = (v.summary or {}).get("counts") or {}
        n = sum(c.get(k, 0) for k in ("mismatch", "calc", "unsourced", "internal"))
        line = f"'{doc_label(load_meta(v.doc_id), v.doc_id)}' 검수 — 지적 {n}건(" + ", ".join(f"{RULE_KO[k]} {c.get(k, 0)}" for k in ("mismatch", "calc", "unsourced", "internal") if c.get(k)) + f"), {names.get(v.created_by, '')}"
        carry = (v.summary or {}).get("carry")
        if carry:
            line += f" · 앞선 검수 대비 해소 {len(carry.get('resolved') or [])} · 남음 {len(carry.get('carried') or [])}"
        if v.finished_at:
            events.append((v.finished_at, "검수", line))
    versions = {r.doc_id: r for r in session.exec(select(DocVersion).where(DocVersion.workspace_id == workspace_id)).all()}
    for j in session.exec(select(IngestJob).where(IngestJob.workspace_id == workspace_id, IngestJob.status == "done")).all():
        if not j.doc_id:
            continue
        v = versions.get(j.doc_id)
        if j.replaces and v and v.version > 1:
            events.append((j.created_at, "자료", f"'{doc_label(load_meta(j.replaces), j.replaces)}' 새 판(v{v.version}) 올림 — {j.file_name}, {names.get(j.uploaded_by, '')}"))
        else:
            events.append((j.created_at, "자료", f"'{doc_label(load_meta(j.doc_id), j.doc_id)}' 올림 — {j.file_name}, {names.get(j.uploaded_by, '')}"))
    for m in session.exec(select(ChannelMessage).where(ChannelMessage.workspace_id == workspace_id, ChannelMessage.kind == "system")).all():
        events.append((m.created_at, "알림", m.text.split("\n")[0]))
    for t in tasks:
        if t.status == "done":
            auto = " (재검수에서 자동 완료)" if "자동 완료" in (t.detail or "") else ""
            events.append((t.updated_at, "작업 완료", f"{t.title} — 담당 {names.get(t.assignee_id or '', '없음')}{auto}"))
    events.sort(key=lambda e: e[0])

    def rec_view(r: TeamRecord) -> Dict[str, Any]:
        t = task_of_record.get(r.id)
        return {"type": RECORD_TYPES.get(r.type, r.type), "text": r.text, "scope": r.scope, "quotes": [_quote_line(q) for q in (r.quotes or [])], "confirmedBy": names.get(r.confirmed_by or "", ""), "at": _hm(r.confirmed_at or r.created_at), "task": f"{TASK_KO.get(t.status, t.status)} · 담당 {names.get(t.assignee_id or '', '없음')}" if t else ""}

    confirmed = [r for r in recs if r.status == "confirmed"]
    order = lambda r: r.confirmed_at or r.created_at  # noqa: E731
    return {
        "decisions": [rec_view(r) for r in sorted((r for r in confirmed if r.type in ("decision", "convention")), key=order)],
        "directives": [rec_view(r) for r in sorted((r for r in confirmed if r.type in ("directive", "todo")), key=order)],
        "questions": [rec_view(r) for r in sorted((r for r in confirmed if r.type == "question"), key=order)],
        "superseded": [rec_view(r) for r in sorted((r for r in recs if r.status == "superseded"), key=order)],
        "events": events,
        "open": [{"title": t.title, "status": TASK_KO.get(t.status, t.status), "assignee": names.get(t.assignee_id or "", "없음"), "due": t.due} for t in sorted(tasks, key=lambda t: (t.due or "9999", t.created_at)) if t.status != "done"],
        "taskCounts": {k: sum(1 for t in tasks if t.status == k) for k in TASK_KO},
        "reports": [{"title": r.title or "제목 없는 리포트", "written": r.written, "sections": len((r.doc or {}).get("sections") or []), "by": names.get(r.created_by, "")} for r in session.exec(select(ReportSession).where(ReportSession.workspace_id == workspace_id)).all()],
    }


def _run(p: Any, text: str, size: float = 10, bold: bool = False, color: Optional[RGBColor] = None) -> None:
    r = p.add_run(text)
    r.font.name = _FONT
    r._element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)
    r.font.size = Pt(size)
    r.bold = bold
    if color is not None:
        r.font.color.rgb = color


def _records(d: Any, items: List[Dict[str, Any]], empty: str) -> None:
    if not items:
        _run(d.add_paragraph(), empty, 9.5, color=_GRAY)
        return
    for it in items:
        p = d.add_paragraph(style="List Bullet")
        _run(p, f"[{it['type']}] ", 10, bold=True)
        _run(p, it["text"])
        meta = " · ".join(x for x in (f"범위 {it['scope']}" if it["scope"] else "", f"확인 {it['confirmedBy']} {it['at']}" if it["confirmedBy"] else it["at"], f"작업 {it['task']}" if it["task"] else "") if x)
        if meta:
            _run(p, f"  ({meta})", 9, color=_GRAY)
        for q in it["quotes"]:
            qp = d.add_paragraph()
            qp.paragraph_format.left_indent = Pt(24)
            _run(qp, f"원문 — {q}", 9, color=_GRAY)


def progress_docx(session: Session, workspace_id: str, user: User) -> Tuple[bytes, str]:
    ws, _m = require_member(session, workspace_id, user)
    data = collect(session, workspace_id)
    names = {u.id: (u.name, u.title) for u in session.exec(select(User)).all()}
    members = session.exec(select(Membership).where(Membership.workspace_id == workspace_id)).all()
    now = _local(utcnow())
    assert now is not None

    d = Document()
    st = d.styles["Normal"]
    st.font.name = _FONT
    st.element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)
    st.font.size = Pt(10)
    _run(d.add_paragraph(), f"작업 경과 — {ws.name}", 18, bold=True)
    sub = d.add_paragraph()
    _run(sub, f"{now.strftime('%Y-%m-%d %H:%M')} 기준 · 작성 {user.name} {user.title} · 멤버 " + ", ".join(f"{names.get(m.user_id, ('?', ''))[0]}({ROLE_KO.get(m.role, m.role)})" for m in members), 9, color=_GRAY)
    _run(d.add_paragraph(), "팀 기록·충돌 채택·검수·자료·작업 항목에서 코드로 모은 경과입니다(AI 요약 없음). 원문은 발언 그대로 옮겼습니다.", 9, color=_GRAY)

    d.add_heading("1. 한눈에", level=2)
    tc = data["taskCounts"]
    lines = [
        f"결정·방침 {len(data['decisions'])}건 · 지시·할 일 {len(data['directives'])}건 · 미결 질문 {len(data['questions'])}건 · 바뀐 결정 {len(data['superseded'])}건",
        "작업 항목: " + " · ".join(f"{TASK_KO[k]} {tc[k]}" for k in TASK_KO),
        f"자료 {len(ws.document_ids or [])}건(활성 판) · 리포트 " + (", ".join(f"'{r['title']}' 섹션 {r['written']}/{r['sections']}({r['by']})" for r in data["reports"]) or "없음"),
    ]
    for l in lines:
        _run(d.add_paragraph(style="List Bullet"), l)

    d.add_heading("2. 정한 것 — 결정·방침(현재 유효)", level=2)
    _records(d, data["decisions"], "아직 확정된 결정·방침이 없습니다.")
    if data["superseded"]:
        d.add_heading("바뀐 결정(이전 것)", level=3)
        _records(d, data["superseded"], "")
    d.add_heading("3. 맡긴 것 — 지시·할 일", level=2)
    _records(d, data["directives"], "확정된 지시·할 일이 없습니다.")
    d.add_heading("4. 아직 답이 없는 것 — 미결 질문", level=2)
    _records(d, data["questions"], "미결 질문이 없습니다.")

    d.add_heading("5. 날짜별 경과", level=2)
    if not data["events"]:
        _run(d.add_paragraph(), "기록된 경과가 없습니다.", 9.5, color=_GRAY)
    day = ""
    for at, kind, line in data["events"]:
        if _day(at) != day:
            day = _day(at)
            _run(d.add_paragraph(), day, 10.5, bold=True)
        p = d.add_paragraph(style="List Bullet")
        _run(p, f"{_hm(at)[-5:]}  [{kind}] ", 9.5, bold=True)
        _run(p, line, 9.5)

    d.add_heading("6. 남은 작업", level=2)
    if not data["open"]:
        _run(d.add_paragraph(), "남은 작업이 없습니다.", 9.5, color=_GRAY)
    else:
        t = d.add_table(rows=1, cols=4)
        t.style = "Table Grid"
        for i, h in enumerate(("작업", "상태", "담당", "기한")):
            t.rows[0].cells[i].text = h
        for o in data["open"]:
            cells = t.add_row().cells
            cells[0].text, cells[1].text, cells[2].text, cells[3].text = o["title"], o["status"], o["assignee"], o["due"] or ""

    buf = io.BytesIO()
    d.save(buf)
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", ws.name).strip("_")[:40] or "workspace"
    return buf.getvalue(), f"{safe}_작업경과_{now.strftime('%Y%m%d')}.docx"


__all__ = ["collect", "progress_docx"]
