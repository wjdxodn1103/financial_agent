"""'반도체 리서치' 워크스페이스 시연 자료 — 실행 중인 백엔드(8200)에 HTTP 로 넣는다. 다시 돌려도 된다(같은 날 같은 조건은 같은 스냅샷).

python -I demo/semi/seed_semi.py ws        워크스페이스 만들기(있으면 그대로) + 이서연 편집자
python -I demo/semi/seed_semi.py prices    주가·지수·업종 ETF 일봉 적재(관리자)
python -I demo/semi/seed_semi.py dart      삼성전자·SK하이닉스 DART 재무제표·개황·본문 + 주가 스냅샷
python -I demo/semi/seed_semi.py all       위 셋을 차례로

결과(워크스페이스 id·문서 id)는 demo/semi/state.json 에 남긴다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import httpx

B = "http://127.0.0.1:8200/api"
H = {"X-User-Id": "u_kim"}
NAME = "반도체 리서치"
STATE = Path(__file__).with_name("state.json")
sys.stdout.reconfigure(encoding="utf-8")

COMPANIES = [
    {"name": "삼성전자", "ticker": "005930.KS", "extra": ["005935.KS"]},
    {"name": "SK하이닉스", "ticker": "000660.KS", "extra": []},
]
# 증시 요약 양식에 쓰는 것 — 반도체지수·상해종합·VIX·엔/달러·S&P500 업종 ETF 11개
MARKET_TICKERS = ["^SOX", "000001.SS", "^VIX", "JPY=X", "XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"]
# (연도, 보고서) — 분기 값은 누적값 차이로 구한다(1분기·반기·3분기·사업보고서가 다 있어야 한다)
REPORTS = [(2023, "annual"), (2024, "q1"), (2024, "half"), (2024, "q3"), (2024, "annual"), (2025, "q1"), (2025, "half"), (2025, "q3"), (2025, "annual"),
           (2026, "q1"), (2026, "half"), (2026, "q3")]


def state() -> Dict[str, Any]:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save(st: Dict[str, Any]) -> None:
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def call(method: str, path: str, timeout: float = 300, **kw: Any) -> httpx.Response:
    return httpx.request(method, f"{B}{path}", headers=H, timeout=timeout, **kw)


def ws() -> str:
    st = state()
    rows = call("GET", "/workspaces").json()["workspaces"]
    hit = next((w for w in rows if w["name"] == NAME), None)
    if hit is None:
        r = call("POST", "/workspaces", json={"name": NAME, "kind": "free", "description": "삼성전자·SK하이닉스 — 피어 비교 대시보드·기업분석·아침 증시 요약"})
        r.raise_for_status()
        hit = r.json().get("workspace") or r.json()
        print("만듦", hit["id"])
    else:
        print("있음", hit["id"])
    wid = hit["id"]
    r = call("POST", f"/workspaces/{wid}/members", json={"userId": "u_lee", "role": "editor"})
    print("이서연 편집자", r.status_code)
    st["workspace"] = wid
    save(st)
    return wid


def prices() -> None:
    tickers = [t for c in COMPANIES for t in [c["ticker"], *c["extra"]]] + MARKET_TICKERS
    for i in range(0, len(tickers), 10):
        r = call("POST", "/market/prices/load", json={"tickers": tickers[i:i + 10], "days": 1500}, timeout=600)
        for row in r.json().get("loaded") or r.json().get("results") or [r.json()]:
            print("  ", json.dumps(row, ensure_ascii=False)[:200])


def dart() -> None:
    st = state()
    wid = st.get("workspace") or ws()
    docs: Dict[str, List[Dict[str, Any]]] = st.setdefault("docs", {})
    for c in COMPANIES:
        found = call("GET", f"/workspaces/{wid}/connectors/dart/companies", params={"q": c["name"]}, timeout=180).json()["companies"]
        corp = next(x for x in found if x["corpName"] == c["name"] and x.get("stockCode"))
        c["corpCode"] = corp["corpCode"]
        print(c["name"], corp["corpCode"], corp["stockCode"])
        got: List[Dict[str, Any]] = []

        def keep(kind: str, r: httpx.Response, label: str) -> None:
            if r.status_code != 200:
                print(f"   ✗ {label}: {r.status_code} {r.text[:160]}")
                return
            d = r.json().get("document") or {}
            got.append({"kind": kind, "id": d.get("id"), "title": r.json().get("title"), "label": label})
            print(f"   ✓ {label}: {d.get('id')} · 수치 {r.json().get('figures')}")

        base = {"corpCode": corp["corpCode"], "corpName": c["name"]}
        for year, rep in REPORTS:
            keep("fin", call("POST", f"/workspaces/{wid}/connectors/dart/financials", json={**base, "year": year, "report": rep, "fs": "CFS"}), f"{year} {rep}")
        keep("overview", call("POST", f"/workspaces/{wid}/connectors/dart/overview", json={**base, "days": 365}), "개황·공시 목록")
        keep("body", call("POST", f"/workspaces/{wid}/connectors/dart/business", json={**base, "year": 2025, "report": "annual"}, timeout=600), "사업보고서 본문 2025")
        keep("price", call("POST", f"/workspaces/{wid}/connectors/prices/snapshot", json={"ticker": c["ticker"], "name": c["name"], "days": 365}), "주가 스냅샷")
        docs[c["name"]] = got
        st.setdefault("corp", {})[c["name"]] = {"corpCode": corp["corpCode"], "ticker": c["ticker"]}
        save(st)


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("ws", "all"):
        ws()
    if step in ("prices", "all"):
        prices()
    if step in ("dart", "all"):
        dart()


# ── 증권사 리포트(네이버 증권 리서치 공개 PDF) ──────────────────────────
# (종목코드, 회사, 리포트 번호) — 2026-11-10 사용자 허락을 받아 4건만 내려받는다. 파일은 저장소 밖 폴더에 둔다(재배포하지 않는다).
BROKER_REPORTS = [("005930", "삼성전자", 97370), ("005930", "삼성전자", 97339), ("000660", "SK하이닉스", 97251), ("000660", "SK하이닉스", 97256)]
NAVER = {"User-Agent": "Mozilla/5.0", "Referer": "https://stock.naver.com/research/company"}


def reports(folder: str) -> None:
    import re
    import time

    st = state()
    wid = st["workspace"]
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    have = {d.get("fileName") for d in call("GET", f"/workspaces/{wid}/documents").json()["documents"]}
    made = st.setdefault("reports", {})
    for _code, company, rid in BROKER_REPORTS:
        info = httpx.get(f"https://m.stock.naver.com/api/research/company/{rid}", headers=NAVER, timeout=30).json()["researchContent"]
        url = next(v for v in info.values() if isinstance(v, str) and v.endswith(".pdf"))
        name = re.sub(r'[\/:*?"<>|]', " ", f"{info['brokerName']}_{company}_{info['writeDate']}_{info['title']}")[:90] + ".pdf"
        path = out / name
        if not path.exists():
            pdf = httpx.get(url, headers=NAVER, timeout=120)
            pdf.raise_for_status()
            path.write_bytes(pdf.content)
        print(f"  {name} · {path.stat().st_size / 1e6:.1f}MB")
        made[name] = {"company": company, "broker": info["brokerName"], "date": info["writeDate"], "title": info["title"], "url": url}
        if name in have:
            continue
        with open(path, "rb") as f:
            r = call("POST", f"/workspaces/{wid}/documents", files={"files": (name, f, "application/pdf")}, timeout=300)
        print("    올림", r.status_code, (r.json().get("errors") or ""))
    save(st)
    for _ in range(60):  # 처리(추출·청킹)가 끝날 때까지
        jobs = [j for j in call("GET", f"/workspaces/{wid}/documents").json().get("jobs") or [] if j.get("status") not in ("done", "error")]
        if not jobs:
            break
        time.sleep(3)
    docs = {d.get("fileName"): d for d in call("GET", f"/workspaces/{wid}/documents").json()["documents"]}
    for name, meta in made.items():
        d = docs.get(name)
        if not d:
            print("  ✗ 처리 안 됨", name)
            continue
        meta["id"] = d["id"]
        print(f"  ✓ {d['id']} · {d.get('docType')} · {d.get('issuer')} · {d.get('company')} · {d.get('date')} · {d.get('pageCount')}쪽 · 청크 {d.get('chunkCount')}")
    save(st)


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[1] == "reports":
    reports(sys.argv[2])


def cards() -> None:
    """올린 증권사 리포트의 카드를 정확한 값으로(발행처·회사·날짜·제목) — 자동 카드는 임시 값이라 직접 적는다(파일만 고친다)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    from app.docs.store import load_meta, save_meta

    for name, r in (state().get("reports") or {}).items():
        if not r.get("id"):
            continue
        meta = load_meta(r["id"]) or {}
        meta["card"] = {**(meta.get("card") or {}), "title": f"{r['company']} — {r['title']}", "docType": "애널리스트 리포트", "issuer": r["broker"], "company": r["company"], "date": r["date"],
                        "oneLine": f"{r['broker']} 기업분석 리포트({r['date']})"}
        meta["enriched"] = True
        meta["snapshot"] = {**(meta.get("snapshot") or {}), "connector": "upload", "url": r["url"], "publishedAt": r["date"]}
        save_meta(r["id"], meta)
        print("  ✓", r["id"], meta["card"]["title"], "·", r["broker"])


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "cards":
    cards()


