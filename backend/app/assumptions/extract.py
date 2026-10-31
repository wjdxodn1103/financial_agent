"""가정 뽑기 — 안건·보고서(AI 작업 문서 또는 올린 자료)에서 투자 판단이 기댄 '가정' 문장 후보를 낸다.
LLM 은 문장 번호·원문 그대로의 인용·대상·(숫자면) 조건만 낸다 → 코드가 인용이 원문에 그대로 있는지 확인한다(없으면 버린다).
당시 근거: AI 작업 문서면 그 문장의 인용 토큰([@문서#문단])이 그대로 근거 앵커가 된다.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from app.anchors import pin as make_anchor, pin_text
from app.docs.citations import tokens
from app.docs.store import doc_label, load_meta, paragraphs
from app.llm.base import ChatParams

PROMPT = """아래는 투자 안건·보고서의 문장들이다(번호 붙음). 투자 판단이 기대고 있는 '가정'(앞으로 확인할 수 있는 전망·조건)을 최대 8개 골라 JSON 하나로만 답한다(설명 없이).
{"assumptions": [{"n": 문장 번호, "quote": "그 문장에서 가정 부분을 글자 그대로", "target": {"name": "대상 회사·자산 이름", "ticker": "티커(알면)"}, "kind": "numeric|qualitative", "role": "assumption|trigger",
  "condition": {"metric": "지표 이름(숫자 가정만)", "period": "latest_q_yoy|latest_q|latest_fy|latest_fy_yoy", "op": ">=|>|<=|<", "threshold": 숫자, "unit": "%|억원|USD mn 등"}}]}
규칙:
- 사실 서술(이미 일어난 일·과거 실적)은 가정이 아니다. '~할 것', '~를 유지', '~ 이상 성장' 같은 앞으로 확인할 전망·조건만.
- role: 맞아야 하는 전망이면 assumption, '~이면 재심의·축소·재검토한다' 처럼 그렇게 되면 행동하는 기준이면 trigger(condition 은 그 기준 — 예: '30% 아래로 내려가면 재심의' → op "<", threshold 30).
- 포트폴리오 비중 조건(단일 발행자 비중·비상장 비중·주식 비중 등)은 metric 에 '…비중'을 쓰고 period 는 비운다.
- quote 는 문장 글자를 바꾸지 않고 그대로 옮긴다.
- 숫자로 확인할 수 있으면 kind=numeric 과 condition 을 채운다(성장률은 latest_q_yoy 또는 latest_fy_yoy, threshold 는 % 숫자). 아니면 qualitative 로 두고 condition 은 빈 객체."""


def _sentences_report(doc: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """AI 작업 문서 → [(섹션 step, 원문 문장(토큰 포함), 글자만)]"""
    out = []
    for sec in doc.get("sections") or []:
        for sent in re.split(r"(?<=[.!?。])\s+|\n+", sec.get("content") or ""):
            plain = re.sub(r"\[@[^\]]+\]", "", sent).strip()
            if len(plain) >= 15:
                out.append((sec["step"], sent, plain))
    return out[:200]


def _sentences_data(doc_id: str) -> List[Tuple[str, str, str]]:
    out = []
    for p in paragraphs(doc_id):
        if p.get("kind") == "table":
            continue
        for sent in re.split(r"(?<=[.!?。])\s+|\n+", p.get("text") or ""):
            s = sent.strip()
            if len(s) >= 15:
                out.append((p["id"], s, s))
    return out[:200]


def _json(text: str) -> Dict[str, Any]:
    m = re.search(r"\{[\s\S]*\}", re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M))
    try:
        v = json.loads(m.group(0)) if m else {}
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


async def extract(llm: Any, doc_kind: str, doc_ref: str, report_doc: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    sents = _sentences_report(report_doc or {}) if doc_kind == "report" else _sentences_data(doc_ref)
    if not sents:
        return []
    body = "\n".join(f"[{i + 1}] {plain}" for i, (_s, _raw, plain) in enumerate(sents))[:16000]
    got: Dict[str, Any] = {}
    for _ in range(2):  # 빈 답·깨진 JSON 이면 한 번 더
        res = await llm.complete("chat", ChatParams(messages=[{"role": "user", "content": f"{PROMPT}\n\n## 문장\n{body}"}], temperature=0, max_tokens=5000, timeout_s=180))
        got = _json(getattr(res, "content", "") or "")
        if got.get("assumptions"):
            break
    out: List[Dict[str, Any]] = []
    for a in got.get("assumptions") or []:
        try:
            n = int(a.get("n"))
        except (TypeError, ValueError):
            continue
        if not (1 <= n <= len(sents)):
            continue
        step, raw, plain = sents[n - 1]
        quote = str(a.get("quote") or "").strip()
        if not quote or re.sub(r"\s+", "", quote) not in re.sub(r"\s+", "", plain):
            continue  # 원문에 그대로 없는 인용은 버린다
        kind = "numeric" if a.get("kind") == "numeric" and isinstance(a.get("condition"), dict) and a["condition"].get("metric") else "qualitative"
        cond = a.get("condition") if kind == "numeric" else {}
        target = a.get("target") if isinstance(a.get("target"), dict) else {}
        if doc_kind == "report":
            anchor = {"kind": "report", "sessionId": doc_ref, "step": step, "quote": quote}
            basis = list(pin_text(raw).values())  # 그 문장의 인용 = 당시 근거
        else:
            anc = make_anchor(doc_ref, step, quote=quote)
            anchor = {"kind": "data", **(anc or {"docId": doc_ref, "chunk": step, "quote": quote})}
            basis = []
        out.append({"step": step if doc_kind == "report" else None, "quote": quote, "anchor": anchor, "target": {"name": str(target.get("name") or "")[:80], "ticker": str(target.get("ticker") or "")[:12]},
                    "kind": kind, "condition": cond or {}, "basis": basis, "role": "trigger" if a.get("role") == "trigger" else None})
    return out


def doc_title(doc_kind: str, doc_ref: str, report_title: str = "") -> str:
    return report_title if doc_kind == "report" else doc_label(load_meta(doc_ref), doc_ref)


__all__ = ["extract", "doc_title", "tokens"]
