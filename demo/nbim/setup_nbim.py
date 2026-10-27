"""NBIM 양식 데모 준비 — 워크스페이스 'NBIM (공개 자료 가정)' + 성과 데이터 엑셀 + 보도자료 + 반기 운용보고서(NBIM 양식) 리포트.

  backend/.venv/Scripts/python demo/nbim/make_pack.py        (데이터 워크북)
  backend/.venv/Scripts/python demo/nbim/fetch_sources.py    (보도자료 받기)
  backend/.venv/Scripts/python demo/nbim/setup_nbim.py       (백엔드 8200 이 떠 있어야 한다)

원본 반기 보고서 PDF(demo/public_samples/03_…)는 올리지 않는다 — 작성 결과와 비교할 정답지.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
PACK = HERE / "NBIM_2025H1_성과데이터.xlsx"
SOURCES = sorted((HERE / "sources").glob("*.md"))
OWNER = "u_kim"
MEMBERS = [("u_lee", "editor"), ("u_park", "editor")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8200")
    ap.add_argument("--fe", default="http://localhost:3200")
    args = ap.parse_args()
    if not PACK.exists() or not SOURCES:
        print("먼저 make_pack.py 와 fetch_sources.py 를 돌리세요.")
        return 1
    c = httpx.Client(base_url=f"{args.base}/api", headers={"X-User-Id": OWNER}, timeout=120)
    ws = c.post("/workspaces", json={"name": "NBIM (공개 자료 가정)", "kind": "quarterly", "description": "노르웨이 국부펀드 공개 자료로 반기 운용보고서 양식을 시험하는 워크스페이스"}).raise_for_status().json()
    wid = ws.get("id") or ws["workspace"]["id"]
    for uid, role in MEMBERS:
        c.post(f"/workspaces/{wid}/members", json={"userId": uid, "role": role}).raise_for_status()
    files = [("files", (p.name, p.read_bytes())) for p in [PACK, *SOURCES]]
    c.post(f"/workspaces/{wid}/documents", files=files).raise_for_status()
    print("워크스페이스", wid, "— 자료 처리 기다리는 중", end="", flush=True)
    for _ in range(180):
        d = c.get(f"/workspaces/{wid}/documents").raise_for_status().json()
        docs, pending = d.get("documents") or [], [j for j in d.get("jobs") or [] if j.get("status") not in ("done", "error")]
        if len(docs) >= 1 + len(SOURCES) and not pending and all(x.get("embedded") for x in docs):
            break
        print(".", end="", flush=True)
        time.sleep(2)
    print()
    for x in c.get(f"/workspaces/{wid}/documents").json().get("documents") or []:
        print("  자료:", x["label"], "·", x.get("fileName"))
    rep = c.post(f"/workspaces/{wid}/reports", json={"title": "NBIM 2025 상반기 운용보고서", "reportType": "nbim_half_year"}).raise_for_status().json()
    sid = (rep.get("session") or rep).get("id")
    c.patch(f"/sessions/{sid}", json={"setup": {"subject": "NBIM(노르웨이 국부펀드) — 공개 자료 가정", "asOf": "2025-06-30", "audience": "운영위원회"}}).raise_for_status()
    (HERE / ".ws").write_text(wid, encoding="utf-8")
    (HERE / ".report").write_text(sid, encoding="utf-8")
    print("리포트", sid)
    print("양식 찾기 ", f"{args.fe}/?w={wid}&v=reports")
    print("리포트    ", f"{args.fe}/?w={wid}&v=reports&s={sid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
