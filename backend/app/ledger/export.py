"""근거 원장 → 엑셀(XLSX). 문서 자동화의 첫 출력 — 운용역이 열어서 값·출처·계산을 직접 검증한다.

시트
  안내       워크스페이스·내보낸 시각·사람, 열 설명
  원장       표 칸 하나 = 한 줄: 지표·기간·기준·값·단위·환산 값·표기 원문·출처 자료·쪽/시트·표 칸·행 원문·상태
  충돌·채택  묶음(지표×기간×기준) 하나 = 한 줄: 자료 수·값들·채택값·채택자·사유
  계산       리포트 섹션에 쓰인 계산(calculate 도구) — 결과 칸은 '원장' 시트 칸을 참조하는 **엑셀 수식**, 옆에 작성 당시 값
값은 표 칸에서 코드로 뽑은 것(LLM 이 만든 수치 없음). 문서에서 온 글자는 수식으로 해석되지 않게 문자열로 넣는다.
"""
from __future__ import annotations

import io
import re
from datetime import timezone
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlmodel import Session, select

from app.auth import require_member
from app.db import ReportSession, User, utcnow
from app.docs.store import load_chunks
from app.ledger.calc import excel_formula, readable, refs_in
from app.ledger.figures import Figure
from app.ledger.service import ledger_for

LEDGER_SHEET = "원장"
HEAD_FILL = PatternFill("solid", fgColor="1E2761")
HEAD_FONT = Font(bold=True, color="FFFFFF")
CONFLICT_FILL = PatternFill("solid", fgColor="FDECEA")
CHOSEN_FILL = PatternFill("solid", fgColor="E6F4EA")
WRAP = Alignment(wrap_text=True, vertical="top")

FIGURE_COLS: List[Tuple[str, int]] = [
    ("지표", 16), ("기간", 10), ("기준", 8), ("값", 14), ("단위", 10), ("환산 값(배율 적용)", 20), ("표기 원문", 14),
    ("출처 자료", 30), ("쪽/시트", 10), ("표 칸(행·열)", 12), ("열 머리", 14), ("행 원문", 50), ("상태", 16), ("근거 ID", 30),
]
VALUE_COL, ABS_COL = 4, 6  # 계산 수식이 참조하는 열(값 / 환산 값)


def _clean(v: Any) -> Any:
    return ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v


def _put(ws: Worksheet, row: int, col: int, v: Any, fmt: Optional[str] = None) -> None:
    cell = ws.cell(row=row, column=col, value=_clean(v))
    if isinstance(v, str) and v.startswith("="):
        cell.data_type = "s"  # 문서에서 온 글자는 수식이 아니다
    if fmt:
        cell.number_format = fmt
    cell.alignment = WRAP


def _header(ws: Worksheet, cols: List[Tuple[str, int]]) -> None:
    for i, (name, width) in enumerate(cols, 1):
        c = ws.cell(row=1, column=i, value=name)
        c.fill, c.font = HEAD_FILL, HEAD_FONT
        c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}1"


def _num_fmt(f: Figure) -> str:
    dec = int(f.get("decimals") or 0)
    base = "#,##0" + ("." + "0" * dec if dec > 0 else "")
    return base + '"%"' if f.get("percent") else base


def _status(f: Figure, g: Optional[Dict[str, Any]]) -> str:
    if g is None:
        return ""
    chosen = (g.get("chosen") or {}).get("figureId")
    if chosen:
        return "채택값" if chosen == f["fid"] else "채택 안 됨"
    if g["conflict"]:
        return "충돌(자료마다 다름)"
    return f"일치({g['documents']}개 자료)" if g["documents"] > 1 else "단일 자료"


class _Rows:
    """표 칸의 행 원문·열 머리 — 문서마다 청크를 한 번만 읽는다."""

    def __init__(self) -> None:
        self._by_doc: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def context(self, f: Figure) -> Tuple[str, str]:
        chunks = self._by_doc.get(f["doc"])
        if chunks is None:
            chunks = self._by_doc[f["doc"]] = {c.get("id"): c for c in load_chunks(f["doc"])}
        rows: List[List[str]] = (chunks.get(f["chunk"]) or {}).get("rows") or []
        ri, ci = (f.get("cell") or [0, 0])[:2]
        row = rows[ri] if 0 <= ri < len(rows) else []
        head = rows[0][ci] if rows and 0 <= ci < len(rows[0]) else ""
        return str(head or ""), " | ".join(str(x or "") for x in row)


