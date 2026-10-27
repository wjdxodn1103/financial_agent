"""양식 샘플 한 턴 — 올린 Word·PDF 를 읽어 표·차트 카드(import_item)를 하나씩, 이어서 리포트 양식 카드(import_format).

카드는 대화 기록(transcript)에 남고, 등록·건너뛰기는 import API 가 카드 상태를 바꾼다(doc.imports 와 기록 둘 다).
표 spec 은 LLM(동시 3개) — 실패하면 규칙. 차트는 규칙. PDF 그림은 리포트 양식의 자리로만(모양은 5단계 VL).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.ids import id36
from app.templates_import.extract import SampleError, extract_sample
from app.templates_import.preview import chart_preview, table_preview
from app.templates_import.spec import chart_to_spec, table_to_spec

logger = logging.getLogger(__name__)
Emit = Callable[[Dict[str, Any]], None]


async def build_cards(sample: Dict[str, Any], llm: Any, source: str, path: Optional[str] = None) -> List[Dict[str, Any]]:
    """표·차트 → 카드 [{n, kind, title, section, spec, via, block, state}] (본문 순서). PDF 그림은 VL 이 읽으면 차트 카드(via=vl)."""
    from app.templates_import.vision import FIG_MAX, crop_figure, read_figure

    sem = asyncio.Semaphore(3)
    figures = [n for n, a in enumerate(sample["assets"]) if a["kind"] == "figure"][:FIG_MAX] if path and llm is not None else []

    async def one(n: int, a: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        sec = sample["sections"][a["section"]]["title"] if a.get("section") is not None and a["section"] < len(sample["sections"]) else None
        if a["kind"] == "table":
            async with sem:
                spec, via = await table_to_spec(llm, a["rows"], a.get("caption") or "", a.get("unit"))
            block = table_preview(a["rows"], spec, a.get("caption") or spec["name"], source)
            subjects = [r[0] for r in a["rows"][1:] if r and r[0].strip()] if spec["orientation"] == "subjects_as_rows" else [h for h in a["rows"][0][1:] if h.strip()]
        elif a["kind"] == "chart":
            spec, via = chart_to_spec(a["chart"], a.get("caption") or a["chart"].get("title") or "", a.get("unit")), "rule"
            block = chart_preview(a["chart"], a.get("caption") or spec["name"], a.get("unit"), source)
            subjects = list(a["chart"]["categories"])
        elif a["kind"] == "figure" and n in figures:
            png = await asyncio.to_thread(crop_figure, path, a["page"], a["y"])
            async with sem:
                chart = await read_figure(llm, png, a.get("caption") or "") if png else None
            if chart is None:
                return None  # 읽지 못한 그림 — 리포트 양식의 그림 자리로만
            unit = a.get("unit") or chart.get("unit")
            spec, via = chart_to_spec(chart, a.get("caption") or "", unit), "vl"
            block = chart_preview(chart, a.get("caption") or spec["name"], unit, source)
            subjects = list(chart["categories"])
            a["read"] = True
        else:
            return None
        return {"n": n, "kind": "chart" if a["kind"] == "figure" else a["kind"], "title": a.get("caption") or spec["name"], "section": sec, "spec": spec, "via": via, "block": block, "sampleRows": subjects, "state": "pending"}

    out = await asyncio.gather(*(one(n, a) for n, a in enumerate(sample["assets"])))
    return [c for c in out if c is not None]


def format_card(sample: Dict[str, Any], cards: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
    """리포트 양식 카드 — 섹션(제목·수준·안내) + 섹션마다 표·차트 카드 번호와 그림 자리."""
    sections = []
    for i, s in enumerate(sample["sections"]):
        assets = [c["n"] for c in cards if c.get("section") == s["title"]]
        figures = [a.get("caption") or "그림" for a in sample["assets"] if a["kind"] == "figure" and not a.get("read") and a.get("section") == i]
        sections.append({"title": s["title"], "level": s["level"], "guide": s.get("guide") or "", "assets": assets, "figures": figures})
    return {"name": name, "sections": sections, "state": "pending"}


async def run_import(doc: Dict[str, Any], import_id: str, llm: Any, emit_raw: Emit, save: Callable[[], Awaitable[None]]) -> None:
    from app.agent.loop import TranscriptBuilder

    imp = (doc.get("imports") or {}).get(import_id)
    asst_id = id36("m", 5)
    tb = TranscriptBuilder(asst_id)

    def emit(e: Dict[str, Any]) -> None:
        tb.apply(e)
        emit_raw(e)

    def say(text: str) -> None:
        emit({"type": "text", "delta": text})

    emit({"type": "meta", "sessionId": doc.get("id"), "model": getattr(llm, "chat_model", "")})
    doc.setdefault("transcript", []).append({"id": f"u{asst_id[1:]}", "role": "user", "text": f"양식 샘플: {(imp or {}).get('name') or '파일'}", "attachment": (imp or {}).get("name")})
    try:
        if imp is None:
            say("올린 파일을 찾지 못했습니다. 다시 올려 주세요.")
            return
        name = imp["name"]
        emit({"type": "status", "stage": "import"})
        sample = await asyncio.to_thread(extract_sample, imp["path"], name)
        if sample.get("scanned"):
            say(f"'{name}' 은(는) 스캔 이미지라 글자를 읽을 수 없습니다. 글자가 선택되는 PDF 나 Word 파일로 올려 주세요.")
            imp["status"] = "scanned"
            return
        tables = sum(1 for a in sample["assets"] if a["kind"] == "table")
        charts = sum(1 for a in sample["assets"] if a["kind"] == "chart")
        figures = sum(1 for a in sample["assets"] if a["kind"] == "figure")
        if not sample["assets"] and not sample["sections"]:
            say(f"'{name}' 에서 섹션 제목이나 표·차트를 찾지 못했습니다.")
            imp["status"] = "empty"
            return
        found = [x for x in (f"표 {tables}개" if tables else "", f"차트 {charts}개" if charts else "", f"그림 {figures}개" if figures else "", f"섹션 {len(sample['sections'])}개" if sample["sections"] else "") if x]
        more = f" (표·차트가 많아 앞의 {len(sample['assets'])}개만 읽었습니다)" if sample.get("more") else ""
        say(f"'{name}' 에서 {' · '.join(found)}를 찾았습니다{more}." + (" 표·차트는 우리 엔진으로 다시 그렸습니다 — 하나씩 등록할지 골라 주세요." if tables or charts else ""))
        cards = await build_cards(sample, llm, name, imp["path"] if name.lower().endswith(".pdf") else None)
        for c in cards:
            emit({"type": "import_item", "importId": import_id, "item": c})
        fmt = format_card(sample, cards, sample.get("title") or name.rsplit(".", 1)[0]) if sample["sections"] else None
        if fmt:
            emit({"type": "import_format", "importId": import_id, "format": fmt})
        imp.update({"status": "ready", "items": cards, "format": fmt})
    except SampleError as e:
        say(str(e))
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("import failed")
        emit({"type": "error", "message": f"양식을 읽지 못했습니다: {e}"})
    finally:
        doc.setdefault("transcript", []).append(tb.msg)
        await save()
        emit_raw({"type": "done"})


__all__ = ["build_cards", "format_card", "run_import"]
