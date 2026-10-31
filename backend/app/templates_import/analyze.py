"""문서 양식 분석 — 샘플 파일(PDF·DOCX)을 LLM 이 읽어 문서 양식의 '형식'을 제안한다: 섹션 틀·작성 안내·문체 + 표·차트 양식(에셋 — forms.py).
내용(이번 호의 국가·기업·지수 이름, 숫자, 행 이름)이 아니라 다른 대상에도 쓸 꼴만 남긴다.

 - PDF: 쪽마다 그림으로 VL 모델(.env CHAT_MODEL = nemotron-…-vl)에 읽힌다 — 글자층이 없는 PDF(Word 가 글자를 그림으로 저장한 것·스캔본)도 된다.
        표·차트마다 구성(머리 묶음·열·계열·축)·겉모양(색·선·정렬)·위치(box — 원본에서 그 부분만 잘라 보인다)를 받는다.
        글자층이 있으면 그 쪽 글도 같이 준다(제목·이름 표기를 정확히). PAGE_MAX 쪽까지(넘으면 앞뒤 두 쪽 + 가운데 고르게 — pick_pages), 동시에 CONCURRENCY 쪽.
 - DOCX: Word 구조(제목 스타일·표·네이티브 차트·본문 글)를 글로 정리해 한 쪽처럼 준다(VL 없음, 위치 없음).
 - 마지막에 한 번 묶어(같은 모델, 글만) 섹션을 일반화하고 에셋마다 일반 이름·구성 한 줄·고유 이름 바꾸기(rename)·같은 꼴 합치기(same_as)를 받는다.
실측(인디아 브리핑 7쪽, 글자층 없음): 쪽당 약 25~40초, 출력 상한이 작으면 빈 답 → 9000 + 한 번 다시. 위치(box)는 제목·출처 줄까지 대체로 맞다.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.llm.base import ChatParams
from app.templates_import.forms import apply_rename, block_to_asset, strip_number

logger = logging.getLogger(__name__)

PAGE_MAX = 12
CONCURRENCY = 4
PAGE_TEXT_MAX = 2500

PAGE_PROMPT = """보고서 한 쪽의 그림이다. 이 쪽의 구성을 JSON 하나로만 답한다(설명·코드 블록 없이).
{"page_role": "cover|content|appendix|disclaimer",
 "blocks": [
  {"type": "heading", "level": 1 또는 2 또는 3, "text": "제목 글자 그대로"},
  {"type": "paragraph", "about": "무슨 내용인지 한 줄", "sentences": 문장 수},
  {"type": "bullets", "about": "무슨 내용인지 한 줄", "items": 항목 수},
  {"type": "table", "caption": "표 제목 그대로(번호 포함)", "box": [x0, y0, x1, y1],
   "stub": "첫 열 머리 글자", "row_kind": "행이 무엇인지(예: 지수·기업·기간·항목)", "row_count": 데이터 행 수,
   "header": [{"group": "위 칸 묶음 머리(없으면 빈 문자열)", "unit": "단위(없으면 빈)", "columns": ["아래 칸 열 이름"]}],
   "source_line": 표 아래 '자료:' 줄이 있으면 true, "note": '주:' 줄이 있으면 true,
   "look": {"header_fill": "#머리 칸 배경색", "header_text": "#머리 글자색", "rule": "#표 위아래 굵은 선 색", "lines": "horizontal|grid|none", "number_align": "right|center|left"}},
  {"type": "chart", "caption": "그림 제목 그대로", "box": [x0, y0, x1, y1], "position": "main 또는 sidebar",
   "chart_type": "line|bar|barh|area|pie|combo|band|other", "x": "date|period|category",
   "series": [{"name": "범례·계열 이름", "type": "line|bar|area", "axis": "left|right"}], "unit": "왼쪽 축 단위", "unit2": "오른쪽 축 단위(없으면 빈)",
   "legend": "top|bottom|right|none", "colors": ["#계열 색"], "grid": 가로 눈금선이 있으면 true, "labels": 값 글자가 붙어 있으면 true, "source_line": '자료:' 줄이 있으면 true},
  {"type": "other", "about": "로고·작성자·쪽 머리글·면책 등"}
 ],
 "caption_style": {"table_label": "표 제목 앞 말(예: 표)", "chart_label": "그림 제목 앞 말(예: 그림, 없으면 빈)", "numbered": 제목에 번호를 붙이면 true, "bold": 제목이 굵으면 true, "color": "#제목 글자색"},
 "style": "이 쪽 본문의 문체 — 문장 끝맺음, 문단 길이, 숫자·단위·괄호 표기, 소제목 꼴(있으면)"}
