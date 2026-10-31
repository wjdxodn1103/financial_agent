"""숫자별 확인 — 리포트 본문의 숫자 하나하나가 어디서 왔는지 코드로 판정하고, 사람이 확인 표시를 남긴다(LLM 0회).

판정(위에서부터 처음 맞는 것):
  source     인용한 문단의 글·표 칸 → 원장에서 인용한 자료에 같은 값
  calc       계산 도구 결과(섹션 증거의 calcs) 또는 같은 문장 두 비율의 차이(%p)
  source     원장의 다른 자료(flag notCited)에 같은 값 — 계산값보다 뒤(사내 공용 데이터처럼 범위가 넓으면 우연히 같은 값이 많다)
  input      사용자가 카드에 넣은 값
  mismatch   문장에 출처가 있는데 그 값이 어디에도 없다
  unsourced  출처 없는 문장의 숫자
needsReview(사람이 봐야 함) = mismatch · unsourced · notCited · conflict(자료마다 다름, 미채택) · notChosen(채택값과 다름).
위치는 리포트 뷰(build_report_view)가 그린 글 기준 — 화면의 [n] 표기와 같은 글자 위치라 칸 강조가 어긋나지 않는다.
확인 표시는 doc["numberChecks"][key] — key 는 (섹션, 문장, 숫자, 문장 안 순번)의 해시라 그 문장이 바뀌면 다시 확인해야 한다.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

from app.docs.citations import _MARKER, _SENT_SPLIT
from app.docs.store import load_chunks
from app.ledger.calc import readable
from app.ledger.figures import Figure
from app.ledger.numbers import find_amounts, is_rounding_of, loss_variants, same_value, scale_slip, sig_digits
from app.report.view import build_report_view

STATUS_KO = {"source": "자료와 일치", "calc": "계산값", "input": "입력값", "mismatch": "원장과 다름", "unsourced": "출처 없음"}
FLAG_KO = {"notCited": "인용하지 않은 자료의 값", "conflict": "자료마다 다른 값", "notChosen": "채택값과 다름", "scale": "단위 의심(자릿수 차이)"}
_COUNT_UNITS = ("개", "건")  # 메타 숫자(“3개 자료”)는 확인 대상이 아니다


def _is_target(a: Dict[str, Any]) -> bool:
    unit = (a.get("unit") or "").strip()
    return not any(unit.startswith(u) for u in _COUNT_UNITS)


def _sentences(text: str) -> List[Tuple[int, int]]:
    out, start = [], 0
    for m in _SENT_SPLIT.finditer(text):
        out.append((start, m.start()))
        start = m.end()
    out.append((start, len(text)))
    return out


def _key(step: str, sentence: str, raw: str, nth: int) -> str:
    norm = " ".join(sentence.split())
    return hashlib.sha1(f"{step}|{norm}|{raw}|{nth}".encode("utf-8")).hexdigest()[:12]


def number_spans(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    """리포트 뷰 블록 → 숫자 위치들 [{b, i, start, end, raw, key, step, sentence, anchors, amount}] (읽는 순서)."""
    out: List[Dict[str, Any]] = []
    for bi, b in enumerate(view["blocks"]):
        if b["kind"] == "para":
            parts = [(None, b["text"], b["cites"])]
        elif b["kind"] == "list":
            parts = [(ii, it["text"], it["cites"]) for ii, it in enumerate(b["items"])]
        else:
            continue
        for ii, text, cites in parts:
            sents = _sentences(text)
            seen: Dict[Tuple[int, str], int] = {}
            for a in find_amounts(text):
                if not _is_target(a):
                    continue
                # find_amounts 의 위치는 숫자 앞 공백까지 잡을 수 있다 — 화면 강조는 표기(raw) 글자에 정확히
                at = text.find(a["raw"], a["start"], a["end"] + 1)
                if at < 0:
                    continue
                a = {**a, "start": at, "end": at + len(a["raw"])}
                si = next((k for k, (s0, s1) in enumerate(sents) if s0 <= a["start"] <= s1), len(sents) - 1)
                s0, s1 = sents[si]
                sentence = _MARKER.sub("", text[s0:s1]).strip()
                nth = seen.get((si, a["raw"]), 0)
                seen[(si, a["raw"])] = nth + 1
                anchors = list(dict.fromkeys((x["docId"], x["chunk"]) for c in cites if s0 <= c["start"] <= s1 + 1 for x in c["anchors"]))
                out.append({"b": bi, "i": ii, "start": a["start"], "end": a["end"], "raw": a["raw"], "key": _key(b["step"], sentence, a["raw"], nth), "step": b["step"], "sentence": sentence, "anchors": anchors, "amount": a})
    return out


def _same(a: Dict[str, Any], f: Dict[str, Any]) -> bool:
    if bool(a.get("percent")) != bool(f.get("percent")):
        return False
    if f.get("unitKnown", True) is False:
        return same_value(a["value"], 10 ** -int(a.get("decimals") or 0), f["value"], 10 ** -int(f.get("decimals") or 0))
    return same_value(a["abs"], a["step"], f["abs"], f["step"])


def _snippet(text: str, start: int, end: int, width: int = 70) -> str:
    s0, s1 = max(0, start - width), min(len(text), end + width)
    return ("…" if s0 else "") + text[s0:s1].replace("\n", " ") + ("…" if s1 < len(text) else "")


class _Judge:
    def __init__(self, doc: Dict[str, Any], ledger: Dict[str, Any]):
        self.figures: List[Figure] = ledger["figures"]
        self.groups = ledger["groups"]
        self.group_of = {fid: g for g in self.groups for fid in g["figureIds"]}
        self.by_fid = {f["fid"]: f for f in self.figures}
        self.evidence = doc.get("evidence") or {}
        # 섹션에 넣은 AI 채팅 표의 계산 칸(영업이익률 등) — 본문이 그 값을 쓰면 계산값으로 본다
        self.table_calcs = {s["step"]: [c for t in s.get("tables") or [] for c in t.get("calcs") or []] for s in doc.get("sections") or []}
        if doc.get("layout"):  # 틀(양식 2.0) 문서 — 섹션에 묶인 표의 계산 칸(비율·증가율)도
            from app.formats.blocks import section_format_blocks

            for s in doc.get("sections") or []:
                if s.get("blocks"):
                    self.table_calcs.setdefault(s["step"], []).extend(c for b in section_format_blocks(doc, s) for c in b.get("calcs") or [])
        self.user_text = re.sub(r"\s+", "", " ".join(v for v in (doc.get("userInputs") or {}).values() if isinstance(v, str)))
        self._chunks: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def chunk(self, doc_id: str, chunk_id: str) -> Optional[Dict[str, Any]]:
        if doc_id not in self._chunks:
            self._chunks[doc_id] = {c.get("id"): c for c in load_chunks(doc_id)}
        return self._chunks[doc_id].get(chunk_id)

    def _fig_ref(self, f: Figure, via: str) -> Dict[str, Any]:
        ch = self.chunk(f["doc"], f["chunk"]) or {}
        rows = ch.get("rows") or []
        ri, ci = (f.get("cell") or [0, 0])[:2]
        row = rows[ri] if 0 <= ri < len(rows) else []
        head = rows[0][ci] if rows and 0 <= ci < len(rows[0]) else ""
        return {"via": via, "docId": f["doc"], "label": f.get("docLabel") or f["doc"][:8], "chunk": f["chunk"], "page": f.get("page"), "sheet": f.get("sheet"), "cell": f.get("cell"), "display": f.get("display") or f["raw"], "quote": " | ".join(str(x) for x in row), "column": str(head or ""), "metric": f["metric"], "period": f["period"]}

    def _flags(self, f: Figure, cited: bool) -> Tuple[List[str], Optional[Dict[str, Any]]]:
        flags: List[str] = [] if cited else ["notCited"]
        g = self.group_of.get(f["fid"])
        info = None
        if g:
            chosen = self.by_fid.get((g.get("chosen") or {}).get("figureId") or "")
            if chosen is not None and not _same(f, chosen):
                flags.append("notChosen")
            elif chosen is None and g["conflict"]:
                flags.append("conflict")
            if g["conflict"] or chosen is not None:
                info = {"values": [v["display"] for v in g["values"]], "chosen": (chosen.get("display") or chosen["raw"]) if chosen else None, "key": g["key"]}
        return flags, info

    def judge(self, e: Dict[str, Any]) -> Dict[str, Any]:
        a = e["amount"]
        cands = loss_variants(a, e.get("sentence") or "")  # 손실 문맥이면 부호 뒤집은 값도

        def same(x: Dict[str, Any]) -> bool:
            return any(_same(c, x) for c in cands)
        cited_docs = {d for d, _c in e["anchors"]}
        # (a) 인용한 문단 — 표면 그 칸, 글이면 같은 값이 든 자리
        for d, c in e["anchors"]:
            ch = self.chunk(d, c)
            if not ch:
                continue
            if ch.get("rows"):
                hit = next((f for f in self.figures if f["doc"] == d and f["chunk"] == c and same(f)), None)
                if hit:
                    flags, info = self._flags(hit, True)
                    return {"status": "source", "flags": flags, "source": self._fig_ref(hit, "cited-cell"), "group": info}
            text = ch.get("text") or ""
            m = next((b for b in find_amounts(text) if same(b)), None)
            if m:
                label = next((f.get("docLabel") for f in self.figures if f["doc"] == d), None)
                return {"status": "source", "flags": [], "source": {"via": "cited-text", "docId": d, "label": label or d[:8], "chunk": c, "page": ch.get("page"), "sheet": ch.get("sheet"), "cell": None, "display": m["raw"], "quote": _snippet(text, m["start"], m["end"]), "column": "", "metric": "", "period": ""}, "group": None}
        # (b) 원장 — 인용한 자료의 같은 값
        hits = [f for f in self.figures if same(f)]
        hits.sort(key=lambda f: (f["doc"] not in cited_docs, not (self.group_of.get(f["fid"]) or {}).get("chosen"), -((self.group_of.get(f["fid"]) or {}).get("documents") or 0)))
        if hits and hits[0]["doc"] in cited_docs:
            flags, info = self._flags(hits[0], True)
            return {"status": "source", "flags": flags, "source": self._fig_ref(hits[0], "ledger"), "group": info}
        # (d) 계산 도구 결과
        for c in [*((self.evidence.get(e["step"]) or {}).get("calcs") or []), *self.table_calcs.get(e["step"], [])]:
            ok = (c.get("percent") and a["percent"] and is_rounding_of(abs(a["value"]), a["step"], abs(c["value"]))) or (not c.get("percent") and not a["percent"] and is_rounding_of(a["abs"], a["step"], c["value"]))
            if ok:
                inputs = [self._fig_ref(self.by_fid[fid], "calc-input") for fid in c.get("inputs") or [] if fid in self.by_fid]
                return {"status": "calc", "flags": [], "calc": {"label": c.get("label") or "계산", "readable": c.get("readable") or c.get("expression") or "", "display": c.get("display") or "", "inputs": inputs}}
        # (e) 같은 문장 두 비율의 차이(%p)
        if a.get("pp"):
            pcts = [b for b in find_amounts(e["sentence"]) if b["percent"] and not b.get("pp")]
            for i, x in enumerate(pcts):
                for y in pcts[i + 1 :]:
                    if is_rounding_of(abs(a["value"]), a["step"], abs(x["value"] - y["value"])):
                        return {"status": "calc", "flags": [], "calc": {"label": "비율 차이", "readable": f"{y['raw']} − {x['raw']}" if y["value"] > x["value"] else f"{x['raw']} − {y['raw']}", "display": a["raw"], "inputs": []}}
        # (c) 원장 — 다른 자료의 같은 값(인용이 없는 문장이면 인용한 것으로 본다). 계산값보다 뒤 — 사내 공용 데이터처럼 범위가 넓으면 우연히 같은 값이 많다
        if hits:
            f = hits[0]
            flags, info = self._flags(f, not cited_docs)
            return {"status": "source", "flags": flags, "source": self._fig_ref(f, "ledger"), "group": info}
        # (f) 사용자 입력
        if a["raw"].replace(" ", "") and a["raw"].replace(" ", "") in self.user_text:
            return {"status": "input", "flags": []}
        # (g) 단위 의심 — 유효 숫자는 인용 문단·원장 금액과 같은데 자릿수가 10^k 배 다르다(billion → 조·억 환산 실수)
        if not a["percent"] and sig_digits(a["raw"]) >= 3:
            for d, c in e["anchors"]:
                ch = self.chunk(d, c) or {}
                for b in find_amounts(ch.get("text") or ""):
                    if not b["percent"] and b.get("unit") and any(scale_slip(c["abs"], b["abs"]) for c in cands):
                        return {"status": "mismatch", "flags": ["scale"], "source": {"via": "cited-text", "docId": d, "label": d[:8], "chunk": c, "page": ch.get("page"), "sheet": ch.get("sheet"), "cell": None, "display": b["raw"], "quote": _snippet(ch.get("text") or "", b["start"], b["end"]), "column": "", "metric": "", "period": ""}, "group": None}
            # 단위를 아는 금액 — 배율 칸(억원·billion)이거나 통화가 있는 원 단위 칸(DART '-5,572,218,496' 원 → 본문 '557.22억원')
            f = next((f for f in self.figures if not f.get("percent") and f.get("abs") and f.get("unitKnown", True) and ((f.get("scale") or 1) > 1 or f.get("currency")) and any(scale_slip(c["abs"], f["abs"]) for c in cands) and f["doc"] in cited_docs), None)
            if f:
                return {"status": "mismatch", "flags": ["scale"], "source": self._fig_ref(f, "ledger"), "group": None}
        return {"status": "mismatch" if e["anchors"] else "unsourced", "flags": []}


def number_report(doc: Dict[str, Any], ledger: Dict[str, Any], names: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """→ {spans: [{b, i, start, end, key, status, needsReview, confirmed}], items: {key: 판정}, order: [key…], summary}"""
    view = build_report_view(doc)
    spans = number_spans(view)
    judge = _Judge(doc, ledger)
    marks: Dict[str, Dict[str, Any]] = doc.get("numberChecks") or {}
    titles = {s["step"]: s.get("title") or s["step"] for s in doc.get("sections") or []}
    items: Dict[str, Dict[str, Any]] = {}
    out_spans: List[Dict[str, Any]] = []
    for e in spans:
        if e["key"] not in items:
            j = judge.judge(e)
            needs = j["status"] in ("mismatch", "unsourced") or bool(set(j["flags"]) & {"notCited", "conflict", "notChosen"})
            mark = marks.get(e["key"])
            items[e["key"]] = {
                "key": e["key"],
                "step": e["step"],
                "section": titles.get(e["step"], e["step"]),
                "raw": e["raw"],
                "sentence": e["sentence"],
                "cited": [{"docId": d, "chunk": c} for d, c in e["anchors"]],
                **j,
                "needsReview": needs,
                "confirmed": {**mark, "byName": (names or {}).get(mark.get("by") or "", "")} if mark else None,
            }
        it = items[e["key"]]
        out_spans.append({"b": e["b"], "i": e["i"], "start": e["start"], "end": e["end"], "raw": e["raw"], "key": e["key"], "status": it["status"], "needsReview": it["needsReview"], "confirmed": bool(it["confirmed"])})
    vals = list(items.values())
    review = [x for x in vals if x["needsReview"]]
    summary = {
        "total": len(vals),
        "byStatus": {k: sum(1 for x in vals if x["status"] == k) for k in STATUS_KO},
        "auto": len(vals) - len(review),
        "needsReview": len(review),
        "reviewConfirmed": sum(1 for x in review if x["confirmed"]),
        "confirmed": sum(1 for x in vals if x["confirmed"]),
    }
    return {"spans": out_spans, "items": items, "order": list(items.keys()), "summary": summary, "statusKo": STATUS_KO, "flagKo": FLAG_KO}


def open_review_items(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """검토 준비 점검용 — 사람이 아직 확인하지 않은 '봐야 할 숫자'(충돌·채택 차이는 충돌 카드가 따로 다룬다)."""
    out = []
    for it in report["items"].values():
        if not it["needsReview"] or it["confirmed"]:
            continue
        if it["status"] in ("mismatch", "unsourced"):
            out.append({"kind": it["status"], "step": it["step"], "title": it["section"], "text": f"{it['raw']} — {it['sentence'][:100]}", "key": it["key"]})
        elif "notCited" in it["flags"]:
            out.append({"kind": "wrongcite", "step": it["step"], "title": it["section"], "text": f"{it['raw']} — {(it.get('source') or {}).get('label', '')}의 값인데 인용하지 않음", "key": it["key"]})
    return out


__all__ = ["number_report", "number_spans", "open_review_items", "STATUS_KO"]
