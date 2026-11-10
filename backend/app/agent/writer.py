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
from app.criteria.prompting import criteria_lines
from app.docs.citations import normalize, tokens
from app.docs.search_tool import SEARCH_TOOL_NAME, SEARCH_TOOL_SCHEMA, SourceBook, doc_index_lines, run_search
from app.docs.chunk import preview
from app.docs.store import doc_label, load_meta, search_docs
from app.formats.brief import block_brief_lines
from app.formats.registry import has_blocks, section_blocks_of, titled
from app.ledger.numbers import find_amounts, korean_hints
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
    from app.formats.blocks import doc_subject

    subject = ((doc.get("setup") or {}).get("subject") or "").strip() or (doc_subject(doc) if doc.get("layout") else "")
    qs = [q.replace("{company}", subject).strip() for q in (item or {}).get("queries") or []]
    qs.append(f"{subject} {title}".strip())
    # 틀 문서의 소제목은 회사마다 다른 주장 한 줄 — 자리 이름(최대 주주·제품 및 매출 구성)으로도 찾는다(주장 글에만 맞는 문단으로 쏠리지 않게)
    if doc.get("layout") and item and item.get("title") and item["title"] != title:
        qs.append(f"{subject} {item['title']}".strip())
    if doc.get("layout") and item and item.get("desc"):
        # 자리 안내 첫 문장('최대주주 및 특수관계인 지분율을 … 정리한다') — 무엇을 찾을지가 들어 있다(같은 자료 안 비슷한 절에 밀리지 않게)
        qs.append(f"{subject} {re.split(r'(?<=다)[.。]|[.。]', item['desc'])[0][:80]}".strip())
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
            hints = korean_hints(body)  # 영문 규모 금액의 한국어 표기(자릿수 환산 실수 방지)
            lines.append(f"[S{n}] {label}, {where}\n{body}" + (f"\n(한국어 금액 표기: {'; '.join(hints)})" if hints else ""))
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


def _pending_sections(doc: Doc, step: str) -> List[str]:
    """아직 안 쓴 다른 섹션의 제목·안내 첫 문장 — 앞 섹션이 뒤 섹션 주제를 미리 쓰지 않게(해외주식 브리핑의 시장 요약이 발표 일정까지 쓰던 것).
    양식 2.0 틀 문서는 _layout_rule 이 같은 장의 소주제 범위를 따로 준다."""
    if doc.get("layout"):
        return []
    out = []
    for s in doc.get("sections") or []:
        if s["step"] == step or s.get("content"):
            continue
        item = item_of((s.get("covers") or [""])[0], doc.get("reportType")) if s.get("covers") else None
        guide = re.split(r"(?<=[.!?。])\s+", str(s.get("guide") or (item or {}).get("desc") or "").strip())[0][:120]
        out.append(f"- {s['title']}" + (f": {guide}" if guide else ""))
    return out