def _figures_sheet(ws: Worksheet, figures: List[Figure], groups: List[Dict[str, Any]]) -> Dict[str, int]:
    """→ 근거 ID → 행 번호(계산 수식이 참조)."""
    _header(ws, FIGURE_COLS)
    by_fid = {f["fid"]: f for f in figures}
    group_of: Dict[str, Dict[str, Any]] = {fid: g for g in groups for fid in g["figureIds"]}
    order = [fid for g in groups for fid in g["figureIds"] if fid in by_fid]
    order += [f["fid"] for f in figures if f["fid"] not in group_of]
    rows = _Rows()
    where: Dict[str, int] = {}
    for r, fid in enumerate(order, 2):
        f, g = by_fid[fid], group_of.get(fid)
        head, row_text = rows.context(f)
        page = f"p.{f['page']}" if f.get("page") else (f"시트 {f['sheet']}" if f.get("sheet") else "")
        cell = f"{f['cell'][0] + 1}행 {f['cell'][1] + 1}열" if f.get("cell") else ""
        unit = f.get("unit") or ("" if f.get("unitKnown", True) else "(표기 없음)")
        abs_fmt = "#,##0" if f.get("currency") and not f.get("percent") else _num_fmt(f)
        values = [f["metric"], f["period"], f.get("basis") or "", f["value"], unit, f["abs"], f["raw"], f.get("docLabel") or f["doc"], page, cell, head, row_text, _status(f, g), fid]
        for c, v in enumerate(values, 1):
            _put(ws, r, c, v, _num_fmt(f) if c == VALUE_COL else (abs_fmt if c == ABS_COL else None))
        status = values[12]
        fill = CONFLICT_FILL if status.startswith("충돌") else (CHOSEN_FILL if status == "채택값" else None)
        if fill:
            for c in range(1, len(FIGURE_COLS) + 1):
                ws.cell(row=r, column=c).fill = fill
        where[fid] = r
    return where


GROUP_COLS: List[Tuple[str, int]] = [("지표", 16), ("기간", 10), ("기준", 8), ("상태", 16), ("자료 수", 8), ("자료별 값", 60), ("채택값", 18), ("채택한 사람", 12), ("사유", 30), ("채택 시각", 18)]


def _groups_sheet(ws: Worksheet, figures: List[Figure], groups: List[Dict[str, Any]], names: Dict[str, str]) -> None:
    _header(ws, GROUP_COLS)
    by_fid = {f["fid"]: f for f in figures}
    for r, g in enumerate(groups, 2):
        chosen = g.get("chosen") or {}
        state = "채택" if chosen.get("figureId") else ("충돌" if g["conflict"] else ("일치" if g["documents"] > 1 else "단일 자료"))
        parts = []
        for v in g["values"]:
            labels = ", ".join(dict.fromkeys(by_fid[i].get("docLabel") or by_fid[i]["doc"] for i in v["figureIds"] if i in by_fid))
            parts.append(f"{v['display']} — {labels}")
        pick = by_fid.get(chosen.get("figureId") or "")
        values = [g["metric"], g["period"], g.get("basis") or "", state, g["documents"], "\n".join(parts), (pick.get("display") or pick["raw"]) if pick else "", names.get(chosen.get("chosenBy") or "", chosen.get("chosenBy") or ""), chosen.get("reason") or "", _local(chosen.get("chosenAt"))]
        for c, v in enumerate(values, 1):
            _put(ws, r, c, v)
        fill = CHOSEN_FILL if state == "채택" else (CONFLICT_FILL if state == "충돌" else None)
        if fill:
            for c in range(1, len(GROUP_COLS) + 1):
                ws.cell(row=r, column=c).fill = fill


CALC_COLS: List[Tuple[str, int]] = [("리포트", 20), ("섹션", 20), ("계산", 28), ("계산식", 50), ("결과(엑셀 수식)", 16), ("작성 당시 값", 14), ("입력 수치", 60)]


