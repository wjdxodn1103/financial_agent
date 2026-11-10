"""판단 기준 루프 시연 준비 — 해외주식운용실 워크스페이스(가상 HLDS)를 만들고 기준을 뽑아 승인한 뒤, 날짜를 되돌려 '새 10-Q → 검토 제안'을 재현한다.
백엔드 8200 이 떠 있어야 한다. 사내 공용 데이터(투자정책서·가상 포트폴리오)가 먼저 들어가 있어야 한다(demo/company/seed_company.py).

  backend/.venv/Scripts/python -I demo/criteria/seed_criteria.py            → 새로 만들기(워크스페이스 id 는 demo/criteria/.ws)
  backend/.venv/Scripts/python -I demo/criteria/seed_criteria.py --scan     → 이미 만든 워크스페이스에서 재현만 다시(9/30 기준선 → 10/29)

만드는 것
  - 워크스페이스 '해외주식운용실 — HLDS(가상)' · 김민준(소유자) · 이서연(편집자)
  - 자료: IWC 회의록(2026-08-27) · 하우스뷰 2026Q3
  - 문서(이서연 작성): 'IWC 안건 — Helios Data Systems 비중 확대'(승인됨) · '주간 해외주식 리뷰'(작성 중, 2분기 35.9% 문장)
  - 판단 기준: 사내 = 투자정책서(한도)·하우스뷰(입장), 워크스페이스 = 회의록(재심의 조건) — 뽑고 김민준이 승인
  - 재현: 2026-09-30 기준 판정(기준선 — 제안 없음) → 2026-10-29 기준(3분기 10-Q 24.0%) → 문서 두 편에 검토 제안
LLM: 회의록 기준 뽑기 1회 + 제안 설명 2회(투자정책서는 가이드라인 점검이 뽑아 둔 것을 쓴다 — 없으면 1회 더).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACK = ROOT / "backend"
WS_FILE = HERE / ".ws"
KIM, LEE = "u_kim", "u_lee"
sys.stdout.reconfigure(encoding="utf-8")  # -I 는 PYTHONIOENCODING 을 무시한다(윈도 콘솔 cp949)
HLDS = "Helios Data Systems"


def client(user: str, base: str) -> httpx.Client:
    return httpx.Client(base_url=f"{base}/api", headers={"X-User-Id": user}, timeout=600)


def wait_docs(c: httpx.Client, ws: str) -> list:
    print("자료 처리 기다리는 중", end="", flush=True)
    for _ in range(180):
        r = c.get(f"/workspaces/{ws}/documents").raise_for_status().json()
        if not [j for j in r.get("jobs") or [] if j.get("status") in ("queued", "processing")]:
            print(" 끝")
            return r.get("documents") or []
        print(".", end="", flush=True)
        time.sleep(3)
    raise SystemExit("자료 처리가 끝나지 않았습니다.")


def in_process_reports(ws: str) -> None:
    """문서 두 편 — 섹션을 내용과 함께 만드는 HTTP API 가 없어 프로세스 안에서(같은 DB). 인용 토큰은 HLDS 10-Q 원장 칸."""
    sys.path.insert(0, str(BACK))
    os.chdir(BACK)
    from sqlmodel import Session

    from app.agent.session import add_section, mark_ai_draft, set_section
    from app.db import User, engine, scope_ids, Workspace
    from app.docs.citations import token_doc_ids
    from app.docs.store import load_meta
    from app.ledger.figures import load_figures
    from app.services.report_service import ReportService
    from app.sharing import set_approval

    with Session(engine) as s:
        ids = scope_ids(s.get(Workspace, ws))
        lee, kim = s.get(User, LEE), s.get(User, KIM)

        def q2_token() -> str:
            for d in ids:
                snap = (load_meta(d) or {}).get("snapshot") or {}
                if "helios" not in str((load_meta(d) or {}).get("card") or "").lower() or snap.get("form") != "10-Q":
                    continue
                for f in load_figures(d):
                    if f.get("metric") == "Data center revenue" and f.get("periodKey") == "2026Q2":
                        return f"[@{d}#{f['chunk']}]"
            return ""

        tok = q2_token()
        svc = ReportService(s)
        # 1) IWC 안건(승인됨) — 원문 md 의 장 = 섹션
        p = svc.create(ws, lee, title=f"IWC 안건 — {HLDS} 비중 확대 (가상)", report_type="free")  # 양식 없음 — 기본 양식 섹션을 깔지 않게
        sid = p["session"]["id"]
        row = svc.row_or_404(sid)
        doc = dict(row.doc or {})
        doc["setup"] = {**doc.get("setup", {}), "subject": f"{HLDS} (HLDS)", "asOf": "2026-08-20"}
        body = {
            "안건": f"해외주식 포트폴리오에서 {HLDS}(HLDS, 가상)의 비중을 벤치마크 대비 30bp 늘린다.",
            "투자 논거": f"{HLDS}의 데이터센터 매출은 앞으로도 전년 대비 30% 이상 성장할 것이다. 2026년 2분기 데이터센터 매출은 19억 3,000만 달러로 전년 같은 분기 14억 2,000만 달러보다 35.9% 늘었다{tok}.\n주요 하이퍼스케일 고객의 설비 투자 확대가 내년까지 이어질 것이다.",
            "리스크": "고객사가 설비 투자를 미루면 데이터센터 매출 성장이 둔화될 수 있다. 이 경우 비중 확대 논거를 다시 심의한다. 단일 발행자 한도(5%) 안에서만 늘린다.",
            "결정": "IWC 2026-08-27 승인 — 비중 30bp 확대(단일 발행자 한도 확인 조건), 다음 분기 실적 발표 뒤 가정 점검.",
        }
        for title, text in body.items():
            sec = add_section(doc, title, [])
            set_section(doc, sec["step"], text, {"docIds": token_doc_ids(text), "checks": {}, "warnings": [], "calcs": [], "memo": ""})
            mark_ai_draft(doc, sec["step"], text)
        svc.persist(row, doc)
        set_approval(s, sid, "approved", kim, "IWC 2026-08-27 승인")
        # 2) 주간 해외주식 리뷰(작성 중) — 한 섹션만 썼다
        p2 = svc.create(ws, lee, title="주간 해외주식 리뷰 — 10월 다섯째 주", report_type="free")
        sid2 = p2["session"]["id"]
        row2 = svc.row_or_404(sid2)
        doc2 = dict(row2.doc or {})
        doc2["setup"] = {**doc2.get("setup", {}), "subject": "해외주식 포트폴리오", "asOf": "2026-10-30"}
        sec = add_section(doc2, "보유 종목 점검", [])
        text = f"{HLDS}는 데이터센터 매출이 2분기 전년 대비 35.9% 늘어 비중 확대 논거가 유지되고 있다{tok}. 하이퍼스케일 고객의 설비 투자 계획도 그대로다."
        set_section(doc2, sec["step"], text, {"docIds": token_doc_ids(text), "checks": {}, "warnings": [], "calcs": [], "memo": ""})
        mark_ai_draft(doc2, sec["step"], text)
        add_section(doc2, "다음 주 확인할 일정", [])
        svc.persist(row2, doc2)
        print(f"문서: IWC 안건 {sid} (승인됨) · 주간 리뷰 {sid2} (작성 중) · 2분기 인용 {'있음' if tok else '없음'}")


def approve_all(c: httpx.Client, ws: str, label: str) -> None:
    rows = [x for x in c.get(f"/workspaces/{ws}/criteria").raise_for_status().json()["criteria"] if x["status"] == "draft" and x["canApprove"]]
    for x in rows:
        c.post(f"/criteria/{x['id']}/decide", json={"approve": True}).raise_for_status()
    print(f"  {label}: {len(rows)}개 승인")


def replay(kim: httpx.Client, ws: str) -> None:
    r1 = kim.post(f"/workspaces/{ws}/criteria/scan", json={"asOf": "2026-09-30"}).raise_for_status().json()
    print(f"재현 2026-09-30(2분기 +35.9%, 기준선): 제안 {r1['proposals']}건 · 대상 {r1['targets']}개")
    r2 = kim.post(f"/workspaces/{ws}/criteria/scan", json={"asOf": "2026-10-29"}).raise_for_status().json()
    print(f"재현 2026-10-29(3분기 10-Q +24.0%): 제안 {r2['proposals']}건")
    for p in kim.get(f"/workspaces/{ws}/proposals", params={"status": "open"}).raise_for_status().json()["proposals"]:
        print(f"  - [{p['reportTitle']}] {p['directionKo']} 검토 제안 · 기준 {p['criterion'].get('title')} v{p['criterion'].get('version')}")
        print(f"    {p['changed']}")
        for h in p["headroom"]:
            print(f"    여유: {h['display']}")
        for sx in p["sentences"]:
            print(f"    걸린 문장: {sx['plain'][:70]} → {(sx['revised'] or '(확인할 문장)')[:90]}")
        dec = (p["evidence"] or {}).get("decision") or {}
        print(f"    근거: 데이터 {len((p['evidence'] or {}).get('data') or [])}칸 · 기준 원문 {'있음' if p['criterion'].get('anchor') else '없음'} · 과거 결정 “{(dec.get('quote') or '')[:50]}”")


def reset(ws: str) -> None:
    """재현을 처음부터 — 이 워크스페이스의 검토 제안을 지우고 기준의 대상별 지난 판정(바뀜 감지)을 비운다(시연 데이터만)."""
    sys.path.insert(0, str(BACK))
    os.chdir(BACK)
    from sqlmodel import Session, select

    from app.db import Criterion, ReviewProposal, engine

    with Session(engine) as s:
        n = 0
        for p in s.exec(select(ReviewProposal).where(ReviewProposal.workspace_id == ws)).all():
            s.delete(p)
            n += 1
        for c in s.exec(select(Criterion).where(Criterion.workspace_id.in_(["", ws]))).all():  # type: ignore[attr-defined]
            c.latest = {}
            s.add(c)
        s.commit()
    print(f"초기화: 검토 제안 {n}건 지움 · 기준 판정 기록 비움")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8200")
    ap.add_argument("--scan", action="store_true", help="이미 만든 워크스페이스에서 재현만")
    ap.add_argument("--reset", action="store_true", help="--scan 전에 제안·판정 기록을 비운다")
    ap.add_argument("--reports", action="store_true", help="--scan 전에 시연 문서 두 편을 지우고 다시 만든다")
    args = ap.parse_args()
    kim, lee = client(KIM, args.base), client(LEE, args.base)
    if args.scan:
        ws = WS_FILE.read_text().strip()
        if args.reports:
            for r in kim.get(f"/workspaces/{ws}/reports").raise_for_status().json()["reports"]:
                if r["title"].startswith(("IWC 안건 — ", "주간 해외주식 리뷰")):
                    lee.delete(f"/sessions/{r['id']}").raise_for_status()
            in_process_reports(ws)
        if args.reset or args.reports:
            reset(ws)
        replay(kim, ws)
        return 0

    ws = kim.post("/workspaces", json={"name": "해외주식운용실 — HLDS(가상)", "kind": "free", "description": "판단 기준 루프 시연(가상 기업 HLDS)"}).raise_for_status().json()
    ws_id = ws.get("id") or ws.get("workspace", {}).get("id")
    kim.post(f"/workspaces/{ws_id}/members", json={"userId": LEE, "role": "editor"}).raise_for_status()
    WS_FILE.write_text(ws_id)
    print(f"워크스페이스 {ws_id}")

    files = [ROOT / "demo/assumptions/IWC_회의록_2026-08-27.md", ROOT / "demo/houseview/하우스뷰_2026Q3.md"]
    kim.post(f"/workspaces/{ws_id}/documents", files=[("files", (p.name, p.read_bytes())) for p in files]).raise_for_status()
    docs = wait_docs(kim, ws_id)
    by = lambda word: next((d for d in docs if word in (d.get("title") or d.get("label") or "") or word in (d.get("fileName") or "")), None)  # noqa: E731
    minutes, house, policy = by("회의록"), by("하우스뷰"), by("투자정책")
    if not policy:
        raise SystemExit("사내 투자정책서가 없습니다 — demo/company/seed_company.py 먼저")

    in_process_reports(ws_id)

    print("판단 기준 뽑기")
    for d, scope, label in ((policy, "company", "투자정책서(사내)"), (house, "company", "하우스뷰 2026Q3(사내)"), (minutes, "workspace", "IWC 회의록(워크스페이스)")):
        if not d:
            print(f"  {label}: 자료 없음 — 건너뜀")
            continue
        r = kim.post(f"/workspaces/{ws_id}/criteria/extract", json={"docKind": "data", "docRef": d["id"], "scope": scope}).raise_for_status().json()
        print(f"  {label}: 초안 {r['made']}개(찾음 {r['found']})")
    approve_all(kim, ws_id, "김민준 승인")
    for x in kim.get(f"/workspaces/{ws_id}/criteria").raise_for_status().json()["criteria"]:
        if x["status"] == "active":
            print(f"  [{x['scopeKo']} v{x['version']}] {x['title']}: {x['conditionText']} → {x['directionKo']} · 대상 {x['applies'].get('name') or x['applies'].get('assetClass') or '전체'}")
    replay(kim, ws_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
