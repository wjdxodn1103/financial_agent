"""출처 토큰 — 리포트 본문에 저장되는 인용 표지.

  저장 형태: `[@<docId 16자>#<청크 id>]`  예) "영업이익은 전년 대비 12% 늘었다[@3fa1…c2#p14]."
  작성 모델에게는 `[S3]` 같은 짧은 번호를 보여 주고(search_tool.SourceBook), 받은 본문의 번호를 이 토큰으로 바꿔 저장한다.
  토큰이 곧 근거 앵커다 — 근거 보기는 이 청크를 그대로 연다(OP 는 판정 결과에 앵커를 따로 남겼다).

화면·내보내기에서는 문서마다 번호를 매겨 `[1]`, `[1, 3]` 으로 렌더하고(render), 끝에 "참고 자료" 목록을 붙인다.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Tuple

TOKEN = re.compile(r"\[@([0-9a-f]{16})#([A-Za-z0-9_-]+)\]")
_GROUP = re.compile(r"(?:\s*\[@[0-9a-f]{16}#[A-Za-z0-9_-]+\])+")
# 마침표 뒤에 붙은 토큰은 마침표 앞으로("…늘었다.[@x#p1]" → "…늘었다[@x#p1].") — 문장 경계가 토큰에 걸리지 않게
_AFTER_PUNCT = re.compile(r"([.!?。])((?:\s*\[@[0-9a-f]{16}#[A-Za-z0-9_-]+\])+)")
_MARKER = re.compile(r"\[\d+(?:,\s*\d+)*\]")
_SENT_SPLIT = re.compile(r"(?<=[.!?。])\s+|\n+")


def tokens(text: str) -> List[Tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in TOKEN.finditer(text or "")]


def token_doc_ids(text: str) -> List[str]:
    return list(dict.fromkeys(d for d, _c in tokens(text)))


def normalize(text: str) -> str:
    return _AFTER_PUNCT.sub(lambda m: m.group(2).lstrip() + m.group(1), text or "")


def strip_tokens(text: str) -> str:
    return re.sub(r"[ \t]+([.,!?。])", r"\1", _GROUP.sub("", text or ""))


def _sentence_at(text: str, at: int) -> str:
    start = 0
    for m in _SENT_SPLIT.finditer(text):
        if m.start() >= at:
            return _MARKER.sub("", text[start : m.start()]).strip()
        start = m.end()
    return _MARKER.sub("", text[start:]).strip()


def render(text: str, number_of: Callable[[str], int]) -> Tuple[str, List[Dict[str, Any]]]:
    """토큰 → `[n, m]` 표기. spans = [{start, end, anchors: [{docId, chunk, n}], sentence}] (표기 위치는 렌더된 글 기준).
    number_of(docId) 는 리포트 전체에서 처음 나온 순서로 번호를 준다(view.build_report_view)."""
    out: List[str] = []
    spans: List[Dict[str, Any]] = []
    pos = 0
    length = 0
    for m in _GROUP.finditer(text or ""):
        head = text[pos : m.start()]
        out.append(head)
        length += len(head)
        pairs = list(dict.fromkeys(TOKEN.findall(m.group(0))))
        nums = sorted({number_of(d) for d, _c in pairs})
        marker = "[" + ", ".join(str(n) for n in nums) + "]"
        spans.append({"start": length, "end": length + len(marker), "anchors": [{"docId": d, "chunk": c, "n": number_of(d)} for d, c in pairs]})
        out.append(marker)
        length += len(marker)
        pos = m.end()
    out.append((text or "")[pos:])
    rendered = "".join(out)
    for sp in spans:
        sp["sentence"] = _sentence_at(rendered, sp["start"])
    return rendered, spans