def _layout_rule(doc: Doc, sec: Dict[str, Any]) -> str:
    """양식 2.0 틀 문서 — 이 자리(요약·소주제)의 출력 꼴. 태그는 화면·Word 가 역할로 그린다(report/view.section_blocks)."""
    lay = doc.get("layout")
    if not lay:
        return ""
    rules = lay.get("rules") or {}
    role = sec.get("role")
    if role == "summary":
        n = next((p.get("claims") for p in lay.get("parts") or [] if p.get("role") == "summary"), 3) or 3
        return (f"## 이 자리의 꼴(문서 양식 — 요약 쪽)\n{rules.get('claim') or ''}\n"
                f"출력: 주장 {n}개. 문단마다 첫 줄은 `[제목] 주장 한 줄`(25자 안팎 — 태그는 글자 그대로 `[제목]`, '[실적]' 같은 분류 이름을 쓰지 않는다), "
                "그다음 줄부터 그 주장을 받치는 본문 2~4문장. 문단 사이는 빈 줄.")
    if role == "subsection":
        part = next((p for p in lay.get("parts") or [] if p.get("id") == sec.get("part")), {})
        mine = {b: titled(doc, (lay.get("forms") or {}).get(b)) for b in section_blocks_of(doc, sec)}
        out = [f"## 이 자리의 꼴(문서 양식 — '{part.get('title') or ''}' 장의 소주제)", rules.get("para") or ""]
        if part.get("keyline"):
            # 원본 왼쪽 칸의 2~4줄은 한 문장이 좁은 칸에서 접힌 것 — '줄마다 [핵심]'이라 했더니 요점 넷을 쌓아 넣었다(2026-10-30 사용자 지적).
            # 꼴만 정한다(한 문단에 한 문장) — 무엇을 요지로 삼을지는 작성기가 정한다
            out.append("`[핵심] 요지` 줄 — 바로 아래 문단의 요지를 한 문장(40자 안팎)으로, 문단 첫 줄에 한 번만 둔다(화면이 좁은 왼쪽 칸에서 2~4줄로 접는다). "
                       "요점을 여러 줄로 나눠 쌓지 않는다. 첫 문단에는 두고, 뒤 문단은 원본 짜임에 '핵심'이 있는 자리에서 문단의 요지가 뚜렷할 때만. 본문에 없는 숫자·주장을 핵심에 새로 넣지 않는다.")
        pat = _sample_pattern(lay, sec, mine)
        if pat:
            out.append(f"원본 이 소주제의 짜임: {pat}. 문단 수·순서를 이 짜임에 맞춘다(자료가 모자라면 줄이고, 지어내지 않는다).")
        if mine:
            out.append("표·그림 자리: " + ", ".join(_marker(f) for f in mine.values() if f) +
                       " — 원본 짜임의 그 자리(관련 문단 바로 뒤)에 이 줄을 그대로 한 줄로 둔다(내용은 시스템이 채운다). 둘 자리가 없으면 쓰지 않는다(섹션 끝에 붙는다).")
        out.append("작은 제목이 필요하면(원본 짜임의 '작은 제목') `### 작은 제목` 한 줄로.")
        sibs = [s["title"] for s in doc.get("sections") or [] if s.get("part") == sec.get("part") and s["step"] != sec["step"]]
        if sibs:
            out.append("같은 장의 다른 소주제(그 내용은 거기서 쓴다 — 여기서 다루거나 '확인되지 않음'이라 쓰지 않는다): " + " / ".join(sibs))
        out.append("소제목(섹션 제목)은 쓰지 않는다 — 화면이 번호와 함께 붙인다.")
        return "\n".join(x for x in out if x)
    return ""


def _marker(form: Dict[str, Any]) -> str:
    """본문 속 표·그림 자리 줄 — report/view 가 이 줄 자리에 블록을 놓는다."""
    return f"[{'표' if form.get('kind') == 'table' else '그림'}: {form.get('title') or ''}]"


def _sample_pattern(lay: Dict[str, Any], sec: Dict[str, Any], mine: Dict[str, Any]) -> str:
    """샘플 소주제의 짜임(blueprint subtopic pattern) → '핵심 → 본문 ×5 → [그림: 주요 연혁]'. 섹션 covers 'c1_2' = 장 c1 의 둘째 소주제."""
    cov = (sec.get("covers") or [""])[0]
    m = re.fullmatch(r"(c\d+)_(\d+)", cov or "")
    part = next((p for p in lay.get("parts") or [] if m and p.get("id") == m.group(1)), None)
    subs = (part or {}).get("subtopics") or []
    if not m or int(m.group(2)) > len(subs):
        return ""
    words: List[str] = []
    for x in subs[int(m.group(2)) - 1].get("pattern") or []:
        w = {"K": "핵심", "P": "본문", "M": "작은 제목"}.get(x) or (_marker(mine[x]) if mine.get(x) else "")
        if not w:
            continue
        if words and words[-1].split(" ×")[0] == w and w in ("핵심", "본문"):
            n = int(words[-1].split(" ×")[1]) + 1 if " ×" in words[-1] else 2
            words[-1] = f"{w} ×{n}"
        else:
            words.append(w)
    return " → ".join(words[:40])


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
    criteria: Sequence[str] = (),
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
    layout_rule = _layout_rule(doc, sec)
    if layout_rule:
        blocks.append(layout_rule)
    described =[x for x in sec.get("slots") or [] if not x.get("templateId") and x.get("kind") in ("table", "chart")]
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
    if criteria:
        blocks.append("## 판단 기준(승인된 사내·워크스페이스 기준 — 해석·시사점의 틀. 도달 여부는 줄의 코드 판정만 옮긴다)\n" + "\n".join(criteria))
    others = _other_sections(doc, step)
    if others:
        blocks.append("## 이미 쓴 다른 섹션(겹치지 않게, 결론이 어긋나지 않게)\n" + "\n".join(others))
    pending = _pending_sections(doc, step)
    if pending:
        blocks.append("## 아직 안 쓴 다른 섹션(그 주제는 그 섹션이 쓴다 — 여기서 미리 쓰지 않는다)\n" + "\n".join(pending))
    docs = doc_index_lines(doc_ids)
    blocks.append("## 자료 목록(search_documents 의 document 인자는 D번호)\n" + ("\n".join(docs) if docs else "없음"))
    if block_lines and doc.get("layout"):
        blocks.append(
            "## 이 섹션의 표(시스템이 자료로 채운다 — 자리는 '이 자리의 꼴'의 [표: …] 줄. 표를 글로 옮기지 말고, 결론에 필요한 핵심 숫자만 이 표기 그대로 쓰고 [S번호] 를 단다. "
            "'(= …)' 한국어 단위 표기가 있으면 본문에는 그 표기를 쓴다)\n" + "\n".join(block_lines)
        )
    elif block_lines:
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
                if on_stage and args.get("query"):
                    on_stage(f"writer.search|“{str(args['query'])[:60]}”")  # 상태 줄에 검색어(처리 단계 실시간)
                result = (await asyncio.to_thread(run_search, book, doc_ids, args))["text"]
            elif name == CALC_TOOL_NAME and isinstance(args, dict) and lb is not None:
                result = lb.calculate(args)
                if on_stage:
                    on_stage(f"writer.calc|{str(result).splitlines()[0][:80] if result else ''}")
            else:
                result = f"없는 도구: {name}. 쓸 수 있는 도구는 {SEARCH_TOOL_NAME}·{CALC_TOOL_NAME} 뿐이다. 더 필요 없으면 본문을 출력한다."
            messages.append({"role": "tool", "tool_call_id": tc.get("id") or f"call_{calls}", "content": result})
    content = (res.content or "").strip() if res is not None else ""
    return {"content": content or last_text.strip(), "finish": getattr(res, "finish_reason", None), "calls": calls}


