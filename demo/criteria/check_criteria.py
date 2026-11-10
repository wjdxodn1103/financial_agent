"""판단 기준 점검(서버·LLM 없이) — 코드 판정·여유·검증 규칙이 시연 이야기대로 나오는지 맞댄다.

  backend/.venv/Scripts/python -I demo/criteria/check_criteria.py [워크스페이스 id]

이야기: HLDS(가상) 데이터센터 매출 증가율 — 2026-09-30 기준 2분기 +35.9%(30% 미만 아님 → 미도달), 2026-10-29 기준 3분기 +24.0%(도달).
단일 발행자 한도 5% — 가상 포트폴리오의 Helios 5.6%(도달, 여유 −0.6%p). 표는 저장하지 않는다(메모리의 기준 행으로 판정만).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACK = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACK))
os.chdir(BACK)
sys.stdout.reconfigure(encoding="utf-8")

from sqlmodel import Session, select  # noqa: E402

from app.assistants.guideline import portfolio_doc  # noqa: E402
from app.criteria import extract, match, proposals, service  # noqa: E402
from app.db import Criterion, Workspace, engine, scope_ids  # noqa: E402

HLDS = {"name": "Helios Data Systems", "ticker": "HLDS"}
fails = 0


def ok(cond: bool, label: str, got: object = "") -> None:
    global fails
    fails += 0 if cond else 1
    print(f"  {'OK ' if cond else 'FAIL'} {label}  {got}")


def pick_workspace(arg: str | None) -> str:
    with Session(engine) as s:
        if arg:
            return arg
        for w in s.exec(select(Workspace)).all():
            ids = scope_ids(w)
            if portfolio_doc(ids) and any("helios" in d.lower() or True for d in ids):
                return w.id
    raise SystemExit("포트폴리오 자료가 든 워크스페이스가 없습니다 — demo/company/seed_company.py 먼저")


def main() -> None:
    ws_id = pick_workspace(sys.argv[1] if len(sys.argv) > 1 else None)
    with Session(engine) as s:
        doc_ids = scope_ids(s.get(Workspace, ws_id))
    print(f"워크스페이스 {ws_id} · 자료 {len(doc_ids)}건")

    growth = Criterion(id="t1", key="k1", title="HLDS 데이터센터 성장 논거", kind="numeric", direction="review", applies=dict(HLDS),
                       condition={"metric": "데이터센터 매출", "period": "latest_q_yoy", "op": "<", "threshold": 30, "unit": "%"})
    issuer = Criterion(id="t2", key="k2", scope="company", title="단일 발행자 한도", kind="numeric", direction="reduce",
                       condition={"metric": "단일 발행자 비중", "op": ">", "threshold": 5, "unit": "%"}, limit={"op": "<=", "threshold": 5, "unit": "%"})

    print("1) 성장 논거(코드 판정)")
    r = match.evaluate(growth, HLDS, doc_ids, "2026-09-30")
    ok(r["result"] == "not_reached", "2026-09-30 → 미도달", r["value"].get("display"))
    r = match.evaluate(growth, HLDS, doc_ids, "2026-10-29")
    ok(r["result"] == "reached" and abs(r["value"]["value"] - 24.0) < 0.1, "2026-10-29 → 도달 24.0%", r["value"].get("display"))
    ok(bool(r["anchors"]) and r["anchors"][0].get("cell"), "근거 = 10-Q 표 칸", (r["anchors"][0].get("rowLabel"), r["anchors"][0].get("ext", {}).get("filed")) if r["anchors"] else None)

    print("2) 단일 발행자 한도(보유 내역)")
    r = match.evaluate(issuer, HLDS, doc_ids)
    ok(r["result"] == "reached", "Helios 5.6% > 5% → 도달", r["value"].get("display"))
    hr = match.headroom([issuer, growth], HLDS, doc_ids)
    ok(len(hr) == 1 and abs(hr[0]["gap"] + 0.6) < 0.01 and not hr[0]["within"], "여유 −0.6%p(한도 기준만)", hr[0]["display"] if hr else None)

    print("3) 대상 거르기")
    ok(match.applies_to(growth, HLDS) and not match.applies_to(growth, {"name": "Orion Logistics"}), "대상 정해진 기준은 그 대상에만")
    ok(match.applies_to(issuer, {"name": "Orion Logistics"}), "대상 없는 한도 기준은 어디에나")
    ok(match.code_metric("데이터센터 매출", ["Total revenue", "Data center revenue", "Data center revenue growth"]) == "Data center revenue", "지표 이름 맞추기(LLM 없이)")

    print("4) 기준 뽑기 검증(가짜 LLM 답)")
    sents = [("s1", "정하윤(위원장): 다음 분기 실적에서 데이터센터 매출 증가율이 전년 같은 분기 대비 30% 아래로 내려가면 재심의합니다.", ""),
             ("s1", "박서준(해외주식운용실장): Helios Data Systems 데이터센터 매출이 2분기에 35.9% 늘었습니다.", "")]
    sents = [(a, b, b) for a, b, _ in sents]
    good = {"n": 1, "quote": "데이터센터 매출 증가율이 전년 같은 분기 대비 30% 아래로 내려가면 재심의합니다", "direction": "review", "kind": "numeric", "applies": {"name": "Helios Data Systems"},
            "condition": {"metric": "데이터센터 매출 증가율", "period": "latest_q_yoy", "op": "<", "threshold": 30, "unit": "%"}}
    got = extract.verify([good], sents, "data", "x", "회의록")
    ok(len(got) == 1 and got[0]["kind"] == "numeric" and got[0]["condition"]["threshold"] == 30.0, "맞는 답 → 숫자 기준 1개", got[0]["condition"] if got else None)
    ok(not extract.verify([{**good, "quote": "30% 아래면 즉시 매도한다"}], sents, "data", "x", "회의록"), "원문에 없는 인용 → 버림")
    ok(not extract.verify([{**good, "n": 2, "quote": "데이터센터 매출이 2분기에 35.9% 늘었습니다"}], sents, "data", "x", "회의록"), "방향 낱말 없는 문장 → 버림")
    ok(not extract.verify([{**good, "applies": {"name": "Orion Logistics"}}], sents, "data", "x", "회의록"), "자료에 없는 대상 → 버림")
    weak = extract.verify([{**good, "condition": {"metric": "데이터센터 매출 증가율", "op": "<", "threshold": "삼십"}}], sents, "data", "x", "회의록")
    ok(len(weak) == 1 and weak[0]["kind"] == "qualitative", "기준값이 숫자가 아니면 정성으로 낮춤")
    ok(extract._json('{"rules": [{"n": 1}]}\n\n{\n}').get("rules") == [{"n": 1}], "답 끝에 빈 객체가 붙어도 첫 JSON 만 읽음")
    ok(extract.limit_of({"metric": "단일 발행자 비중", "op": ">", "threshold": 5}) == {"op": "<=", "threshold": 5.0, "unit": "%"}, "비중 조건 → 한도(반대 부등호)")

    print("5) 정책서 → 한도 기준(캐시가 있으면)")
    from app.assistants.guideline import _find_docs
    from app.config import DATA_DIR

    with Session(engine) as s:
        policy, _port = _find_docs(s, ws_id)
    if policy and (DATA_DIR / "guideline" / f"rules_{policy}.json").exists():
        class NoLlm:
            async def complete(self, *_a, **_k):
                raise RuntimeError("LLM 을 부르면 안 됨(캐시)")

        import asyncio

        pol = asyncio.run(extract.from_policy(NoLlm(), policy))
        iss = next((x for x in pol if x["condition"].get("metric") == "단일 발행자 비중"), None)
        ok(bool(iss) and iss["condition"]["op"] == ">" and iss["direction"] == "reduce" and iss["limit"]["op"] == "<=", "단일 발행자 ≤5% → '>5% 면 축소 검토' + 한도 ≤5", iss["title"] if iss else pol[:2])
    else:
        print("  -- 정책서 조건 캐시 없음(가이드라인 점검을 한 번 돌리면 생김) — 건너뜀")

    print("6) 검토 제안 문장 검증")
    allowed = ["+24.0% (2026Q3 1860 USD millions / 2025Q3 1500 USD millions)", "단일 발행자 한도 5% 이하 · 지금 5.6% · 여유 -0.6%p", "데이터센터 매출 30% 미만"]
    ok(proposals.numbers_ok("3분기 데이터센터 매출은 전년 대비 24.0% 늘어 기준 30%에 못 미쳤다.", allowed), "허용 숫자만 → 통과")
    ok(not proposals.numbers_ok("3분기 데이터센터 매출은 전년 대비 18% 늘었다.", allowed), "지어낸 숫자(18) → 거부")
    ok(bool(proposals.FORBID.search("비중을 축소해야 한다")) and not proposals.FORBID.search("재심의 검토가 필요하다"), "단정·권고 낱말 거르기")
    ok(not proposals.revision_ok("비중을 벤치마크 대비 30bp 늘린다.", "비중을 벤치마크 대비 5.6%로 맞춘다.", allowed), "결정 문장(비중·bp)은 고치지 않음")
    ok(not proposals.revision_ok("2분기 35.9% 늘어 논거가 유지되고 있다.", "3분기 24.0% 늘어 논거가 유지되고 있다.", allowed), "전제가 깨졌는데 '유지되고 있다' → 거부")
    ok(proposals.revision_ok("2분기 35.9% 늘어 논거가 유지되고 있다.", "2026년 3분기 24.0%로 기준 30%에 못 미쳤다.", allowed), "사실로 고친 문장 → 통과")
    raw = "Helios는 2분기 35.9% 늘었다[@0a3275dd29375acc#p3]."
    rev = proposals._revised_raw(raw, "Helios는 3분기 24.0% 늘었다.", {"anchors": [{"docId": "3b7e8b5073fd3982", "chunk": "p5"}]})
    ok(rev.endswith("[@0a3275dd29375acc#p3][@3b7e8b5073fd3982#p5].") and "24.0%" in rev, "고친 문장 = 원래 인용 + 새 근거 토큰(마침표 앞)", rev)

    print("7) 판 사이 바뀐 것")
    v2 = Criterion(id="t3", key="k1", version=2, title=growth.title, kind="numeric", direction="reduce", applies=dict(HLDS),
                   condition={"metric": "데이터센터 매출", "period": "latest_q_yoy", "op": "<", "threshold": 25, "unit": "%"})
    d = {x["field"]: (x["before"], x["after"]) for x in service.diff(growth, v2)}
    ok("조건" in d and "방향" in d and d["방향"] == ("재심의", "축소 검토"), "조건 30→25 · 방향 재심의→축소 검토", d)

    print("실패 0" if not fails else f"실패 {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
