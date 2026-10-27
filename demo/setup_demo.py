"""데모 준비 — 깨끗한 워크스페이스 하나를 API 로 만든다(백엔드 8200 이 떠 있어야 한다).

  backend/.venv/Scripts/python demo/setup_demo.py            → 워크스페이스·멤버·자료 5개·리포트·사내 양식
  backend/.venv/Scripts/python demo/setup_demo.py --base http://localhost:8200

만드는 것
  - 워크스페이스 'A사 투자 검토'(딜) — 김민준 팀장(소유자) · 이서연 과장 · 박지훈 대리(편집자)
  - 자료 4개(IR PDF · 실적 요약 DOCX · 손익 엑셀 · 증권사 리포트 MD) → 근거 원장
  - 타 부서 초안 DOCX 는 올리되 '근거 제외'로 둔다(검수 대상 — 틀린 숫자가 원장에 들어가지 않게)
  - 리포트 'A사 투자 검토 보고서'(기업 분석) + 사내 양식 DOCX 등록
자료가 없으면 먼저 demo/make_materials.py 를 돌린다. 만든 id 는 demo/.demo_ws · demo/.demo_report 에 남긴다.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
MAT = HERE / "materials"
EVIDENCE = ["A사_2024_IR.pdf", "A사_2024_실적요약.docx", "A사_손익요약.xlsx", "B증권_A사_분석.md"]
DRAFT = "투자검토보고서_초안_투자전략팀.docx"
TEMPLATE = "사내양식_투자검토보고서.docx"
OWNER = "u_kim"
MEMBERS = [("u_lee", "editor"), ("u_park", "editor")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8200")
    ap.add_argument("--fe", default="http://localhost:3200")
    ap.add_argument("--workspace", default="", help="이미 만든 워크스페이스 id — 만들기·올리기를 건너뛰고 나머지(근거 제외·리포트·양식)만")
    args = ap.parse_args()
    missing = [n for n in [*EVIDENCE, DRAFT, TEMPLATE] if not (MAT / n).exists()]
    if missing:
        print("자료가 없습니다 — 먼저 demo/make_materials.py 를 돌리세요:", ", ".join(missing))
        return 1
    c = httpx.Client(base_url=f"{args.base}/api", headers={"X-User-Id": OWNER}, timeout=120)

    if args.workspace:
        wid = args.workspace
    else:
        ws = c.post("/workspaces", json={"name": "A사 투자 검토", "kind": "deal", "description": "A사(가상) 데이터센터 인프라 — 투자 검토 데모"}).raise_for_status().json()
        wid = ws.get("id") or ws["workspace"]["id"]
        for uid, role in MEMBERS:
            c.post(f"/workspaces/{wid}/members", json={"userId": uid, "role": role}).raise_for_status()
        files = [("files", (n, (MAT / n).read_bytes())) for n in [*EVIDENCE, DRAFT]]
        c.post(f"/workspaces/{wid}/documents", files=files).raise_for_status()
    print("워크스페이스", wid)
    print("자료 처리 기다리는 중", end="", flush=True)
    docs = []
    for _ in range(180):  # 최대 6분
        d = c.get(f"/workspaces/{wid}/documents").raise_for_status().json()
        docs = d.get("documents") or []
        pending = [j for j in d.get("jobs") or [] if j.get("status") not in ("done", "error")]
        if len(docs) >= 5 and not pending and all(x.get("embedded") for x in docs):
            break
        print(".", end="", flush=True)
        time.sleep(2)
    print()
    errors = [j for j in (c.get(f"/workspaces/{wid}/documents").json().get("jobs") or []) if j.get("status") == "error"]
    if errors:
        print("처리 실패:", errors)
        return 1
    # 같은 내용의 파일은 전에 올린 자료를 다시 쓴다(파일 이름도 처음 올린 것) — 이름이 다르면 카드 제목으로 찾는다
    draft = next((x for x in docs if x.get("fileName") == DRAFT), None) or next((x for x in docs if "초안" in (x.get("label") or "")), None)
    if draft is None:
        print("초안이 목록에 없습니다 — 처리 결과를 확인하세요.")
        return 1
    c.post(f"/workspaces/{wid}/documents/{draft['id']}/evidence", json={"use": False}).raise_for_status()
    print("초안 근거 제외:", draft["label"])

    rep = c.post(f"/workspaces/{wid}/reports", json={"title": "A사 투자 검토 보고서", "reportType": "equity"}).raise_for_status().json()
    sid = (rep.get("session") or rep).get("id")
    c.post(f"/sessions/{sid}/template", files={"file": (TEMPLATE, (MAT / TEMPLATE).read_bytes())}).raise_for_status()
    print("리포트", sid, "+ 사내 양식")

    (HERE / ".demo_ws").write_text(wid, encoding="utf-8")
    (HERE / ".demo_report").write_text(sid, encoding="utf-8")
    print()
    print("홈      ", f"{args.fe}/?w={wid}")
    print("리포트  ", f"{args.fe}/?w={wid}&v=reports&s={sid}")
    print("원장    ", f"{args.fe}/?w={wid}&v=ledger")
    print("검수    ", f"{args.fe}/?w={wid}&v=reviews")
    print("대화    ", f"{args.fe}/?w={wid}&v=channel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
