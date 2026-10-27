"""사내 공용 데이터(더미)를 백엔드에 넣는다 — 모든 워크스페이스가 기본으로 쓰는 데이터. 백엔드 8200 이 떠 있어야 한다.

  backend/.venv/Scripts/python demo/company/make_company_data.py
  backend/.venv/Scripts/python demo/company/seed_company.py

같은 파일을 다시 넣으면 문서 저장소가 같은 문서로 알아보고 사내 목록에 한 번만 남는다.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

DATA = Path(__file__).resolve().parent / "data"
OWNER = "u_kim"  # 사내 공용 데이터는 워크스페이스 소유자만 넣는다(데모 계정)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8200")
    args = ap.parse_args()
    files = sorted(p for p in DATA.iterdir() if p.is_file()) if DATA.exists() else []
    if not files:
        print("먼저 make_company_data.py 를 돌리세요.")
        return 1
    c = httpx.Client(base_url=f"{args.base}/api", headers={"X-User-Id": OWNER}, timeout=120)
    # 이미 들어간 파일 이름은 건너뛴다(엑셀은 만들 때마다 내부 시각이 달라 다른 문서로 들어가므로 이름으로 막는다)
    have = {d.get("fileName") for d in c.get("/company/documents").raise_for_status().json().get("documents") or []}
    todo = [p for p in files if p.name not in have]
    r = {"documents": []}
    if todo:
        r = c.post("/company/documents", files=[("files", (p.name, p.read_bytes())) for p in todo]).raise_for_status().json()
        if r.get("errors"):
            print("거절:", r["errors"])
    else:
        print("이미 모두 들어가 있습니다.")
    print("처리 기다리는 중", end="", flush=True)
    for _ in range(120):
        r = c.get("/company/documents").raise_for_status().json()
        if not r.get("jobs"):
            break
        print(".", end="", flush=True)
        time.sleep(2)
    print()
    for d in r.get("documents") or []:
        print(f"- {d['label']} · {d.get('size', 0):,}B · 임베딩 {'됨' if d.get('embedded') else '대기'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