def _calcs_sheet(ws: Worksheet, reports: List[ReportSession], figures: List[Figure], where: Dict[str, int]) -> int:
    """리포트 섹션의 계산 기록 → 수식. 입력 수치가 원장에서 사라졌으면 수식 대신 작성 당시 값만 남긴다."""
    _header(ws, CALC_COLS)
    by_fid = {f["fid"]: f for f in figures}
    r = 2
    for rep in reports:
        doc = rep.doc or {}
        titles = {s.get("step"): s.get("title") or s.get("step") for s in doc.get("sections") or []}
        for step, ev in (doc.get("evidence") or {}).items():
            for c in (ev or {}).get("calcs") or []:
                expr = str(c.get("expression") or "")
                refs = refs_in(expr)
                inputs = list(c.get("inputs") or [])
                fids = dict(zip(refs, inputs)) if len(refs) == len(inputs) else {}
                ok = bool(fids) and all(fid in where for fid in fids.values())
                names = {k: f"{by_fid[v]['metric']} {by_fid[v]['period']} {by_fid[v].get('display') or by_fid[v]['raw']}" for k, v in fids.items() if v in by_fid}
                # 같은 계산 안의 금액은 모두 단위가 있거나 모두 없다(계산 도구가 섞지 않는다) — 단위가 있으면 환산 값 열을 참조
                col = get_column_letter(ABS_COL)
                cells = {k: f"'{LEDGER_SHEET}'!${col}${where[v]}" for k, v in fids.items() if v in where}
                # 비율끼리의 차이(diff)는 %p — 증감률(%)과 헷갈리지 않게
                fmt = ('0.0"%p"' if expr.strip().startswith("diff(") else '0.0"%"') if c.get("percent") else "#,##0"
                values = [rep.title or "제목 없는 리포트", titles.get(step, step), c.get("label") or "계산", readable(expr, names) if names else c.get("readable") or expr]
                for i, v in enumerate(values, 1):
                    _put(ws, r, i, v)
                formula = excel_formula(expr, cells) if ok else ""
                if formula:
                    ws.cell(row=r, column=5, value=formula).number_format = fmt
                else:
                    _put(ws, r, 5, "입력 수치가 원장에 없음")
                _put(ws, r, 6, c.get("value"), fmt)
                _put(ws, r, 7, "\n".join(f"{k}: {names.get(k, '')} ({(by_fid.get(v) or {}).get('docLabel', '')}, 원장 {where[v]}행)" if v in where else f"{k}: (원장에 없음)" for k, v in fids.items()))
                r += 1
    return r - 2


def _local(iso_s: Optional[str]) -> str:
    if not iso_s:
        return ""
    from datetime import datetime

    from app.scheduler import local_tz

    try:
        dt = datetime.fromisoformat(iso_s.rstrip("Z")).replace(tzinfo=timezone.utc)
    except ValueError:
        return iso_s
    return dt.astimezone(local_tz()).strftime("%Y-%m-%d %H:%M")


def _safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_")[:40] or "workspace"


def ledger_xlsx(session: Session, workspace_id: str, user: User) -> Tuple[bytes, str]:
    ws_row, _m = require_member(session, workspace_id, user)
    led = ledger_for(session, workspace_id)
    figures, groups = led["figures"], led["groups"]
    names = {u.id: f"{u.name} {u.title}".strip() for u in session.exec(select(User)).all()}
    reports = list(session.exec(select(ReportSession).where(ReportSession.workspace_id == workspace_id)).all())

    wb = Workbook()
    info = wb.active
    info.title = "안내"
    fig_ws = wb.create_sheet(LEDGER_SHEET)
    grp_ws = wb.create_sheet("충돌·채택")
    calc_ws = wb.create_sheet("계산")
    where = _figures_sheet(fig_ws, figures, groups)
    _groups_sheet(grp_ws, figures, groups, names)
    n_calc = _calcs_sheet(calc_ws, reports, figures, where)

    now = _local(utcnow().isoformat() + "Z")
    lines = [
        ("근거 원장", ""),
        ("워크스페이스", ws_row.name),
        ("내보낸 시각", now),
        ("내보낸 사람", names.get(user.id, user.id)),
        ("수치", f"{len(figures)}건 · 자료 {len({f['doc'] for f in figures})}개"),
        ("묶음", f"{len(groups)}개 · 충돌 {sum(1 for g in groups if g['conflict'] and not g.get('chosen'))} · 채택 {sum(1 for g in groups if g.get('chosen'))}"),
        ("계산", f"{n_calc}건(리포트 섹션에 쓰인 것)"),
        ("", ""),
        ("값", "자료의 표 칸에서 코드로 뽑은 값입니다(AI 가 만든 수치 없음). '표기 원문'·'행 원문'이 자료에 적힌 그대로입니다."),
        ("환산 값", "단위 배율을 적용한 값(억원 → 원 등). 단위 표기가 없는 칸은 표기 숫자 그대로입니다."),
        ("상태", "충돌 = 같은 지표·기간·기준인데 자료마다 값이 다름(빨강) · 채택값 = 팀이 고른 값(초록, 결정 기록이 남음)"),
        ("계산", "결과 칸은 '원장' 시트 칸을 참조하는 엑셀 수식입니다. 원장 값을 고치면 다시 계산되고, '작성 당시 값'과 비교해 검증할 수 있습니다."),
    ]
    for r, (k, v) in enumerate(lines, 1):
        _put(info, r, 1, k)
        _put(info, r, 2, v)
        info.cell(row=r, column=1).font = Font(bold=True, size=14 if r == 1 else 11)
    info.column_dimensions["A"].width = 14
    info.column_dimensions["B"].width = 90

    buf = io.BytesIO()
    wb.save(buf)
    stamp = now[:10].replace("-", "")
    return buf.getvalue(), f"{_safe_name(ws_row.name)}_근거원장_{stamp}.xlsx"


__all__ = ["ledger_xlsx"]