# ── 반복 업무(루틴) ─────────────────────────────────────────────────────
# 아침 증시 요약만 실제로 돌린다(run). 나머지는 등록만 — 다음 실행 시각에 '예정'으로 보인다.
ROUTINES = [
    {"name": "전날 증시 요약 리포트", "formatId": "rt:kicmarketdaily", "schedule": {"every": "daily", "time": "07:00"},
     "instruction": "전일 미국·한국·아시아 증시와 금리·환율·원자재, 업종별 등락률, 경제지표 일정을 정해진 양식으로 정리한다."},
    {"name": "삼성전자 기업분석 갱신", "formatId": None, "schedule": {"every": "weekly", "time": "08:00", "weekday": 4},
     "instruction": "삼성전자(코스피 005930) 기업분석 보고서. 새로 들어온 공시·리포트를 반영한다."},
    {"name": "주간 리스크 지표 점검", "formatId": "rt:kicrisk", "schedule": {"every": "weekly", "time": "16:00", "weekday": 4}, "instruction": "한 주 동안의 주요 위험지표 변화와 한도 점검."},
    {"name": "월간 투자분석 초안", "formatId": "rt:kicmonthly", "schedule": {"every": "weekly", "time": "09:00", "weekday": 0}, "instruction": "시장 환경과 자산군별 성과를 초안으로."},
    {"name": "IC 심의 요약 정리", "formatId": "rt:kicicminutes", "schedule": {"every": "manual", "time": "07:00"}, "instruction": "회의록이 올라오면 안건별 쟁점·결정 사항을 정리한다."},
]