_HEADING_LINE = re.compile(r"^\s*(#{1,6}\s+.*|\*\*[^*\n]{1,40}\*\*\s*:?)\s*$")


def tidy(content: str, title: str) -> str:
    """모델이 붙이는 섹션 제목·코드펜스·텍스트형 도구 호출을 떼고 공백을 정리한다."""
    t = re.sub(r"<tool_call>.*?(?:</tool_call>|$)", "", content or "", flags=re.S)
    t = re.sub(r"\s*\[계산\]", "", t)  # 브리프의 '[계산] …' 줄 머리를 본문에 따라 붙인 것(2026-10-30 실측)
    t = re.sub(r"^```[a-z]*\s*|\s*```$", "", t.strip())
    lines = t.split("\n")
    while lines and (not lines[0].strip() or _HEADING_LINE.match(lines[0]) or lines[0].strip().strip("#*: ") == title.strip()):
        lines.pop(0)
    t = "\n".join(lines)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def doc_unit(doc: Doc) -> str:
    """양식 2.0 틀 문서의 금액 단위 — 표 양식 단위 중 가장 많은 것(KIRS = 억원). 틀이 없거나 정할 수 없으면 ''."""
    units = [f.get("unit") for f in ((doc.get("layout") or {}).get("forms") or {}).values() if f.get("kind") == "table" and f.get("unit")]
    return max(set(units), key=units.count) if units else ""


def to_doc_unit(text: str, unit: str) -> str:
    """본문 원화 금액을 문서 단위로 — 코드가 바꾼다(모델에게 단위 환산을 시키지 않는다). 지금은 억원만:
    '7,198,980천원'·'56,925천원'·'520백만원'(0.1억 이상) · '3,327,723,500원'(1억 이상) · '14억 6,715만 원' → '72.0억원'·'0.6억원'·'5.2억원'·'33.3억원'·'14.7억원'
    (소수 첫째 자리 — 숫자 확인이 반올림 차이까지 원장과 맞춘다). 조 단위·이미 'n억원'인 것, 비율, 작은 원 금액(주당 금액·주가), 0.1억 아래 천원은 그대로."""
    if unit != "억원":
        return text
    out: List[str] = []
    last = 0
    for a in find_amounts(text):
        u = (a.get("unit") or "").replace(" ", "")
        small = u in ("원", "천원", "백만원") and abs(a["abs"]) >= (1e8 if u == "원" else 1e7)
        if a.get("percent") or a.get("currency") != "KRW" or not (small or (u.startswith("억") and "만" in u)):
            continue
        seg = text[a["start"]:a["end"]]
        lead = seg[: len(seg) - len(seg.lstrip())]  # 금액 정규식이 앞 공백까지 잡는다 — 띄어쓰기는 살린다
        out += [text[last:a["start"]], f"{lead}{'-' if a['abs'] < 0 else ''}{abs(a['abs']) / 1e8:,.1f}억원"]
        last = a["end"]
    return "".join(out) + text[last:]


