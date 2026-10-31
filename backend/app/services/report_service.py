"""리포트 세션 수명주기 + 한 턴 SSE 중계 — OP `service/paper_chat_service.py` 의 구조 그대로.

 - SSE 이벤트: status / meta / text / text_replace / tool_start / tool_end / section_update / outline_update / approval /
   plan_update / suggestions / setup_update / error / done. 원고가 바뀌는 이벤트에는 BE 가 조립한 `report`(뷰)를 동봉한다.
 - 상류 읽기는 producer task + asyncio.Queue 로 돈다. 15초 무응답이면 ": ping".
 - 세션당 한 턴(잠금). 첫 바이트 전에 알 수 있는 오류(세션 없음·키 없음·세션 사용 중)는 HTTP 로 낸다.
 - **요청 세션(DB)을 스트림에 끌고 가지 않는다** — producer 는 짧은 세션으로 읽고 저장한다(OP 2026-09-18 풀 고갈 사고).
 - **커밋된 row.doc 를 제자리에서 고치지 않는다** — deepcopy 후 새 dict 를 대입해야 UPDATE 가 나간다.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request
from sqlmodel import Session

from app.agent.loop import humanize_error, run_turn, suggestions_for
from app.agent.modes import has_doc, normalize as normalize_modes
from app.agent.session import find_section, log_section, new_doc, new_section_id, public_session, restore_version, save_version, seed_sections, set_section, written_sections
from app.agent.template import DEFAULT_TYPE, REGISTERED, known_type, match_item, public_types
from app.auth import ROLE_RANK, require_member
from app import usage
from app.notify import notify
from app.db import ChannelMessage, Repo, ReportSession, Task, User, Workspace, company_ids, engine, iso, utcnow
from app.docs.store import document_cards
from app.drive import clean_scope, folders_of, place, report_scope_ids, scope_view, visible_folders
from app.ids import id36, now_iso
from app.llm.base import LlmError
from app.llm.client import ReportLlm, provider_info
from app.ledger.service import ledger_for
from app.report.number_check import number_report
from app.report.readiness import KIND_KO, readiness, summary_line
from app.report.view import build_report_view

logger = logging.getLogger(__name__)

PING_INTERVAL_SEC = 15.0
DISCONNECT_POLL_SEC = 2.0
TURN_WALLCLOCK_SEC = 30 * 60
_busy: set[str] = set()
_tasks: Dict[str, "asyncio.Task[None]"] = {}
_REPORT_EVENTS = frozenset({"section_update", "outline_update", "setup_update"})


def sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class EventStream:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()

    def emit(self, event: Dict[str, Any]) -> None:
        self.queue.put_nowait(event)

    def close(self) -> None:
        self.queue.put_nowait(None)


def try_lock(session_id: str) -> bool:
    if session_id in _busy:
        return False
    _busy.add(session_id)
    return True


def release_lock(session_id: str) -> None:
    _busy.discard(session_id)


class ReportService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = Repo(session)

    # ── 메타 ────────────────────────────────────────────────────────────
    @staticmethod
    def meta() -> Dict[str, Any]:
        return {"reportTypes": public_types(), "defaultType": DEFAULT_TYPE, "provider": provider_info()}

    # ── 세션 ────────────────────────────────────────────────────────────
    def row_or_404(self, session_id: str) -> ReportSession:
        row = self.repo.get(session_id)
        if row is None:
            raise HTTPException(404, "리포트 세션이 없습니다.")
        return row

    def access(self, session_id: str, user: User, *, write: bool = False) -> ReportSession:
        """리포트를 볼 수 있는가(워크스페이스 멤버), 쓸 수 있는가(작성자 — 에이전트 대화는 작성자 것이다)."""
        row = self.row_or_404(session_id)
        _ws, m = require_member(self.session, row.workspace_id, user)
        if write and row.created_by != user.id:
            raise HTTPException(403, "이 리포트는 작성자만 고칠 수 있습니다. 의견은 채널이나 검수로 남겨 주세요.")
        if write and ROLE_RANK.get(m.role, 0) < ROLE_RANK["editor"]:
            raise HTTPException(403, "리포트를 고치려면 편집자 이상 역할이 필요합니다.")
        return row

    def create(self, workspace_id: str, user: User, title: str = "", report_type: str = DEFAULT_TYPE, folder_id: Optional[str] = None, data_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """새 문서 — folder_id = 드라이브 자리(나에게 보이는 폴더), data_scope = 참고 데이터(default 워크스페이스 기본값 | custom 고른 데이터·폴더)."""
        ws, _m = require_member(self.session, workspace_id, user, "editor")
        rtype = report_type if known_type(report_type) else DEFAULT_TYPE
        if rtype.startswith(REGISTERED):
            from app.templates_import.registry import can_use

            if not can_use(self.session, rtype, ws.id, user.id):
                raise HTTPException(404, "양식이 없습니다.")
        if folder_id and folder_id not in visible_folders(folders_of(self.session, ws.id), user.id):
            raise HTTPException(404, "폴더가 없습니다.")
        sid = id36("r", 4)
        doc = new_doc(sid, rtype, title.strip())
        doc["dataScope"] = clean_scope(self.session, ws, data_scope)
        doc["documentIds"] = report_scope_ids(self.session, ws, doc, user.id)
        row = ReportSession(id=sid, workspace_id=ws.id, created_by=user.id, title=doc["setup"]["title"], report_type=rtype, written=0, doc=doc)
        self.repo.save(row)
        if folder_id:
            place(self.session, ws.id, sid, "doc", folder_id)
        self.repo.save(ws)  # 최근 활동 순서
        return self.payload(row, user)

    def list(self, workspace_id: str, user: User) -> List[Dict[str, Any]]:
        require_member(self.session, workspace_id, user)
        return [
            {
                "id": r.id,
                "title": r.title or ("제목 없는 리포트" if has_doc(r.doc or {}) else "새 작업"),
                "reportType": r.report_type,
                "written": r.written,
                "sections": len((r.doc or {}).get("sections") or []),
                "createdBy": r.created_by,
                "updatedAt": iso(r.updated_at),
                "hasDoc": has_doc(r.doc or {}),
                # 아직 아무것도 안 한 작업(대화·문서 없음) — 'AI 작업'을 누르면 새로 만들지 않고 이것을 연다, 불러오기 목록에서는 뺀다
                "empty": not has_doc(r.doc or {}) and not (r.doc or {}).get("transcript"),
            }
            for r in self.repo.reports(workspace_id)
        ]

    def get_payload(self, session_id: str, user: User) -> Dict[str, Any]:
        return self.payload(self.access(session_id, user), user)

    def delete(self, session_id: str, user: User) -> None:
        row = self.row_or_404(session_id)
        _ws, m = require_member(self.session, row.workspace_id, user)
        if row.created_by != user.id and m.role != "owner":
            raise HTTPException(403, "리포트는 작성자나 워크스페이스 소유자만 지울 수 있습니다.")
        if session_id in _busy:
            raise HTTPException(409, "이 세션에서 아직 앞선 요청을 처리하고 있습니다.")
        place(self.session, row.workspace_id, row.id, "doc", None)  # 드라이브 자리도 치운다
        self.repo.delete(row)

    def patch(self, session_id: str, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        """화면 편집 — 한 번에 한 가지(OP PATCH 분기와 같은 규칙: {step} 만 오면 400, 비우려면 content: null)."""
        row = self.access(session_id, user, write=True)
        if session_id in _busy:
            raise HTTPException(409, "이 세션에서 아직 앞선 요청을 처리하고 있습니다.")
        doc = copy.deepcopy(row.doc)
        sections: List[Dict[str, Any]] = list(doc.get("sections") or [])
        if body.get("reportType") is not None:
            rtype = str(body["reportType"])
            if not known_type(rtype):
                raise HTTPException(400, "모르는 리포트 유형입니다.")
            if rtype.startswith(REGISTERED):
                from app.templates_import.registry import can_use

                if not can_use(self.session, rtype, row.workspace_id, user.id):
                    raise HTTPException(404, "양식이 없습니다.")
            if written_sections(doc):
                raise HTTPException(409, "이미 쓴 섹션이 있어 유형을 바꿀 수 없습니다. 새 리포트를 만들어 주세요.")
            doc["reportType"] = rtype
            seed_sections(doc)
            doc.pop("plan", None)
            doc.pop("pendingPlan", None)
        elif body.get("setup") is not None:
            setup = doc.setdefault("setup", {})
            for k in ("title", "subject", "asOf", "audience"):
                if k in body["setup"]:
                    setup[k] = str(body["setup"][k] or "").strip()
        elif body.get("data") is not None:
            # 이 작업 채팅에서 AI 가 참고할 데이터 고르기 — 이 문서의 범위 안에서 끄고 켠다(doc.dataExcluded)
            doc_id = str(body["data"].get("docId") or "")
            if doc_id not in report_scope_ids(self.session, self.repo.workspace(row.workspace_id), doc, row.created_by, apply_off=False):
                raise HTTPException(400, "이 문서가 쓰는 데이터가 아닙니다.")
            off = [d for d in doc.get("dataExcluded") or [] if d != doc_id]
            doc["dataExcluded"] = off if body["data"].get("use") else [*off, doc_id]
        elif body.get("dataScope") is not None:
            # 참고 데이터 범위 — 묶음(워크스페이스·사내·개인) + 고른 데이터(데이터 설정) | 옛 모양(기본값 / 고른 데이터·폴더)
            doc["dataScope"] = clean_scope(self.session, self.repo.workspace(row.workspace_id), body["dataScope"])  # type: ignore[arg-type]
            if "groups" in doc["dataScope"]:
                doc["dataExcluded"] = []  # 데이터 설정이 범위를 통째로 정한다 — 예전에 하나씩 끈 것은 푼다
        elif body.get("order") is not None:
            by_step = {s["step"]: s for s in sections}
            order = [str(x) for x in body["order"]]
            doc["sections"] = [by_step[s] for s in order if s in by_step] + [s for s in sections if s["step"] not in order]
        elif body.get("modes") is not None:
            # AI 작업 모드(하나씩) — 다음 턴부터 그 모드의 도구·프롬프트만. 문서 작성에서 다른 모드로 바꾸면 문서를 판으로(중간 저장)
            new = normalize_modes(body["modes"], doc)
            if normalize_modes(None, doc)["writing"] and not new["writing"] and written_sections(doc):
                save_version(doc, "중간 저장")
            doc["modes"] = new
        elif body.get("saveVersion") is not None:
            if not written_sections(doc):
                raise HTTPException(400, "아직 쓴 섹션이 없습니다.")
            save_version(doc, str(body["saveVersion"] or "").strip()[:30] or "저장")
        elif body.get("restoreVersion") is not None:
            if not restore_version(doc, str(body["restoreVersion"])):
                raise HTTPException(404, "그런 판이 없습니다.")
        elif body.get("attachTable") is not None:
            # 드라이브 ▸ 에셋에서 연 표·차트를 이 작업의 결과에 둔다(지금 보는 것)
            from app.research.service import ResearchService

            tid = str(body["attachTable"])
            if ResearchService(self.session).table_row(tid, user).workspace_id != row.workspace_id:
                raise HTTPException(400, "다른 워크스페이스의 표입니다.")
            if tid not in (doc.get("tableIds") or []):
                doc["tableIds"] = [*(doc.get("tableIds") or []), tid]
            doc["currentTableId"] = tid
        elif body.get("removeTable") is not None:
            # 섹션에 넣은 AI 채팅 표 빼기 — {step, id}
            sec = find_section(doc, str(body["removeTable"].get("step") or ""))
            if sec is None:
                raise HTTPException(400, "그런 섹션이 없습니다.")
            sec["tables"] = [t for t in sec.get("tables") or [] if t.get("id") != body["removeTable"].get("id")]
        elif body.get("remove") is not None:
            doc["sections"] = [s for s in sections if s["step"] != body["remove"]]
            (doc.get("evidence") or {}).pop(body["remove"], None)
        elif body.get("step") is not None and body.get("title") is not None:
            sec = find_section(doc, body["step"])
            if sec is None:
                raise HTTPException(400, "그런 섹션이 없습니다.")
            sec["title"] = str(body["title"]).strip() or sec["title"]
        elif body.get("step") is not None:
            if "content" not in body:
                raise HTTPException(400, "수정할 항목이 없습니다.")
            content = body.get("content")
            if set_section(doc, body["step"], content) is None:
                raise HTTPException(400, "그런 섹션이 없습니다.")
            log_section(doc, body["step"], "본문 되돌리기(비움)" if content is None else f"화면에서 본문 편집 · {len(content)}자")
            doc["lastWrittenStep"] = None if content is None else body["step"]
            if content is not None:
                from app.anchors import pin_section

                pin_section(doc, find_section(doc, body["step"]) or {})  # 사람이 고친 본문의 인용·숫자도 그 시점 원문으로
        else:
            raise HTTPException(400, "수정할 항목이 없습니다.")
        self.persist(row, doc)
        return self.payload(row, user)

    # ── DOCX 양식 ──────────────────────────────────────────────────────
    def set_template(self, session_id: str, user: User, src_path: str, file_name: str) -> Dict[str, Any]:
        """양식 등록 — 제목 문단이 섹션이 된다(아직 쓴 섹션이 없으면 목차를 양식으로 바꾸고, 있으면 제목이 같은 섹션은 두고 없는 제목만 더한다)."""
        import shutil

        from app.config import TEMPLATE_DIR
        from app.report.template_docx import TemplateError, parse_template

        row = self.access(session_id, user, write=True)
        if session_id in _busy:
            raise HTTPException(409, "작성 중에는 양식을 바꿀 수 없습니다.")
        from app.formats.registry import is_format

        if is_format((row.doc or {}).get("reportType")):
            raise HTTPException(400, "고정 양식 리포트는 섹션·표·그림이 양식으로 정해져 있어 DOCX 양식을 따로 등록하지 않습니다.")
        if (row.doc or {}).get("layout"):
            raise HTTPException(400, "샘플로 만든 문서 양식(장·소주제·표 양식)을 쓰는 문서라 DOCX 양식을 따로 등록하지 않습니다.")
        try:
            parsed = parse_template(src_path)
        except TemplateError as e:
            raise HTTPException(400, str(e)) from e
        dest = TEMPLATE_DIR / f"{session_id}.docx"
        shutil.copyfile(src_path, dest)
        doc = copy.deepcopy(row.doc)
        rtype = doc.get("reportType")
        sections: List[Dict[str, Any]] = list(doc.get("sections") or [])
        written = {s["title"].strip(): s for s in written_sections(doc)}
        new_sections = []
        for h in parsed["headings"]:
            keep = written.get(h["title"])
            if keep is not None:
                new_sections.append({**keep, "guide": h["guide"]})
                continue
            item = match_item(h["title"], rtype)
            new_sections.append({"step": new_section_id(), "title": h["title"], "status": "empty", "covers": [item["id"]] if item else [], "guide": h["guide"]})
        # 양식에 없는 이미 쓴 섹션은 버리지 않고 뒤에 둔다
        titles = {h["title"] for h in parsed["headings"]}
        new_sections += [s for s in sections if s.get("status") == "written" and s["title"].strip() not in titles]
        doc["sections"] = new_sections
        doc.pop("plan", None)
        doc.pop("pendingPlan", None)
        doc["template"] = {"name": file_name, "sections": len(parsed["headings"]), "uploadedAt": now_iso()}
        self.persist(row, doc)
        return self.payload(row, user)

    def remove_template(self, session_id: str, user: User) -> Dict[str, Any]:
        from app.config import TEMPLATE_DIR

        row = self.access(session_id, user, write=True)
        doc = copy.deepcopy(row.doc)
        doc.pop("template", None)
        try:
            (TEMPLATE_DIR / f"{session_id}.docx").unlink()
        except OSError:
            pass
        self.persist(row, doc)
        return self.payload(row, user)

    def export(self, session_id: str, user: User) -> Tuple[bytes, str]:
        """양식이 있으면 원본 양식에 채우고, 없으면 기본 DOCX."""
        import re as _re
        import time as _time

        from app.config import TEMPLATE_DIR
        from app.report.export import build_docx
        from app.report.template_docx import fill_template

        row = self.access(session_id, user)
        doc = self._current_scope(row)
        tpl = TEMPLATE_DIR / f"{session_id}.docx"
        if doc.get("template") and tpl.exists():
            title = str((doc.get("setup") or {}).get("title") or "report")
            safe = _re.sub(r'[\\/:*?"<>|]+', "_", title).strip() or "report"
            return fill_template(tpl, doc), f"{safe}_{_time.strftime('%Y%m%d')}.docx"
        return build_docx(doc)

    def _current_scope(self, row: ReportSession) -> Dict[str, Any]:
        """내보내기용 문서 — 화면(payload)과 같은 지금의 데이터 범위로(저장된 documentIds 는 마지막 턴 때 값이라, 그 뒤 올린 자료가 표·차트에서 빠졌다)."""
        doc = dict(row.doc or {})
        doc["documentIds"] = report_scope_ids(self.session, self.repo.workspace(row.workspace_id), doc, row.created_by)
        return doc

    def export_xlsx(self, session_id: str, user: User) -> Tuple[bytes, str]:
        """리포트의 표·그림 데이터(블록마다 시트 + 엑셀 막대 그래프) — 고정 양식의 표·그림과 넣은 AI 채팅 표."""
        from app.formats.registry import is_format
        from app.report.format_export import build_blocks_xlsx

        row = self.access(session_id, user)
        doc = self._current_scope(row)
        if not is_format(doc.get("reportType")) and not doc.get("layout") and not any(s.get("tables") for s in doc.get("sections") or []):
            raise HTTPException(400, "내려받을 표가 없습니다.")
        return build_blocks_xlsx(doc)

    def insert_table(self, session_id: str, user: User, table_id: str, step: str) -> Dict[str, Any]:
        """AI 채팅 표를 섹션 뒤에 넣는다 — 지금 표의 복사본(이후 표를 고쳐도 문서는 그대로). 계산 칸은 숫자 확인의 계산값 출처로 같이 둔다."""
        from app.research.block import table_entry
        from app.research.service import ResearchService

        row = self.access(session_id, user, write=True)
        if session_id in _busy:
            raise HTTPException(409, "이 세션에서 아직 앞선 요청을 처리하고 있습니다.")
        table = ResearchService(self.session).table_row(table_id, user)
        if table.workspace_id != row.workspace_id:
            raise HTTPException(400, "다른 워크스페이스의 표입니다.")
        if table.status != "done":
            raise HTTPException(409, "표를 아직 만드는 중입니다.")
        doc = copy.deepcopy(row.doc)
        sec = find_section(doc, step)
        if sec is None:
            raise HTTPException(400, "그런 섹션이 없습니다.")
        if table.kind == "note":
            note_into_section(doc, sec, table)
        else:
            sec["tables"] = [*(sec.get("tables") or []), table_entry(table)]
            log_section(doc, step, f"{'차트' if table.kind == 'chart' else '표'} 넣기: {table.title}")
        self.persist(row, doc)
        return self.payload(row, user)

    def add_note(self, session_id: str, user: User, msg_id: str) -> Dict[str, Any]:
        """대화의 답 하나 → 메모(에셋 kind=note) — 이 작업의 결과에 두고 지금 보는 것으로. 근거 자료가 아니다."""
        from app.db import ResearchTable
        from app.research.notes import note_data, note_title

        row = self.access(session_id, user, write=True)
        if session_id in _busy:
            raise HTTPException(409, "이 세션에서 아직 앞선 요청을 처리하고 있습니다.")
        doc = copy.deepcopy(row.doc)
        msgs = doc.get("transcript") or []
        i = next((k for k, m in enumerate(msgs) if m.get("id") == msg_id and m.get("role") == "assistant"), None)
        if i is None or not (msgs[i].get("text") or "").strip():
            raise HTTPException(404, "메모로 남길 답이 없습니다.")
        question = next((m.get("text") or "" for m in reversed(msgs[:i]) if m.get("role") == "user"), "")
        note = self.repo.save(ResearchTable(id=id36("rt", 4), workspace_id=row.workspace_id, chat_id=session_id, created_by=user.id, title=note_title(msgs[i]["text"], question), status="done", kind="note", data=note_data(msgs[i]["text"], question)))
        doc["tableIds"] = [*(doc.get("tableIds") or []), note.id]
        doc["currentTableId"] = note.id
        self.persist(row, doc)
        return self.payload(row, user)

    def add_chart(self, session_id: str, user: User, table_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """결과 패널의 '차트' — 표에서 차트 에셋을 만들어 이 작업의 결과에 둔다(지금 보는 것 = 새 차트)."""
        from app.research.service import ResearchService

        row = self.access(session_id, user, write=True)
        if session_id in _busy:
            raise HTTPException(409, "이 세션에서 아직 앞선 요청을 처리하고 있습니다.")
        chart = ResearchService(self.session).make_chart(table_id, user, body, chat_id=session_id)
        doc = copy.deepcopy(row.doc)
        doc["tableIds"] = [*(doc.get("tableIds") or []), chart.id]
        doc["currentTableId"] = chart.id
        self.persist(row, doc)
        return self.payload(row, user)

    # ── 검토 준비 · 검토 요청 ──────────────────────────────────────────
    def readiness(self, session_id: str, user: User) -> Dict[str, Any]:
        """코드 점검표 + 섹션별 충돌 카드(멤버 누구나 본다). 채택은 원장 API(편집자 이상), 검토 요청은 작성자만."""
        row = self.access(session_id, user)
        _ws, m = require_member(self.session, row.workspace_id, user)
        r = readiness(row.doc or {}, ledger_for(self.session, row.workspace_id))
        req = (row.doc or {}).get("reviewRequest")
        if req:
            t = self.session.get(Task, req.get("taskId") or "")
            req = {**req, "taskStatus": t.status if t else None}
        return {**r, "reviewRequest": req, "canChoose": ROLE_RANK.get(m.role, 0) >= ROLE_RANK["editor"], "canRequest": row.created_by == user.id}

    # ── 숫자별 확인 ────────────────────────────────────────────────────
    def numbers(self, session_id: str, user: User) -> Dict[str, Any]:
        """본문 숫자마다 출처 판정 + 사람 확인 표시. 확인은 검토자 이상(작성자 포함)."""
        row = self.access(session_id, user)
        _ws, m = require_member(self.session, row.workspace_id, user)
        names = {u.id: f"{u.name} {u.title}".strip() for u in self.repo.users()}
        out = number_report(row.doc or {}, ledger_for(self.session, row.workspace_id), names)
        return {**out, "canConfirm": ROLE_RANK.get(m.role, 0) >= ROLE_RANK["reviewer"]}

    def confirm_number(self, session_id: str, user: User, key: str, confirmed: bool, note: str = "", raw: str = "") -> Dict[str, Any]:
        """사람 확인 표시 — 막지 않고 남긴다(확인한 사람·시각·메모·그때 판정). 문장이 바뀌면 key 가 바뀌어 다시 확인한다.
        raw = 화면이 보여 준 숫자 표기 — 다르면 거절(오래된 화면이 다른 숫자에 확인을 남기지 않게)."""
        row = self.access(session_id, user)
        require_member(self.session, row.workspace_id, user, "reviewer")
        if session_id in _busy:
            raise HTTPException(409, "이 세션에서 아직 앞선 요청을 처리하고 있습니다.")
        doc = copy.deepcopy(row.doc or {})
        current = number_report(doc, ledger_for(self.session, row.workspace_id))
        item = current["items"].get(key)
        if item is None:
            raise HTTPException(404, "그 숫자를 찾지 못했습니다(본문이 바뀌었을 수 있습니다). 화면을 새로 고쳐 주세요.")
        if raw and item["raw"] != raw:
            raise HTTPException(409, f"화면의 숫자({raw})와 서버의 숫자({item['raw']})가 다릅니다. 화면을 새로 고쳐 주세요.")
        marks = dict(doc.get("numberChecks") or {})
        if confirmed:
            marks[key] = {"by": user.id, "at": iso(utcnow()), "note": note.strip()[:300], "status": item["status"], "flags": item["flags"], "raw": item["raw"]}
        else:
            marks.pop(key, None)
        doc["numberChecks"] = marks
        self.persist(row, doc)
        return self.numbers(session_id, user)

    def request_review(self, session_id: str, user: User, reviewer_id: str, note: str = "") -> Dict[str, Any]:
        """작성자 → 검토자 작업 항목(점검 요약을 담는다) + 채널 알림. 막지 않는다 — 확인할 것이 남아 있으면 그대로 요약에 적는다.
        같은 리포트의 앞선 검토 작업이 아직 안 끝났으면 새로 만들지 않고 그 작업을 고친다."""
        row = self.access(session_id, user, write=True)
        if session_id in _busy:
            raise HTTPException(409, "이 세션에서 아직 앞선 요청을 처리하고 있습니다.")
        if reviewer_id == user.id:
            raise HTTPException(400, "검토는 다른 멤버에게 요청해 주세요.")
        mm = self.repo.membership(row.workspace_id, reviewer_id)
        reviewer = self.repo.user(reviewer_id)
        if mm is None or reviewer is None or ROLE_RANK.get(mm.role, 0) < ROLE_RANK["reviewer"]:
            raise HTTPException(400, "검토자는 이 워크스페이스의 검토자 이상 멤버여야 합니다.")
        doc = copy.deepcopy(row.doc or {})
        r = readiness(doc, ledger_for(self.session, row.workspace_id))
        title = str((doc.get("setup") or {}).get("title") or row.title or "제목 없는 리포트")
        line = summary_line(r)
        lines = [f"{user.name} {user.title}님 요청 · {line}"]
        if note.strip():
            lines.append(f"요청 메모: {note.strip()[:300]}")
        lines += [f"- [{KIND_KO[i['kind']]}] {i['title']}: {i['text']}" for i in r["items"] if i["kind"] != "unwritten"][:8]
        detail = "\n".join(lines)[:1000]
        prev = (doc.get("reviewRequest") or {}).get("taskId")
        task = self.session.get(Task, prev) if prev else None
        if task is not None and task.status != "done":
            task.assignee_id, task.detail, task.status = reviewer_id, detail, "todo"
        else:
            task = Task(id=id36("t", 4), workspace_id=row.workspace_id, title=f"리포트 검토 — {title}"[:160], detail=detail, assignee_id=reviewer_id, status="todo", source={"kind": "report", "reportId": row.id}, created_by=user.id)
        self.repo.save(task)
        text = f"{user.name} {user.title}님이 {reviewer.name} {reviewer.title}님께 '{title}' 리포트 검토를 요청했습니다 — {line}"
        if note.strip():
            text += f"\n“{note.strip()[:300]}”"
        self.repo.save(ChannelMessage(id=id36("c", 4), workspace_id=row.workspace_id, user_id=user.id, kind="system", text=text, meta={"mentions": [reviewer_id], "report": {"id": row.id, "title": title}, "taskId": task.id}))
        notify(  # 채널 메시지는 숨긴 화면이라 알림함으로도(채널 글은 그대로 둔다)
            [reviewer_id], workspace_id=row.workspace_id, kind="review", title=f"검토 요청 — {title}"[:200], body=f"{user.name} {user.title}님 · {line}",
            link={"w": row.workspace_id, "v": "reports", "s": row.id}, ref={"kind": "report", "id": row.id}, session=self.session)
        doc["reviewRequest"] = {"reviewerId": reviewer_id, "requestedBy": user.id, "requestedAt": iso(utcnow()), "taskId": task.id, "note": note.strip()[:300], "summary": line, "state": r["state"]}
        doc["approval"] = {**(doc.get("approval") or {}), "status": "review", "label": "검토 중", "reviewerId": reviewer_id, "at": iso(utcnow())}
        self.persist(row, doc)
        return self.readiness(session_id, user)

    def request_reviews(self, workspace_id: str, user: User, report_ids: List[str], reviewer_id: str, note: str = "") -> Dict[str, Any]:
        """문서 검수 화면 — 작성한 문서 여러 편을 한 검토자에게 한 번에(문서마다 request_review)."""
        require_member(self.session, workspace_id, user, "editor")
        ids = [r for r in dict.fromkeys(report_ids) if (self.repo.get(r) or ReportSession(id="", workspace_id="")).workspace_id == workspace_id]
        if not ids:
            raise HTTPException(400, "보낼 문서를 골라 주세요.")
        for rid in ids:
            self.request_review(rid, user, reviewer_id, note)
        return {"sent": len(ids)}

    def persist(self, row: ReportSession, doc: Dict[str, Any]) -> None:
        doc["updatedAt"] = now_iso()
        row.doc = dict(doc)  # 새 객체를 대입해야 JSON 컬럼이 dirty 로 잡힌다
        # 제목이 없으면 첫 질문을 목록 이름으로(대화만 하는 작업, 제목 없이 붙인 문서)
        first = next((m.get("text") for m in doc.get("transcript") or [] if m.get("role") == "user" and m.get("text")), "")
        row.title = str((doc.get("setup") or {}).get("title") or (first or "")[:40])
        row.report_type = str(doc.get("reportType") or DEFAULT_TYPE)
        row.written = len(written_sections(doc))
        self.repo.save(row)

    def payload(self, row: ReportSession, user: User) -> Dict[str, Any]:
        """FE 로 가는 세션 응답(모델 히스토리 제외). 저장 문서는 여기서 고치지 않는다.
        자료는 워크스페이스 것(리포트 doc 의 documentIds 는 턴마다 이 문서의 데이터 범위에서 이 작업이 끈 것을 뺀 값으로 덮어쓴다 — drive.report_scope_ids).
        documents 는 이 문서의 데이터 범위 전부 — off = 이 작업 채팅에서 끈 것, shared = 사내 공용 데이터. dataScope = 범위 모드와 고른 데이터·폴더 이름.
        에이전트 대화(transcript)는 작성자에게만 — 대화는 개인, 기록은 공유."""
        doc = dict(row.doc or {})
        ws: Optional[Workspace] = self.repo.workspace(row.workspace_id)
        doc["documentIds"] = report_scope_ids(self.session, ws, doc, row.created_by)
        owner = row.created_by == user.id
        public = public_session(doc)
        if not owner:
            public = {**public, "transcript": [], "userInputs": {}}
        author = self.repo.user(row.created_by)
        used = set(doc["documentIds"])
        company = set(company_ids()) - set((ws.document_ids if ws else None) or [])
        from app.research.service import ResearchService

        rsvc = ResearchService(self.session)
        tables = []
        for t in rsvc._tables(doc.get("tableIds") or []):
            try:
                tables.append(rsvc.table_view(rsvc.table_row(t.id, user), user))
            except HTTPException:
                continue  # 지운 표·이제 볼 수 없는 표
        return {
            "session": public,
            "report": build_report_view(doc),
            "modes": normalize_modes(None, doc),
            "hasDoc": has_doc(doc),
            # 문서 판(중간 저장) — 목록만(내용은 되돌릴 때 서버가)
            "versions": [{k: v.get(k) for k in ("id", "at", "label", "written")} for v in reversed(doc.get("versions") or [])],
            "tables": tables,
            "suggestions": suggestions_for(doc) if owner else [],
            "provider": provider_info(),
            "documents": [{**c, "off": c["id"] not in used, "shared": c["id"] in company} for c in document_cards(report_scope_ids(self.session, ws, doc, row.created_by, apply_off=False))],
            "dataScope": scope_view(self.session, ws, doc, row.created_by),
            "workspaceId": row.workspace_id,
            "owner": {"id": row.created_by, "name": author.name if author else "", "title": author.title if author else ""},
            "canChat": owner,
        }

    # ── 한 턴 SSE ──────────────────────────────────────────────────────
    @staticmethod
    def start_turn(session_id: str, body: Dict[str, Any]) -> Tuple[EventStream, "asyncio.Task[None]"]:
        """producer 태스크를 띄운다. 잠금(try_lock)은 호출자가 먼저 잡고, 해제는 producer 의 finally 가 한다."""
        es = EventStream()
        task = asyncio.create_task(_produce_turn(es, session_id, body), name=f"report-turn-{session_id}")
        _tasks[session_id] = task
        return es, task

    @staticmethod
    def cancel_turn(session_id: str) -> bool:
        task = _tasks.get(session_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    @staticmethod
    async def stream_events(es: EventStream, task: "asyncio.Task[None]", request: Request) -> AsyncIterator[str]:
        started = time.monotonic()
        last_ping = started
        try:
            while True:
                if await request.is_disconnected():
                    task.cancel()
                    break
                if time.monotonic() - started > TURN_WALLCLOCK_SEC:
                    yield sse("error", {"type": "error", "message": "처리 시간이 너무 길어 중단했습니다. 다시 요청해 주세요."})
                    yield sse("done", {"type": "done"})
                    task.cancel()
                    break
                try:
                    ev = await asyncio.wait_for(es.queue.get(), DISCONNECT_POLL_SEC)
                except asyncio.TimeoutError:
                    if time.monotonic() - last_ping >= PING_INTERVAL_SEC:
                        last_ping = time.monotonic()
                        yield ": ping\n\n"
                    continue
                if ev is None:
                    break
                yield sse(str(ev.get("type", "message")), ev)
        finally:
            if not task.done():
                task.cancel()


def _persist_doc(session_id: str, doc: Dict[str, Any]) -> None:
    with Session(engine) as s:
        svc = ReportService(s)
        row = svc.repo.get(session_id)
        if row is None:
            logger.warning("report session %s vanished during turn — not saved", session_id)
            return
        svc.persist(row, {k: v for k, v in doc.items() if not k.startswith("_")})  # _ 키 = 턴에만 싣는 맥락(양식 목록·지금 표)


def _workspace_context(workspace_id: str, doc: Dict[str, Any], owner_id: str) -> Dict[str, Any]:
    """턴에 실을 워크스페이스 맥락 — 이 작업 채팅이 쓰는 데이터(작성자에게 보이는 범위 → 고른 데이터·폴더 − 이 작업이 끈 것)·확정된 팀 기록·원장 채택값."""
    from app.ledger.service import choices_of
    from app.records.service import confirmed_notes

    with Session(engine) as s:
        ws = Repo(s).workspace(workspace_id)
        from app.agent.template import public_types
        from app.db import ResearchTable
        from app.research.forms import format_assets
        from app.research.service import visible_templates
        from app.templates_import.registry import report_type_views

        cur = s.get(ResearchTable, doc.get("currentTableId") or "") if doc.get("currentTableId") else None
        return {
            "workspaceId": workspace_id,
            "ownerId": owner_id,
            "documentIds": report_scope_ids(s, ws, doc, owner_id),
            "teamNotes": confirmed_notes(s, workspace_id),
            "ledgerChoices": choices_of(s, workspace_id),
            "_templates": visible_templates(s, workspace_id, owner_id),
            # 이 작업 문서 양식의 표·차트 양식(F번호 — research/forms.py)
            "_forms": format_assets(s, doc.get("reportType")),
            # 말로 붙일 수 있는 문서 양식(use_format) — 기본 유형·고정 양식 + 이 사람에게 보이는 등록 양식
            "_formats": [{"id": t["id"], "title": t["title"]} for t in public_types() if t["kind"] != "free"]
            + [{"id": t["id"], "title": t["title"]} for t in report_type_views(s, workspace_id, s.get(User, owner_id))],
            "_current": {"id": cur.id, "title": cur.title, "data": cur.data} if cur is not None else None,
        }


def note_into_section(doc: Dict[str, Any], sec: Dict[str, Any], note: Any) -> None:
    """메모를 섹션 끝에 잇는다 — 출처 링크는 본문 인용 토큰으로(그 출처는 원문 문단)."""
    from app.agent.session import set_section
    from app.research.notes import to_tokens

    text = to_tokens((note.data or {}).get("text") or "").strip()
    set_section(doc, sec["step"], f"{sec['content'].rstrip()}\n\n{text}" if sec.get("content") else text)
    log_section(doc, sec["step"], f"메모 넣기: {note.title}")


def _attach_table(doc: Dict[str, Any], owner_id: str, table_id: str) -> None:
    """오른쪽 패널에서 보던 표(드라이브·에셋에서 연 표 포함) — '이 표'가 가리키는 것. 볼 수 있는 표면 이 작업의 표 목록에도 넣는다."""
    from app.research.service import ResearchService

    with Session(engine) as s:
        user = s.get(User, owner_id)
        if user is None:
            return
        try:
            ResearchService(s).table_row(table_id, user)
        except HTTPException:
            return
    doc["currentTableId"] = table_id
    if table_id not in (doc.get("tableIds") or []):
        doc["tableIds"] = [*(doc.get("tableIds") or []), table_id]


async def _produce_turn(es: EventStream, session_id: str, body: Dict[str, Any]) -> None:
    started = time.monotonic()
    workspace_id = ""
    try:
        with Session(engine) as s:
            row = ReportService(s).row_or_404(session_id)
            doc = copy.deepcopy(row.doc or {})
            workspace_id, owner_id = row.workspace_id, row.created_by
        usage.bind(ws=workspace_id, feature="turn")  # 이 턴의 LLM 사용량을 워크스페이스로 묶는다
        if body.get("tableId"):
            await asyncio.to_thread(_attach_table, doc, owner_id, str(body["tableId"]))
        doc.update(await asyncio.to_thread(_workspace_context, workspace_id, doc, owner_id))
        llm = ReportLlm()

        async def save() -> None:
            await asyncio.to_thread(_persist_doc, session_id, copy.deepcopy(doc))

        def emit(e: Dict[str, Any]) -> None:
            if e.get("type") in _REPORT_EVENTS:
                try:
                    e = {**e, "report": build_report_view(doc)}
                except Exception:  # noqa: BLE001 — 뷰 조립 실패가 이벤트를 막지 않게
                    logger.exception("report view failed for %s", e.get("type"))
            es.emit(e)

        await run_turn(doc, body, llm, emit, save)
    except asyncio.CancelledError:
        raise
    except LlmError as e:
        es.emit({"type": "error", "message": humanize_error(e), "code": e.code})
        es.emit({"type": "done"})
    except HTTPException as e:
        es.emit({"type": "error", "message": str(e.detail)})
        es.emit({"type": "done"})
    except Exception as e:  # noqa: BLE001
        logger.exception("report turn failed")
        es.emit({"type": "error", "message": f"처리 중 오류가 났습니다: {e}"})
        es.emit({"type": "done"})
    finally:
        es.close()
        release_lock(session_id)
        if _tasks.get(session_id) is asyncio.current_task():
            _tasks.pop(session_id, None)
        await asyncio.to_thread(usage.activity, "turn", {"sessionId": session_id}, {"sec": round(time.monotonic() - started, 2), "approval": bool(body.get("approval"))}, ws=workspace_id)