def routines(run: bool = False) -> None:
    import time

    st = state()
    wid = st["workspace"]
    have = {r["name"]: r for r in call("GET", f"/workspaces/{wid}/routines").json()["routines"]}
    for spec in ROUTINES:
        body = {**spec, "formatId": spec["formatId"] or st.get("format"), "recipients": {"all": True}}
        if spec["name"] in have:
            print("  있음", spec["name"])
            continue
        r = call("POST", f"/workspaces/{wid}/routines", json=body)
        print("  등록", spec["name"], r.status_code, r.text[:120] if r.status_code >= 300 else "")
    if not run:
        return
    rows = {r["name"]: r for r in call("GET", f"/workspaces/{wid}/routines").json()["routines"]}
    rid = rows[ROUTINES[0]["name"]]["id"]
    r = call("POST", f"/routines/{rid}/run", json={})
    print("  실행", r.status_code, r.text[:160])
    for _ in range(80):
        time.sleep(5)
        last = (call("GET", f"/routines/{rid}/runs").json()["runs"] or [{}])[0]
        if last.get("status") != "running":
            print("  결과", json.dumps(last, ensure_ascii=False)[:400])
            st["dailyRoutine"], st["dailyReport"] = rid, last.get("reportId")
            save(st)
            break


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "routines":
    routines(run="--run" in sys.argv)