def unsourced_number_sentences(content: str) -> List[str]:
    """수치(단위가 붙은 숫자)가 있는데 출처 토큰이 없는 문장 — 확인할 곳으로 카드에 보인다(결정적, LLM 0회)."""
    out: List[str] = []
    for s in _SENT_SPLIT.split(content or ""):
        s = s.strip()
        if s and _NUMBER_SENT.search(re.sub(r"\[@[^\]]+\]", "", s)) and not tokens(s):
            # 틀 문서의 '[핵심]'·'[제목]' 줄은 아래 본문의 요지 — 그 숫자가 본문(출처 달린 문장)에 다시 나오면 출처 없는 숫자로 보지 않는다
            if _TAG_LINE.match(s) and all(n in _sourced_text(content) for n in re.findall(r"\d[\d,.]*\d|\d", s)):
                continue
            out.append(re.sub(r"\s+", " ", s)[:160])
    return out


_TAG_LINE = re.compile(r"^\[(핵심|제목)\]")


def _sourced_text(content: str) -> str:
    return " ".join(s for s in _SENT_SPLIT.split(content or "") if tokens(s))


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
    extra_calcs: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    """→ {"content": 토큰이 든 본문, "checks", "warnings"}. 빈 본문이면 RuntimeError.
    extra_calcs = 이 턴에 대화가 먼저 계산 도구로 구한 값 — 지시문에 실려 오므로 본문이 그 값을 쓰면 계산값으로 본다."""
    sec = find_section(doc, step)
    if sec is None:
        raise RuntimeError(f"작성 대상 섹션이 없습니다: {step}")
    item = item_of((sec.get("covers") or [""])[0], doc.get("reportType")) if sec.get("covers") else None
    book = SourceBook()
    lb = LedgerBook()
    lb.calcs.extend(extra_calcs)
    if on_stage:
        on_stage("writer.retrieve")
    queries = _queries(doc, sec["title"], item)
    ledger = await asyncio.to_thread(select_figures, doc_ids, doc.get("ledgerChoices") or {}, [*queries, sec["title"], instruction or ""], book, lb) if doc_ids else []
    material = await asyncio.to_thread(presearch, book, doc_ids, queries) if doc_ids else []
    notes = notes_lines(doc.get("teamNotes") or [], scope_hint=sec["title"])
    crit_items = doc.get("_criteria") or []
    crit = criteria_lines(crit_items) if crit_items else []
    block_lines = await asyncio.to_thread(block_brief_lines, doc, sec, book, lb) if has_blocks(doc) else []
    if on_stage:
        on_stage(f"writer.retrieve|문단 {len(material)}개 · 원장 수치 {len(ledger)}개")
    brief = build_brief(doc, step, doc_ids=doc_ids, material=material, instruction=instruction, user_info=user_info or {}, previous_text=previous_text, ledger=ledger, notes=notes,
                        block_lines=block_lines, criteria=crit)
    if on_stage:
        on_stage("writer.generate")
    gen = await _generate_with_search(llm, load("writer_system"), brief, book, doc_ids, on_stage, lb)
    body, memo = split_memo(gen["content"])
    content = tidy(body, sec["title"])
    if doc.get("layout"):
        content = to_doc_unit(content, doc_unit(doc))  # 원본이 천원·원이어도 본문은 양식 단위(억원) — 요약 주장 '72억 원'과 본문 '7,198,980천원'이 섞이던 것
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
        "unitSuspect": nums.get("unitSuspect") or [],
        "numbersChecked": nums["checked"],
        "numbersMatched": nums["matched"],
        "ledgerShown": len(ledger),
        "calcs": len(calcs),
        "truncated": gen["finish"] == "length",
    }
    # 브리프에 실린 판단 기준(판 고정) — 섹션 근거에 '참고한 판단 기준'으로 남긴다
    return {"content": content, "checks": checks, "warnings": warnings, "calcs": calcs, "memo": memo, "criteria": [{"id": c["id"], "key": c["key"], "version": c["version"]} for c in crit_items]}
