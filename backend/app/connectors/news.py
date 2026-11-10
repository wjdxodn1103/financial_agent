"""뉴스 제목 수집 — 구글 뉴스 RSS 검색(키 없음). 기사 본문은 가져오지 않는다: 제목·언론사·발행일·링크만 자료 한 건으로 둔다.
대시보드 '관련 뉴스·리포트' 탭과 아침 증시 요약의 '시장 리뷰'(원인 서술의 근거)가 이 자료를 쓴다. 같은 기사(링크)는 한 번만 넣는다.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from xml.etree import ElementTree as ET

import httpx

from app.docs.store import load_meta

log = logging.getLogger(__name__)
FEED = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
DOC_TYPE = "뉴스·보도자료"


def search(query: str, days: int = 7, limit: int = 10) -> List[Dict[str, str]]:
    """→ [{title, press, date, url}] 최신순. 구글 뉴스 제목은 '제목 - 언론사' 꼴이라 언론사를 떼어 낸다."""
    url = FEED.format(q=quote(f"{query} when:{max(1, days)}d"))
    r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (news collector)"}, timeout=25, follow_redirects=True)
    r.raise_for_status()
    out: List[Dict[str, str]] = []
    for it in ET.fromstring(r.text).iter("item"):
        f = {c.tag.rsplit("}", 1)[-1]: (c.text or "").strip() for c in it}
        title, press = f.get("title", ""), f.get("source", "")
        if press and title.endswith(f" - {press}"):
            title = title[: -len(press) - 3].strip()
        try:
            day = parsedate_to_datetime(f.get("pubDate", "")).date().isoformat()
        except Exception:  # noqa: BLE001
            day = ""
        if title and f.get("link"):
            out.append({"title": re.sub(r"\s+", " ", title), "press": press, "date": day, "url": f["link"]})
    out.sort(key=lambda x: x["date"], reverse=True)
    seen, uniq = set(), []
    for x in out:  # 같은 제목(통신사 받아쓰기)은 하나만
        k = re.sub(r"\W", "", x["title"])[:24]
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    return uniq[:limit]


def collect(workspace_id: str, query: str, company: str = "", topic: str = "", days: int = 7, limit: int = 8, have: Optional[List[str]] = None, added_by: str = "") -> List[str]:
    """검색 결과를 워크스페이스 자료로 넣는다 → 새로 넣은 문서 id. have = 이미 있는 자료 id(같은 링크는 건너뛴다)."""
    from app.pipeline.docs import add_text

    known = {((load_meta(d) or {}).get("snapshot") or {}).get("url") for d in have or []}
    cut = (date.today() - timedelta(days=days + 1)).isoformat()
    made: List[str] = []
    for it in search(query, days, limit * 2):
        if len(made) >= limit:
            break
        if it["url"] in known or (it["date"] and it["date"] < cut):
            continue
        text = f"# {it['title']}\n\n발행: {it['date']} · {it['press']}\n원문: {it['url']}\n\n(기사 제목만 수집 — 본문은 원문 링크에서 확인)"
        try:
            did = add_text(text, f"뉴스_{it['press'][:12]}_{it['date']}_{it['title'][:40]}",
                           card={"title": it["title"][:200], "docType": DOC_TYPE, "date": it["date"], "issuer": it["press"], "company": company, "oneLine": topic or query},
                           snapshot={"connector": "news", "url": it["url"], "query": query, "publishedAt": it["date"], "topic": topic},
                           scope="workspace", workspace_id=workspace_id, added_by=added_by)
            made.append(did)
        except Exception:  # noqa: BLE001
            log.exception("news add failed: %s", it["title"][:60])
    return made
