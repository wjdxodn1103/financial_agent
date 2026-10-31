"""PDF 그림 → 차트 값(VL 모델). 캡션('그림 n')과 붙은 그림 영역을 PNG 로 잘라 차트 종류·범주·계열·값을 JSON 으로 읽게 한다.

그림 영역 = 캡션 아래(없으면 위) 350pt 안의 그리기·이미지 상자를 합친 것(없으면 캡션 아래 260pt).
값은 미리보기·양식 모양(열 이름·차트 종류)에만 쓴다 — 등록한 양식은 나중에 자료에서 다시 채운다.
VL 은 config.CHAT_MODEL 과 같은 모델(.env 의 nemotron-…-vl). 차트가 아니거나 읽지 못하면 None — 그 그림은 리포트 양식의 자리로만 남는다.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.llm.base import ChatParams

logger = logging.getLogger(__name__)
FIG_MAX = 6  # 샘플 하나에서 VL 호출 상한
PROMPT = """이 그림은 보고서의 차트다. 차트에 보이는 값을 그대로 읽어 JSON 하나만 답한다(설명 없이).
{"chart_type": "bar" 또는 "line", "horizontal": 가로 막대면 true, "categories": [x축(가로 막대면 세로축) 항목], "series": [{"name": "범례의 계열 이름(없으면 빈 문자열)", "values": [숫자 또는 null]}], "unit": "단위(보이면)"}
값은 데이터 라벨이 있으면 그 숫자, 없으면 눈금으로 어림한 값. 차트가 아니면 {"chart_type": null}."""


def crop_figure(pdf_path: str | Path, page_no: int, caption_y: float) -> Optional[bytes]:
    import fitz  # PyMuPDF

    doc = fitz.open(str(pdf_path))
    try:
        if not 1 <= page_no <= len(doc):
            return None
        page = doc[page_no - 1]
        boxes = [fitz.Rect(d["rect"]) for d in page.get_drawings() if d.get("rect") is not None]
        boxes += [fitz.Rect(i["bbox"]) for i in page.get_image_info()]
        boxes = [b for b in boxes if b.width > 4 and b.height > 4]
        below = [b for b in boxes if caption_y + 4 <= b.y0 <= caption_y + 350]
        above = [b for b in boxes if caption_y - 350 <= b.y1 <= caption_y - 2]
        pick = below or above
        if pick:
            r = fitz.Rect(pick[0])
            for b in pick[1:]:
                r |= b
            r = fitz.Rect(r.x0 - 12, r.y0 - 10, r.x1 + 12, r.y1 + 22) & page.rect  # 축 글자까지
        else:
            r = fitz.Rect(page.rect.x0 + 20, caption_y + 14, page.rect.x1 - 20, min(page.rect.y1, caption_y + 274))
        if r.width < 40 or r.height < 40:
            return None
        return page.get_pixmap(dpi=144, clip=r).tobytes("png")
    finally:
        doc.close()


def _num(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def parse_figure(text: str, caption: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        return None
    try:
        ans = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(ans, dict) or ans.get("chart_type") not in ("bar", "line"):
        return None
    cats = [str(c).strip() for c in ans.get("categories") or [] if str(c).strip()]
    series: List[Dict[str, Any]] = []
    for i, s in enumerate(ans.get("series") or []):
        if not isinstance(s, dict):
            continue
        vals = [_num(v) for v in s.get("values") or []]
        if not any(v is not None for v in vals):
            continue
        # 범례가 없는 단일 계열 — 캡션에서 '추이·비교·현황' 같은 꼬리말을 떼면 지표 이름('매출액 추이' → '매출액')
        lone = re.sub(r"\s*(추이|비교|현황|구성|변화|전망|동향|분포|비중|흐름)$", "", caption or "").strip()
        name = str(s.get("name") or "").strip() or ((lone or caption) if len(ans.get("series") or []) == 1 else f"계열 {i + 1}")
        series.append({"name": name[:40], "values": vals})
    if not cats or not series:
        return None
    n = len(cats)
    for s in series:
        s["values"] = (s["values"] + [None] * n)[:n]
    return {"type": ans["chart_type"], "horizontal": bool(ans.get("horizontal")) and ans["chart_type"] == "bar", "title": "", "categories": cats, "series": series, "unit": str(ans.get("unit") or "").strip()[:12] or None}


async def read_figure(llm: Any, png: bytes, caption: str) -> Optional[Dict[str, Any]]:
    """→ {type, horizontal, categories, series, unit} | None."""
    msg = [{"role": "user", "content": [{"type": "text", "text": PROMPT + (f"\n그림 캡션: {caption}" if caption else "")}, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}]
    try:
        res = await llm.complete("chat", ChatParams(messages=msg, temperature=0.1, max_tokens=2500, timeout_s=120))
    except Exception:  # noqa: BLE001 — VL 이 안 되면 그 그림은 자리로만
        logger.exception("figure read failed")
        return None
    return parse_figure(getattr(res, "content", "") or "", caption)


__all__ = ["FIG_MAX", "crop_figure", "parse_figure", "read_figure"]