본문 순서대로(사이드바는 position=sidebar). box 는 그림 왼쪽 위 (0,0) ~ 오른쪽 아래 (1000,1000) 비율 좌표이고 제목·출처 줄까지 감싼다.
header 는 첫 열(stub)을 뺀 나머지 열을 왼쪽부터 — 위 칸이 여러 열을 묶으면 group 에 그 글자, 묶음이 없는 열은 group 을 빈 문자열로 하나씩.
combo = 막대와 선을 함께(보조축), band = 선 하나와 평균·표준편차 띠선, barh = 가로 막대. 색은 가까운 #RRGGBB.
표·차트의 숫자 값과 행 이름은 옮기지 않는다(머리·계열 이름·구성만)."""

SYNTH_PROMPT = """아래는 보고서 샘플을 쪽마다 읽은 구성(JSON)이다. 표·차트에는 id(a1, a2…)를 붙여 두었다.
이 샘플의 '형식'을 다른 대상(다른 국가·시장·기업·기간)의 문서에도 그대로 쓸 수 있는 문서 양식으로, JSON 하나로만 답한다(설명·코드 블록 없이).
{"name": "양식 이름 — 이 꼴의 문서를 부르는 일반 이름(예: '국가 증시 브리핑', '기업 실적 리뷰')",
 "desc": "어떤 꼴의 문서인지 한 줄",
 "style": "문체·형식 안내 3~6줄 — 문장 끝맺음(예: ~했다·~판단한다), 문단 길이(문장 수), 숫자·단위·증감 괄호 표기(예: +12.0%, YoY), 회사·종목 표기(예: 회사명(티커, 투자의견)), 소제목 꼴",
 "sections": [{"title": "섹션 제목", "level": 1 또는 2,
               "guide": "이 섹션의 꼴 1~3문장 — 다루는 항목의 종류와 순서, 문단 수·길이, 소제목 꼴",
               "repeat": "같은 꼴을 대상마다 되풀이하면 그 대상(예: 기업), 아니면 빈 문자열",
               "assets": ["이 섹션 자리에 있던 표·차트 id"]}],
 "assets": [{"id": "a1", "name": "표·차트 양식 이름(예: '기간별 수익률 비교표', '대표 지수 추이 선 그래프')",
             "desc": "구성 한 줄 — 행이 무엇·열(기간·지표)·계열·가로축·단위(대상 이름 없이)",
             "same_as": "앞의 표·차트와 구성이 완전히 같으면 그 id, 아니면 빈 문자열",
             "rename": {"샘플 대상에만 있는 이름": "역할 이름"}}]}
규칙:
- 내용이 아니라 형식을 뽑는다. 양식 이름·설명·문체·섹션 제목·안내·표차트 이름과 설명에 특정 국가·지역·기업·지수·종목·상품·통화 이름, 날짜·회차·이번 호 사건을 쓰지 않는다.
  그 자리는 '대상'·'대상 시장'·'기업'·'대표 지수'·'현지 통화'처럼 역할로 쓴다. 예: '인도 주요 데이터' → '주요 데이터', 'Nifty 50 추이' → '대표 지수 추이'.
- 안내는 이번 호에 쓴 내용(어느 업종이 올랐다 등)이 아니라 꼴(무엇을 어떤 순서로 몇 문단)으로 쓴다.
- rename: 표 머리·계열 이름·단위 가운데 샘플 대상에만 있는 이름을 역할 이름으로 바꾼다(예: {"Nifty 50": "대표 지수", "INR": "현지 통화"}).
  기간(1주·1개월·1년)·지표(수익률·시가총액·P/E)·평균·표준편차 같은 구조 이름은 그대로 둔다. 바꿀 것이 없으면 {}.
