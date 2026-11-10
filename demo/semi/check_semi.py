"""반도체 리서치 시연 확인 — 서버·LLM 없이. python -I demo/semi/check_semi.py [shares|board]
shares = 두 회사의 '주식의 총수 현황'을 받아 워크스페이스에 붙인다(DART 호출). board = 피어 비교 값을 찍고 원장과 맞는지 본다."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
ST = json.loads(Path(__file__).with_name("state.json").read_text(encoding="utf-8"))
WS = ST["workspace"]
COS = [{"name": n, "corpCode": c["corpCode"], "stockCode": c["ticker"].split(".")[0], "ticker": c["ticker"]} for n, c in ST["corp"].items()]


def shares() -> None:
    from sqlmodel import Session

    from app.connectors import dart
    from app.db import engine
    from app.services.document_service import attach_document

    for c in COS:
        snap = dart.fetch_shares(c["corpCode"], c["name"], 2026, "half")
        with Session(engine) as s:
            attach_document(s, WS, snap["id"])
        print(c["name"], snap["id"], snap["figures"], snap["asOf"])


def board() -> None:
    from app.dashboards import peer

    b = peer.board(WS, {"companies": COS})
    if b.get("error"):
        print("오류", b["error"])
        return
    print("기간", b["period"], "· 주가 기준일", b["priceDate"], "·", b["basis"], "· 빠진 회사", b["missing"])
    for h in b["companies"]:
        print(" ", h["name"], h["code"], f"{h.get('close'):,.0f}", h.get("changePct"), (h.get("marketCap") or {}).get("display"), h.get("returns"), (h.get("marketCap") or {}).get("calc"))
    for m in b["metrics"]:
        print(f"  {m['label']:<22}", " | ".join(f"{(v or {}).get('display', '–'):>10} (근거 {len((v or {}).get('cites', []))})" for v in m["values"]))
    q = b["quarters"]
    print("  분기", q["categories"])
    for s in q["series"]:
        print("   ", s["name"], s["values"])
    r = b["relative"]
    print("  상대수익률 기준일", r["base"], [(s["name"], s["points"][-1]) for s in r["series"]])
    d = b["docs"]
    print("  자료", {k: len(v) for k, v in d.items()})
    # 맞춤 확인 — 최근 4분기 영업이익 = 분기 차트의 마지막 4개 합
    for i, s in enumerate(q["series"]):
        ttm = next(m for m in b["metrics"] if m["id"] == "op")["values"][i]["value"]
        print(f"  확인 {s['name']}: 최근 4분기 영업이익 {ttm:.1f} ↔ 분기 합 {sum(s['values'][-4:]):.1f}")


if __name__ == "__main__":
    {"shares": shares, "board": board}[sys.argv[1] if len(sys.argv) > 1 else "board"]()
