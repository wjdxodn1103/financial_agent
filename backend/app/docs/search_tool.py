"""자료 검색 도구 `search_documents` — 채팅(질의응답)과 작성기(섹션 작성 중)가 같이 쓴다.

OP 의 `search_references` 와 같은 방식(모델이 근거 문단을 먼저 찾고, 뒷받침될 때만 인용)이지만 표지가 다르다:
결과 문단마다 `[S1]`, `[S2]` … 번호를 붙여 돌려주고, 모델은 그 번호를 문장 끝에 단다. 번호 ↔ (문서, 청크) 대응은
SourceBook 이 들고 있다가 본문을 저장할 때 `[@docId#청크]` 토큰으로 바꾼다(citations.py). 돌려주지 않은 번호는 지운다.
검색 자체는 LLM 0회(BM25 + 벡터, store.search_docs).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.docs.chunk import preview
from app.docs.store import doc_label, doc_language, load_meta, search_cards, search_docs

SEARCH_TOOL_NAME = "search_documents"
SEARCH_K = 6
SEARCH_PER_DOC = 2
SNIPPET_CHARS = 700
# 모델이 쓰는 출처 번호 표지 — [S3] 외에 【S3】·〔S3〕·［S3］·(S3), 묶음 [S3, S5] 도 받는다(nemotron 이 【S2】 로 쓴 실측)
S_REF = re.compile(r"[\[【〔［(]\s*S\s*\d+(?:\s*[,，、]\s*S?\s*\d+)*\s*[\]】〕］)]")
S_REF_RUN = re.compile(r"(?:\s*" + S_REF.pattern + r")+")

SEARCH_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": SEARCH_TOOL_NAME,
        "description": (
            "업로드한 자료(사업보고서·IR·리포트·규정 등)에서 근거 문단을 찾는다. 수치·사실을 말하거나 쓰기 전에 부른다. "
            "결과 문단마다 [S번호] 가 붙어 있다 — 그 문단이 문장을 실제로 뒷받침할 때만 문장 끝에 그 번호를 단다. "
            "결과가 '근거 없음' 이면 그 내용은 쓰지 않거나 '자료에서 확인되지 않음' 이라고 밝힌다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "찾을 내용(한국어 한 문장 또는 핵심어). 예: '2024년 연결 기준 영업이익과 증감 이유'"},
                "query_en": {"type": "string", "description": "같은 내용의 영어 질의 — 자료 목록에 '영문' 표시 자료가 있으면 꼭 같이 쓴다(영문 문단을 더 정확히 찾는다)"},
                "document": {"type": "string", "description": "특정 문서 안에서만 찾을 때 그 문서 번호(D1, D2 …) 또는 이름 일부·설명(선택)"},
                "kind": {"type": "string", "enum": ["table", "prose"], "description": "표 문단만(table) 또는 본문만(prose) — 수치 표를 찾을 때 table(선택)"},
                "year": {"type": "integer", "description": "이 연도가 나오는 문단을 앞으로(예: 2024 — 빼지는 않는다, 기간이 분명할 때, 선택)"},
                "include_disclaimer": {"type": "boolean", "description": "면책·법적 고지 문단도 찾을지(기본 false — 고지 내용을 물을 때만 true)"},
            },
            "required": ["query"],
        },
    },
}


class SourceBook:
    """한 번의 작성(또는 한 채팅 턴)에서 모델에게 보여 준 문단의 번호표."""

    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []
        self._by_key: Dict[Tuple[str, str], int] = {}

    def add(self, doc_id: str, chunk: Dict[str, Any], label: str) -> int:
        key = (doc_id, str(chunk.get("id")))
        if key in self._by_key:
            return self._by_key[key]
        n = len(self.items) + 1
        self.items.append({"n": n, "docId": doc_id, "chunk": chunk.get("id"), "page": chunk.get("page"), "label": label, "text": chunk.get("text") or "", "heading": chunk.get("heading")})
        self._by_key[key] = n
        return n

    def get(self, n: int) -> Optional[Dict[str, Any]]:
        return self.items[n - 1] if 1 <= n <= len(self.items) else None

    def to_tokens(self, text: str) -> Dict[str, Any]:
        """본문의 [S3]·[S3, S5]·[S3][S5] → [@docId#청크] 토큰. 번호표에 없는 번호는 지운다. → {"text", "used": [n…], "unknown": [n…]}"""
        used: List[int] = []
        unknown: List[int] = []

        def one(n: int) -> str:
            it = self.get(n)
            if it is None:
                unknown.append(n)
                return ""
            used.append(n)
            return f"[@{it['docId']}#{it['chunk']}]"

        def group(m: re.Match) -> str:
            return "".join(one(int(x)) for x in re.findall(r"(\d+)", m.group(0)))

        out = S_REF.sub(group, text or "")
        return {"text": out, "used": list(dict.fromkeys(used)), "unknown": list(dict.fromkeys(unknown))}

    def label_of(self, n: int) -> str:
        it = self.get(n)
        if not it:
            return ""
        return f"{it['label']}, p.{it['page']}" if it.get("page") else it["label"]


def doc_index_lines(doc_ids: Sequence[str]) -> List[str]:
    """프롬프트용 문서 목록 — `D1. 제목 (문서 종류, 날짜, 영문)`. 도구의 document 인자가 이 번호를 받는다. '영문' = 검색에 query_en 을 같이 쓸 자료."""
    out: List[str] = []
    for i, did in enumerate(doc_ids, 1):
        m = load_meta(did)
        if not m:
            continue
        c = m.get("card") or {}
        extra = ", ".join(x for x in (c.get("docType"), c.get("date"), c.get("issuer"), "영문" if doc_language(did) == "en" else "") if x)
        line = f"D{i}. {doc_label(m, did)}" + (f" ({extra})" if extra else "")
        if c.get("oneLine"):
            line += f" — {c['oneLine']}"
        out.append(line)
    return out


def _pick_docs(doc_ids: Sequence[str], spec: str) -> List[str]:
    spec = (spec or "").strip()
    if not spec:
        return list(doc_ids)
    m = re.fullmatch(r"[Dd]\s*(\d+)", spec)
    if m:
        i = int(m.group(1)) - 1
        return [doc_ids[i]] if 0 <= i < len(doc_ids) else list(doc_ids)
    low = spec.lower()
    hit = [d for d in doc_ids if low in (doc_label(load_meta(d), d) + " " + ((load_meta(d) or {}).get("fileName") or "")).lower()]
    if hit:
        return hit
    # 이름이 안 맞으면 문서 카드(제목·종류·날짜·요약)로 뜻이 가까운 문서 몇 개
    near = [d for d, _s in search_cards(doc_ids, spec, k=3)]
    return near or list(doc_ids)


def run_search(book: SourceBook, doc_ids: Sequence[str], args: Dict[str, Any], k: int = SEARCH_K) -> Dict[str, Any]:
    """→ {"text": 모델에게 돌려줄 결과, "hits": n}. 동기 함수(스레드에서 부른다)."""
    qs = [q.strip() for q in (str(args.get("query") or ""), str(args.get("query_en") or "")) if q and q.strip()]
    if not qs:
        return {"text": "질의가 비어 있습니다 — query 에 찾을 내용을 넣어 다시 부르세요.", "hits": 0}
    if not doc_ids:
        return {"text": "근거 없음 — 업로드한 자료가 없습니다. 오른쪽 '자료' 패널에서 파일을 올려 달라고 안내하세요.", "hits": 0}
    scope = _pick_docs(doc_ids, str(args.get("document") or ""))
    per = SEARCH_PER_DOC if len(scope) > 1 else k
    kind = args.get("kind") if args.get("kind") in ("table", "prose") else None
    try:
        years = [int(args["year"])] if args.get("year") not in (None, "") else None
    except (TypeError, ValueError):
        years = None
    excl = not bool(args.get("include_disclaimer"))
    hits = search_docs(scope, qs, k=k, per_doc=per, kind=kind, years=years, exclude_disclaimer=excl)
    relaxed = ""
    if len(hits) < 2 and kind:
        # 조건이 너무 좁았다 — 표/본문 조건을 풀고 다시(연도 가산점·면책 빼기는 그대로)
        hits = search_docs(scope, qs, k=k, per_doc=per, years=years, exclude_disclaimer=excl)
        relaxed = f"\n[내부 메모] kind={kind} 에 맞는 문단이 적어 조건 없이 찾았다."
    if not hits:
        return {"text": "근거 없음 — 이 내용을 뒷받침하는 문단이 자료에 없습니다. 지어내지 말고 '자료에서 확인되지 않음' 으로 다룬다.", "hits": 0}
    lines: List[str] = []
    seen_before = len(book.items)
    for h in hits:
        meta = load_meta(h["docId"])
        label = doc_label(meta, h["docId"])
        n = book.add(h["docId"], h["chunk"], label)
        where = f"p.{h['chunk'].get('page')}" if h["chunk"].get("page") else f"문단 {h['chunk'].get('id')}"
        head = f" · {h['chunk']['heading']}" if h["chunk"].get("heading") else ""
        table = h["chunk"].get("kind") == "table"
        text = h["chunk"].get("text") or ""
        # 표는 줄 구조를 지킨다(행이 한 줄로 뭉치면 숫자가 어느 항목인지 모른다)
        body = (text[:SNIPPET_CHARS] + ("…" if len(text) > SNIPPET_CHARS else "")) if table else preview(text, SNIPPET_CHARS)
        lines.append(f"[S{n}] {label}, {where}{head}{' · 표' if table else ''}\n{body}")
    # 같은 질의를 되풀이해도 새 문단이 없으면 그렇게 알려 검색을 멈추게 한다(작성기가 거의 같은 질의를 4번 부르던 실측)
    if len(book.items) == seen_before:
        refs = ", ".join(f"[S{book.add(h['docId'], h['chunk'], '')}]" for h in hits)
        return {"text": f"새 문단 없음 — 이미 받은 {refs} 와 같다.\n[내부 메모] 비슷한 질의를 되풀이하지 말고, 가진 자료로 쓰거나 그 항목은 '자료에서 확인되지 않음'으로 처리한다.", "hits": 0}
    # 영문 자료가 범위에 있는데 영문 질의가 없었으면 다음 검색부터 같이 쓰게 알린다(영문 문단은 영문 질의로 더 정확히 찾힌다)
    en_memo = "\n[내부 메모] 영문 자료가 있다 — 다음 검색부터 query_en 에 같은 내용의 영어 질의도 넣는다." if not str(args.get("query_en") or "").strip() and any(doc_language(d) == "en" for d in scope) else ""
    # 첫 줄은 화면 "작업 과정" 요약으로도 쓰인다(loop._summary) — 지시문은 둘째 줄부터
    return {"text": f"검색 결과 {len(lines)}개(관련도 순)\n[내부 메모] 문장을 실제로 뒷받침하는 문단의 [S번호] 만 문장 끝에 단다.{en_memo}{relaxed}\n\n" + "\n\n".join(lines), "hits": len(lines)}