- 표지 로고·작성자·쪽 머리글·면책·준법 고지(disclaimer)는 섹션으로 만들지 않는다. 사이드바 차트는 그 쪽 첫 섹션(보통 요약)에 둔다.
- 여러 쪽에 이어지는 같은 섹션은 하나로. 대상마다 되풀이되는 소제목(예: '기업명(티커, 투자의견): 요지')은 섹션 하나로 묶고 repeat 에 대상, guide 에 소제목 꼴을 적는다.
- assets 에는 받은 표·차트 id 를 모두 한 번씩 적는다."""

Progress = Callable[[int, int], Awaitable[None]]


def _json(text: str) -> Optional[Dict[str, Any]]:
    t = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M)
    m = re.search(r"\{[\s\S]*\}", t)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except ValueError:
        return None


async def _ask(llm: Any, content: Any, max_tokens: int, effort: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """한 번 묻고, 빈 답·JSON 아님이면 출력 상한을 늘려 한 번 더(추론 모델은 상한이 작으면 빈 답을 낸다).
    effort = 생각 길이(기본 = 모델 기본). 쪽 읽기는 끄거나 줄이면 차트 종류·위치(box)·묶음 머리가 틀린다(2026-10-29 실측) — 기본으로 둔다."""
    for tokens in (max_tokens, int(max_tokens * 1.6)):
        try:
            res = await llm.complete("chat", ChatParams(messages=[{"role": "user", "content": content}], temperature=0.1, max_tokens=tokens, timeout_s=240, reasoning_effort=effort))
        except Exception:  # noqa: BLE001 — 그 쪽은 건너뛴다
            logger.exception("format analysis call failed")
            continue
        out = _json(getattr(res, "content", "") or "")
        if out:
            return out
    return None


# ── PDF: 쪽 그림 → VL ─────────────────────────────────────────────────────

def pick_pages(total: int, limit: int = PAGE_MAX) -> List[int]:
    """읽을 쪽(0부터) — limit 쪽 이하면 전부. 넘으면 앞 두 쪽(표지·요약)·뒤 두 쪽(재무표·고지) + 가운데를 고르게 —
    앞쪽만 읽으면 뒤의 장(투자포인트·밸류에이션·리스크)이 양식에서 빠진다(기업분석 27쪽 샘플)."""
    if total <= limit:
        return list(range(total))
    ends = [0, 1, total - 2, total - 1]
    n = limit - len(ends)
    lo, hi = 2, total - 3
    mid = [lo + round(k * (hi - lo) / (n - 1)) for k in range(n)] if n > 1 else [lo]
    return sorted(set(ends + mid))


def pdf_pages(path: str | Path) -> List[Dict[str, Any]]:
    """고른 쪽(pick_pages) → [{page, png, text}] (text = 글자층, 없으면 빈 문자열)."""
    import fitz  # PyMuPDF

    out: List[Dict[str, Any]] = []
    doc = fitz.open(str(path))
    try:
        for i in pick_pages(len(doc)):
            page = doc[i]
            out.append({"page": i + 1, "png": page.get_pixmap(matrix=fitz.Matrix(1.3, 1.3)).tobytes("png"), "text": re.sub(r"[ \t]+", " ", page.get_text("text") or "").strip()[:PAGE_TEXT_MAX]})
        total = len(doc)
    finally:
        doc.close()
    for p in out:
        p["total"] = total
    return out


async def _read_page(llm: Any, p: Dict[str, Any]) -> Dict[str, Any]:
    text = PAGE_PROMPT + (f"\n\n이 쪽의 글자층(표기를 정확히 하는 데만 쓴다):\n{p['text']}" if p["text"] else "")
    content = [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(p["png"]).decode()}}]
    got = await _ask(llm, content, 9000)
    return {"page": p["page"], **(got or {"page_role": "unknown", "blocks": []})}


# ── DOCX: Word 구조 → 한 쪽처럼 ───────────────────────────────────────────

def docx_page(path: str | Path) -> Dict[str, Any]:
    from docx import Document

    from app.templates_import.extract import extract_sample

    sample = extract_sample(path, Path(path).name)
    blocks: List[Dict[str, Any]] = []
    for i, s in enumerate(sample["sections"]):
        blocks.append({"type": "heading", "level": s.get("level") or 1, "text": s["title"]})
        if s.get("guide"):
            blocks.append({"type": "paragraph", "about": s["guide"][:200]})
        for a in sample["assets"]:
            if a.get("section") == i:
                if a["kind"] == "table":
                    rows = a.get("rows") or []
                    head = rows[0] if rows else []
                    blocks.append({"type": "table", "caption": a.get("caption") or "", "stub": head[0] if head else "", "row_count": max(1, len(rows) - 1), "header": [{"group": "", "unit": a.get("unit") or "", "columns": [c]} for c in head[1:]]})
                elif a["kind"] == "chart":
                    ch = a.get("chart") or {}
                    blocks.append({"type": "chart", "caption": a.get("caption") or "", "chart_type": ("barh" if ch.get("horizontal") else "bar") if ch.get("type") == "bar" else ch.get("type") or "other", "series": [{"name": s.get("name")} for s in ch.get("series") or []], "unit": a.get("unit") or ""})
    body = " ".join(p.text.strip() for p in Document(str(path)).paragraphs if len(p.text.strip()) > 40)[:4000]
    return {"page": 1, "page_role": "content", "blocks": blocks, "title": sample.get("title") or "", "body_sample": body}


# ── 묶기 ─────────────────────────────────────────────────────────────────

def _clip(v: Any, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def collect_assets(read: List[Dict[str, Any]], pdf: bool) -> List[Dict[str, Any]]:
    """쪽마다 읽은 표·차트 블록에 id(a1…)를 붙이고 에셋으로(이름은 샘플 제목 — 묶기가 일반 이름으로 바꾼다).
    블록에도 id 를 적어 묶기 LLM 이 섹션·에셋을 id 로 가리킨다. 면책 쪽은 뺀다."""
    out: List[Dict[str, Any]] = []
    for p in read:
        if p.get("page_role") == "disclaimer":
            continue
        for b in p.get("blocks") or []:
            if not isinstance(b, dict) or b.get("type") not in ("table", "chart"):
                continue
            a = block_to_asset(b, f"a{len(out) + 1}", p.get("page") if pdf else None, p.get("caption_style"))
            if a:
                if not pdf:
                    a["source"]["box"] = None
                b["id"] = a["id"]
                out.append(a)
    return out


_SLIM_DROP = ("box", "look", "colors", "grid", "labels", "legend", "source_line", "note")


def _slim(read: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """묶기에 보낼 쪽 읽기 — 위치·겉모양은 빼고(묶기는 이름·구성만 본다) 글을 줄인다."""
    return [{**p, "blocks": [{k: v for k, v in b.items() if k not in _SLIM_DROP} for b in p.get("blocks") or [] if isinstance(b, dict)]} for p in read]


def normalize(raw: Dict[str, Any], fallback_name: str, assets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """묶기 답 + 쪽에서 모은 에셋 → 제안 {name, desc, style, sections:[{id, title, level, guide, slots: []}], assets}."""
    by_id = {a["id"]: a for a in assets}
    merged: Dict[str, str] = {}
    for x in raw.get("assets") or []:
        if not isinstance(x, dict) or str(x.get("id") or "") not in by_id:
            continue
        a = by_id[str(x["id"])]
        same = str(x.get("same_as") or "")
        if same in by_id and same != a["id"] and same not in merged:
            merged[a["id"]] = same
            continue
        apply_rename(a, x.get("rename"))
        a["name"] = _clip(x.get("name"), 80) or a["name"]
        a["desc"] = _clip(x.get("desc"), 200)
    secs = []
    for s in (raw.get("sections") or [])[:40]:
        if not isinstance(s, dict) or not _clip(s.get("title"), 60):
            continue
        sid = f"s{len(secs) + 1}"
        try:
            level = max(1, min(3, int(s.get("level") or 1)))
        except (TypeError, ValueError):
            level = 1
        repeat = _clip(s.get("repeat"), 40)
        guide = _clip(s.get("guide"), 600)
        if repeat and repeat not in guide:
            guide = f"{guide} ({repeat}마다 같은 꼴로 되풀이)".strip()
        for ref in s.get("assets") or []:
            a = by_id.get(merged.get(str(ref), str(ref)))
            if a and not a["sectionId"]:
                a["sectionId"] = sid
        secs.append({"id": sid, "title": _clip(s["title"], 60), "level": level, "guide": guide, "slots": []})
    kept = [a for a in assets if a["id"] not in merged]
    return {"name": _clip(raw.get("name"), 60) or fallback_name, "desc": _clip(raw.get("desc"), 200), "style": str(raw.get("style") or "").strip()[:800], "sections": secs, "assets": kept}


def _rule_proposal(pages: List[Dict[str, Any]], name: str, assets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """묶기가 실패하면 — 쪽마다 읽은 제목을 그대로 섹션으로, 표·차트는 샘플 제목 그대로(일반화 없음)."""
    secs: List[Dict[str, Any]] = []
    for p in pages:
        if p.get("page_role") in ("disclaimer", "cover"):
            continue
        for b in p.get("blocks") or []:
            if b.get("type") == "heading" and (b.get("level") or 1) <= 2:
                secs.append({"title": b.get("text") or "", "level": b.get("level") or 1, "guide": "", "assets": []})
            elif b.get("id") and secs:
                secs[-1]["assets"].append(b["id"])
    for a in assets:
        a["name"] = strip_number(a["source"]["caption"])[:80] or a["name"]
    return normalize({"name": name, "sections": secs}, name, assets)


async def analyze_sample(path: str | Path, file_name: str, llm: Any, progress: Optional[Progress] = None) -> Dict[str, Any]:
    """샘플 → {name, desc, style, sections:[{id, title, level, guide, slots}], assets:[forms.py 모양], pages:{read, total}}."""
    ext = Path(file_name).suffix.lower()
    stem = Path(file_name).stem
    if ext == ".pdf":
        # 글자층이 있는 PDF — 레이아웃(글꼴·색·좌표·표 칸)으로 틀을 뽑는다(양식 2.0, VL 없음·LLM 은 일반화 한 번). 그림 PDF 만 아래 VL 경로
        from app.templates_import.blueprint import build_blueprint

        got = await build_blueprint(str(path), file_name, llm)
        if got is not None:
            if progress:
                await progress(1, 1)
            got["name"] = got.get("name") or stem
            return got
        pages = await asyncio.to_thread(pdf_pages, path)
        if not pages:
            raise ValueError("PDF 에 쪽이 없습니다.")
        total = len(pages)
        sem = asyncio.Semaphore(CONCURRENCY)
        done = 0

        async def one(p: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal done
            async with sem:
                r = await _read_page(llm, p)
            done += 1
            if progress:
                await progress(done, total)
            return r

        read = sorted(await asyncio.gather(*(one(p) for p in pages)), key=lambda r: r["page"])
        pages_total = pages[0]["total"]
        title = ""
    elif ext == ".docx":
        page = await asyncio.to_thread(docx_page, path)
        read, pages_total, title = [page], None, page.get("title") or ""
        if progress:
            await progress(1, 1)
    else:
        raise ValueError("Word(.docx)나 PDF 샘플을 올려 주세요.")
    if not any(r.get("blocks") for r in read):
        raise ValueError("샘플에서 구성을 읽지 못했습니다(모든 쪽이 빈 답). 잠시 뒤 다시 올려 주세요.")
    assets = collect_assets(read, ext == ".pdf")
    head = f"파일 이름: {file_name}" + (f"\n문서 제목: {title}" if title else "")
    raw = await _ask(llm, f"{SYNTH_PROMPT}\n\n{head}\n\n" + json.dumps(_slim(read), ensure_ascii=False)[:60000], 9000)
    out = normalize(raw, stem, assets) if raw and raw.get("sections") else _rule_proposal(read, stem, assets)
    out["pages"] = {"read": len(read), "total": pages_total}
    return out


__all__ = ["analyze_sample", "collect_assets", "docx_page", "normalize", "pdf_pages"]
