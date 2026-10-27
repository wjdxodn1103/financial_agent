"""섹션 작성기 — OP `paper/agent/writer.py::write_section` 의 골격만 옮겼다.

흐름(on_stage 로 화면 상태 줄에 단계를 알린다):
  writer.retrieve  항목 질의(template.queries)로 미리 찾기 — LLM 0회, 결과는 [S번호] 로 브리프에 싣는다
  writer.generate  작성 모델 호출. 모델은 search_documents 도구로 근거를 더 찾을 수 있다(라운드 상한, 넘으면 본문 강제)
  writer.calc      calculate 도구 — 증감률·비율은 코드가 원장 값(F번호)으로 계산하고 계산식을 남긴다
  writer.cite      본문의 [S번호] → [@docId#청크] 토큰(번호표에 없는 번호는 지움)
수치 점검은 결정적: 출처 없는 수치 문장 + 본문 숫자 ↔ 근거 원장·계산 결과 대조(ledger_brief.number_checks).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.agent.ledger_brief import CALC_TOOL_NAME, CALC_TOOL_SCHEMA, LedgerBook, number_checks, select_figures, used_calcs
from app.agent.prompts import load, setup_lines
from app.agent.session import Doc, find_section, written_sections
from app.agent.template import item_of, report_type
from app.docs.citations import normalize, tokens
from app.docs.search_tool import SEARCH_TOOL_NAME, SEARCH_TOOL_SCHEMA, SourceBook, doc_index_lines, run_search
from app.docs.chunk import preview
from app.docs.store import doc_label, load_meta, search_docs
from app.formats.brief import block_brief_lines
from app.formats.registry import is_format
from app.llm.base import ChatParams
from app.records.service import notes_lines

log = logging.getLogger(__name__)

WRITER_SEARCH_ROUNDS = 4
PRESEARCH_PER_QUERY = 3
PRESEARCH_MAX = 10
WRITER_MAX_TOKENS = 8000  # 추론 모델은 reasoning 토큰이 같은 상한을 쓴다 — 넉넉히
_NUMBER_SENT = re.compile(r"\d[\d,.]*\s*(?:%|%p|억|조|만|원|달러|배|bp|명|개|건|톤)")
_SENT_SPLIT = re.compile(r"(?<=[.!?。])\s+|\n+")


def _tools_unsupported(err: Exception) -> bool:
    s = str(err).lower()
    return "tool" in s or "function" in s or "(400)" in s


def _queries(doc: Doc, title: str, item: Optional[Dict[str, Any]]) -> List[str]:
    subject = ((doc.get("setup") or {}).get("subject") or "").strip()
    qs = [q.replace("{company}", subject).strip() for q in (item or {}).get("queries") or []]
    qs.append(f"{subject} {title}".strip())
    return [q for q in dict.fromkeys(qs) if q]


def presearch(book: SourceBook, doc_ids: Sequence[str], queries: Sequence[str]) -> List[str]:
    """질의마다 상위 몇 문단을 번호표에 올리고 브리프 줄로(겹치면 한 번만). 동기 — 스레드에서 부른다."""
    lines: List[str] = []
    seen: set = set()
    for q in queries:
        for h in search_docs(doc_ids, q, k=PRESEARCH_PER_QUERY, per_doc=2, exclude_disclaimer=True):
            key = (h["docId"], h["chunk"].get("id"))
            if key in seen:
                continue
            seen.add(key)
            label = doc_label(load_meta(h["docId"]), h["docId"])
            n = book.add(h["docId"], h["chunk"], label)
            where = f"p.{h['chunk'].get('page')}" if h["chunk"].get("page") else f"문단 {h['chunk'].get('id')}"
            text = h["chunk"].get("text") or ""
            body = text[:700] if h["chunk"].get("kind") == "table" else preview(text, 700)
            lines.append(f"[S{n}] {label}, {where}\n{body}")
            if len(lines) >= PRESEARCH_MAX:
                return lines
    return lines


def _other_sections(doc: Doc, step: str) -> List[str]:
    out = []
    for s in written_sections(doc):
        if s["step"] == step:
            continue
        first = re.split(r"(?<=[.!?。])\s+", re.sub(r"\[@[^\]]+\]", "", s["content"]).strip())[:2]
        out.append(f"- {s['title']}: {' '.join(first)[:240]}")
    return out


def build_brief(
    doc: Doc,
    step: str,
    *,
    doc_ids: Sequence[str],
    material: List[str],
    instruction: Optional[str],
    user_info: Dict[str, str],
    previous_text: Optional[str],
    ledger: Sequence[str] = (),
    notes: Sequence[str] = (),
    block_lines: Sequence[str] = (),
) -> str:
    sec = find_section(doc, step) or {}
    title = sec.get("title") or ""
    item = item_of((sec.get("covers") or [""])[0], doc.get("reportType")) if sec.get("covers") else None
    t = report_type(doc.get("reportType"))
    labels = {f["key"]: f["label"] for f in (item or {}).get("inputs") or []}
    blocks = [
        "## 리포트\n" + "\n".join([f"유형: {t['title']}", *setup_lines(doc)]),
        "## 이번에 쓸 섹션\n" + f"제목: {title}\n" + (f"작성 지침: {item['desc']}" if item else "작성 지침: 사용자가 만든 섹션 — 제목과 요청 사항에 맞춰 쓴다."),
    ]
    if sec.get("guide"):
        blocks.append("## 양식 안내문(등록한 DOCX 양식이 이 섹션에 요구하는 내용 — 따른다)\n" + sec["guide"])
    if t.get("style"):
        blocks.append("## 문서 스타일(문서 양식 — 문체·형식을 따른다)\n" + t["style"])
    described = [x for x in sec.get("slots") or [] if not x.get("templateId") and x.get("kind") in ("table", "chart")]
    if described:
        blocks.append(
            "## 이 섹션의 표·그림 자리(문서 양식 — 본문에서 처음 언급할 때 <표>·<그림> 제목으로 가리키고 핵심 숫자만 쓴다. 표·그림 자체는 리서치에서 만들어 넣는다)\n"
            + "\n".join(f"- {'표' if x['kind'] == 'table' else '그림'}: {x['title']}" + (f" — {x['desc']}" if x.get("desc") else "") for x in described)
        )
    filled = [f"- {labels.get(k, k)}: {v.strip()}" for k, v in user_info.items() if isinstance(v, str) and v.strip()]
    if filled:
        blocks.append("## 사용자 입력(사용자 판단 — 그대로 근거로 인정)\n" + "\n".join(filled))
    if instruction:
        blocks.append("## 요청 사항\n" + instruction.strip())
    if notes:
        blocks.append("## 팀 기록(확정된 결정·지시·방침 — 지킨다. 본문에 기록 자체를 인용하지는 않는다)\n" + "\n".join(notes))
    others = _other_sections(doc, step)
    if others:
        blocks.append("## 이미 쓴 다른 섹션(겹치지 않게, 결론이 어긋나지 않게)\n" + "\n".join(others))
    docs = doc_index_lines(doc_ids)
    blocks.append("## 자료 목록(search_documents 의 document 인자는 D번호)\n" + ("\n".join(docs) if docs else "없음"))
    if block_lines:
        blocks.append(
            "## 이 섹션 뒤에 붙는 표·그림(시스템이 붙인다 — 표를 글로 옮기지 말고, 결론에 필요한 핵심 숫자만 이 표기 그대로 쓰고 [S번호] 를 단다. "
            "'(= …)' 한국어 단위 표기가 있으면 본문에는 그 표기를 쓴다. 처음 언급할 때 <표 n>·<그림 n> 으로 가리킨다)\n" + "\n".join(block_lines)
        )
    if ledger:
        blocks.append(
            "## 근거 원장(자료의 표에서 코드가 뽑은 수치 — 숫자는 이 표기 그대로 쓰고 [S번호] 를 단다. 증감률·비율은 calculate 도구로 F번호를 넣어 계산한다)\n"
            + "\n".join(ledger)
        )
    blocks.append("## 미리 찾은 자료\n" + ("\n\n".join(material) if material else "없음 — 필요한 근거는 search_documents 로 찾는다. 자료가 없으면 근거 없는 수치를 쓰지 않는다."))
    if previous_text:
        blocks.append("## 지금 본문(이것을 요청 사항에 맞게 고쳐 쓴다 — 근거 표지는 [S번호] 로 다시 단다)\n" + re.sub(r"\[@[^\]]+\]", "", previous_text))
    # 전문가용 — 확인 카드 대신 작성 뒤 '왜 이렇게 썼는지'를 사용자에게 설명한다(코드가 떼어 낸다)
    out = (
        "## 출력\n섹션 본문만 쓴다. 근거 문장 끝에 [S번호]."
        f"\n본문 뒤에 빈 줄을 두고 `{MEMO_TAG}` 로 시작하는 2~4문장: 이 섹션을 이렇게 구성한 이유, 강조한 점, 자료에 없어 쓰지 못한 것. 메모에는 [S번호] 를 달지 않는다."
    )
    blocks.append(out)
    return "\n\n".join(blocks)


MEMO_TAG = "[작성 메모]"
_MEMO = re.compile(r"\n*\s*\[작성\s*메모\]\s*:?\s*([\s\S]*)$")


def split_memo(text: str) -> tuple[str, str]:
    """작성 모델 출력 → (본문, 작성 메모). 메모가 없으면 빈 문자열."""
    m = _MEMO.search(text or "")
    if not m:
        return text, ""
    memo = re.sub(r"\[S\d+\]|\[@[^\]]+\]", "", m.group(1)).strip()
    return text[: m.start()].rstrip(), re.sub(r"\s+", " ", memo)


async def _generate_with_search(
    llm: Any, system_text: str, brief: str, book: SourceBook, doc_ids: Sequence[str], on_stage: Optional[Callable[[str], None]], lb: Optional[LedgerBook] = None
) -> Dict[str, Any]:
    """작성 모델을 부르되 search_documents 호출을 받아 검색을 돌려주며 본문이 나올 때까지 잇는다(OP 그대로).
    도구를 못 받는 모델(400)이면 도구 없이 한 번 더."""
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_text}, {"role": "user", "content": brief}]
    use_tools = bool(doc_ids)
    calls = 0
    round_ = 0
    res: Any = None
    last_text = ""
    nudged = False
    for _attempt in range(WRITER_SEARCH_ROUNDS + 3):  # 상한 — tool_choice="none" 을 무시하고 계속 도구를 부르는 모델이 있다
        force_write = use_tools and round_ >= WRITER_SEARCH_ROUNDS
        params = ChatParams(
            messages=messages,
            tools=([SEARCH_TOOL_SCHEMA, CALC_TOOL_SCHEMA] if lb is not None and lb.refs else [SEARCH_TOOL_SCHEMA]) if use_tools else None,
            tool_choice=("none" if force_write else "auto") if use_tools else None,
            temperature=0.3,
            max_tokens=WRITER_MAX_TOKENS,
            reasoning_effort="low",
            timeout_s=600,
        )
        try:
            res = await llm.collect("writer", params)
        except Exception as err:  # noqa: BLE001
            if use_tools and round_ == 0 and _tools_unsupported(err):
                log.info("[writer] tools unsupported — retry without tools: %s", str(err)[:120])
                use_tools = False
                continue
            raise
        tcs = res.tool_calls or []
        # 검색을 끝내야 하는데 본문이 비었거나 여전히 도구를 부르면(2026-10-08 nemotron 실측: 강제 라운드 빈 본문) 도구를 떼고 한 번 더 조른다
        if (force_write or not use_tools) and (tcs or not (res.content or "").strip()) and not nudged:
            nudged = True
            use_tools = False
            messages.append({"role": "user", "content": "[내부 메모] 검색은 끝났다. 지금까지 받은 자료([S번호])만으로 섹션 본문을 지금 출력한다. 자료에 없는 항목은 '자료에서 확인되지 않음'으로 처리한다."})
            continue
        if not tcs or not use_tools:
            break
        round_ += 1
        if on_stage:
            on_stage("writer.search")
        if res.content:
            last_text = res.content
        messages.append({"role": "assistant", "content": res.content or None, "tool_calls": tcs})
        for tc in tcs:
            fn = tc.get("function") or {}
            name = re.sub(r"<\|[\s\S]*$", "", fn.get("name") or "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            if name == SEARCH_TOOL_NAME and isinstance(args, dict):
                calls += 1
                result = (await asyncio.to_thread(run_search, book, doc_ids, args))["text"]
            elif name == CALC_TOOL_NAME and isinstance(args, dict) and lb is not None:
                if on_stage:
                    on_stage("writer.calc")
                result = lb.calculate(args)
            else:
                result = f"없는 도구: {name}. 쓸 수 있는 도구는 {SEARCH_TOOL_NAME}·{CALC_TOOL_NAME} 뿐이다. 더 필요 없으면 본문을 출력한다."
            messages.append({"role": "tool", "tool_call_id": tc.get("id") or f"call_{calls}", "content": result})
    content = (res.content or "").strip() if res is not None else ""
    return {"content": content or last_text.strip(), "finish": getattr(res, "finish_reason", None), "calls": calls}


_HEADING_LINE = re.compile(r"^\s*(#{1,6}\s+.*|\*\*[^*\n]{1,40}\*\*\s*:?)\s*$")


def tidy(content: str, title: str) -> str:
    """모델이 붙이는 섹션 제목·코드펜스·텍스트형 도구 호출을 떼고 공백을 정리한다."""
    t = re.sub(r"<tool_call>.*?(?:</tool_call>|$)", "", content or "", flags=re.S)
    t = re.sub(r"^```[a-z]*\s*|\s*```$", "", t.strip())
    lines = t.split("\n")
    while lines and (not lines[0].strip() or _HEADING_LINE.match(lines[0]) or lines[0].strip().strip("#*: ") == title.strip()):
        lines.pop(0)
    t = "\n".join(lines)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def unsourced_number_sentences(content: str) -> List[str]:
    """수치(단위가 붙은 숫자)가 있는데 출처 토큰이 없는 문장 — 확인할 곳으로 카드에 보인다(결정적, LLM 0회)."""
    out: List[str] = []
    for s in _SENT_SPLIT.split(content or ""):
        s = s.strip()
        if s and _NUMBER_SENT.search(re.sub(r"\[@[^\]]+\]", "", s)) and not tokens(s):
            out.append(re.sub(r"\s+", " ", s)[:160])
    return out


async def write_section(
    llm: Any,
    doc: Doc,
    step: str,
    *,
    doc_ids: Sequence[str],
    instruction: Optional[str] = None,
    user_info: Optional[Dict[str, str]] = None,
    previous_text: Optional[str] = None,
    on_stage: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """→ {"content": 토큰이 든 본문, "checks", "warnings"}. 빈 본문이면 RuntimeError."""
    sec = find_section(doc, step)
    if sec is None:
        raise RuntimeError(f"작성 대상 섹션이 없습니다: {step}")
    item = item_of((sec.get("covers") or [""])[0], doc.get("reportType")) if sec.get("covers") else None
    book = SourceBook()
    lb = LedgerBook()
    if on_stage:
        on_stage("writer.retrieve")
    queries = _queries(doc, sec["title"], item)
    ledger = await asyncio.to_thread(select_figures, doc_ids, doc.get("ledgerChoices") or {}, [*queries, sec["title"], instruction or ""], book, lb) if doc_ids else []
    material = await asyncio.to_thread(presearch, book, doc_ids, queries) if doc_ids else []
    notes = notes_lines(doc.get("teamNotes") or [], scope_hint=sec["title"])
    block_lines = await asyncio.to_thread(block_brief_lines, doc, sec, book, lb) if is_format(doc.get("reportType")) else []
    brief = build_brief(doc, step, doc_ids=doc_ids, material=material, instruction=instruction, user_info=user_info or {}, previous_text=previous_text, ledger=ledger, notes=notes, block_lines=block_lines)
    if on_stage:
        on_stage("writer.generate")
    gen = await _generate_with_search(llm, load("writer_system"), brief, book, doc_ids, on_stage, lb)
    body, memo = split_memo(gen["content"])
    content = tidy(body, sec["title"])
    if len(content) < 20:
        raise RuntimeError("작성 모델이 빈 본문을 돌려줬습니다. 같은 요청을 다시 보내 주세요.")
    if on_stage:
        on_stage("writer.cite")
    conv = book.to_tokens(content)
    content = normalize(re.sub(r"[ \t]+\n", "\n", conv["text"]))
    cited = tokens(content)
    warnings: List[str] = []
    if conv["unknown"]:
        warnings.append(f"검색 결과에 없는 출처 번호 {len(conv['unknown'])}개를 지웠습니다.")
    if gen["finish"] == "length":
        warnings.append("출력 길이 상한에 걸려 끝부분이 잘렸을 수 있습니다.")
    unsourced = unsourced_number_sentences(content)
    nums = number_checks(content, lb, [v for v in (user_info or {}).values() if isinstance(v, str)])
    calcs = used_calcs(content, lb.calcs)
    checks = {
        "citations": len(cited),
        "documents": len({d for d, _c in cited}),
        "searchCalls": gen["calls"],
        "presearch": len(material),
        "removedSources": len(conv["unknown"]),
        "unsourcedNumbers": unsourced[:5],
        "mismatchedNumbers": nums["mismatched"],
        "numbersChecked": nums["checked"],
        "numbersMatched": nums["matched"],
        "ledgerShown": len(ledger),
        "calcs": len(calcs),
        "truncated": gen["finish"] == "length",
    }
    return {"content": content, "checks": checks, "warnings": warnings, "calcs": calcs, "memo": memo}
