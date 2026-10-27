"""NBIM 공개 글(보도자료)을 받아 근거 자료(.md)로 저장 — 워크스페이스의 '서술 근거'(왜 그렇게 됐는지).

  backend/.venv/Scripts/python demo/nbim/fetch_sources.py   → demo/nbim/sources/*.md

원본 반기 보고서 PDF 는 근거로 올리지 않는다 — 작성 결과와 비교할 '정답지'라서.
표준 라이브러리만 쓴다(HTML 에서 본문 문단만 뽑는다).
"""
from __future__ import annotations

import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "sources"
SOURCES = [
    {
        "file": "NBIM_2025상반기_결과_보도자료.md",
        "title": "NBIM 보도자료 — 2025년 상반기 운용 결과",
        "date": "2025-08",
        "url": "https://www.nbim.no/en/news-and-insights/the-press/press-releases/2025/the-result-is-driven-by-good-returns-in-the-stock-market-particularly-in-the-financial-sector/",
    },
]


class _Text(HTMLParser):
    """<main> 안의 제목·문단만(메뉴·바닥글 제외)."""

    def __init__(self) -> None:
        super().__init__()
        self.depth_main = 0
        self.tag = ""
        self.buf: list[str] = []
        self.blocks: list[str] = []
        self.done = False  # 보도 본문 뒤(담당자 연락처·보고서 바로가기)는 받지 않는다

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.depth_main += 1
        if self.depth_main and not self.done and tag in ("h1", "h2", "h3", "p", "li"):
            self.tag, self.buf = tag, []

    def handle_endtag(self, tag):
        if self.depth_main and tag == self.tag:
            text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
            if tag in ("h2", "h3") and re.search(r"press contact|view the report|contact", text, re.I):
                self.done, self.tag = True, ""
                return
            if text and not (tag == "li" and len(text) < 30):  # 짧은 목록 = 경로·메뉴(Home › News …)
                self.blocks.append(("## " if tag in ("h1", "h2", "h3") else "- " if tag == "li" else "") + text)
            self.tag = ""
        if tag == "main":
            self.depth_main -= 1

    def handle_data(self, data):
        if self.tag:
            self.buf.append(data)


def fetch(src: dict) -> Path:
    req = urllib.request.Request(src["url"], headers={"User-Agent": "Mozilla/5.0 (evidence-desk demo)"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="replace")
    p = _Text()
    p.feed(html)
    body = "\n\n".join(p.blocks)
    if len(body) < 200:
        raise RuntimeError(f"본문을 찾지 못했습니다: {src['url']}")
    OUT.mkdir(exist_ok=True)
    path = OUT / src["file"]
    path.write_text(f"# {src['title']}\n\n출처: Norges Bank Investment Management, {src['url']} ({src['date']})\n\n{body}\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    for s in SOURCES:
        path = fetch(s)
        print(path, len(path.read_text(encoding="utf-8")), "자")
    sys.exit(0)
