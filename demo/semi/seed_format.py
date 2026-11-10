"""기업분석 보고서(사내 양식)을 '반도체 리서치' 워크스페이스로 복사한다 — 원본 행(rpmvufye1r38e9)은 그대로 둔다.
틀(장 구성·요약 옆 칸·표·그림 모양·색)은 그대로. 원본 샘플(에스비비테크)에서 온 소제목·예시·그림 이름만 어느 회사에나 맞는 말로 바꾼다.
python -I demo/semi/seed_format.py   (다시 돌리면 같은 행을 덮어쓴다)"""
import copy
import json
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
STATE = Path(__file__).with_name("state.json")
SRC, NEW = "rpmvufye1r38e9", "rpsemikirs0001"

SUBTOPICS = {  # 원본 소제목 → (새 소제목, 예시)
    "기업 소개": ("기업 소개", "주력 사업과 설립·상장 이력"),
    "제품 및 매출 구성": ("제품 및 매출 구성", "사업부문별 매출 구성, 주요 제품/서비스"),
    "주요 고객": ("주요 고객", "주요 고객군과 판매 경로"),
    "주요 주주 현황": ("주요 주주 현황", "최대주주 및 특수관계인 지분"),
    "정밀 감속기 산업": ("주력 산업 현황", "주력 사업이 속한 산업의 현황과 전망"),
    "정밀 베어링 산업": ("경쟁 구도", "주요 경쟁사와 점유율 구도"),
    "정밀 감속기 기술력": ("핵심 기술 경쟁력", "핵심 제품의 기술 경쟁력"),
    "로봇 산업 수혜 기대": ("전방 산업 성장 수혜", "전방 산업 투자 확대에 따른 수혜"),
    "경쟁 심화 리스크": ("경쟁 심화 리스크", "경쟁 강도와 업황 변동 리스크"),
}
FIGURES = {  # 그림 자리 이름
    "글로벌 감속기 시장 전망": "주력 산업 시장 전망", "로봇 부품 기업 주가 추이": "동종 기업 주가 추이", "글로벌 베어링 기업 매출액": "글로벌 주요 기업 매출액",
    "국내 베어링 기업 매출액": "국내 주요 기업 매출액", "글로벌 정밀 베어링 시장 전망": "세부 시장 전망", "글로벌 로봇 시장 전망": "전방 산업 시장 전망",
}
ROWS = {"KOSDAQ (1/2)": "KOSPI (1/2)", "매출액(억원)": "매출액(조원)", "영업이익(억원)": "영업이익(조원)", "지배주주순이익(억원)": "지배주주순이익(조원)"}


def main() -> None:
    from sqlmodel import Session

    from app import config
    from app.db import ReportTemplate, engine

    wid = json.loads(STATE.read_text(encoding="utf-8"))["workspace"]
    with Session(engine) as s:
        src = s.get(ReportTemplate, SRC)
        spec = copy.deepcopy(src.spec)
        bp = spec["blueprint"]
        for p in bp["parts"]:
            if p.get("role") == "cover":
                p["examples"] = ["시장ㅣ업종 회사명(종목코드) 한 줄 제목"]
            if p.get("role") == "summary":
                p["examples"] = ["주력 사업과 시장 지위", "산업 전망", "최근 실적 흐름"]
            for st in p.get("subtopics") or []:
                if st.get("title") in SUBTOPICS:
                    st["title"], st["example"] = SUBTOPICS[st["title"]]
        for f in bp["forms"].values():
            if f.get("title") in FIGURES:
                f["title"] = FIGURES[f["title"]]
            f.pop("sampleTitle", None)
            for r in f.get("rows") or []:
                if r.get("label") in ROWS:
                    r["label"] = ROWS[r["label"]]
                    if "조원" in r["label"]:
                        r["unit"], r["decimals"] = "조원", 1
            for lg in (f.get("chart") or {}).get("legend") or []:
                lg["name"] = {"에스비비테크": "{subject}", "KOSDAQ": "KOSPI"}.get(lg.get("name"), lg.get("name"))
        old = ROOT / "backend" / "data" / str(spec.get("sampleFile") or "")
        base = Path(getattr(config, "DATA_DIR", ROOT / "backend" / "data"))
        if spec.get("sampleFile") and (base / spec["sampleFile"]).exists():
            dst = base / "formats" / NEW
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copy2(base / spec["sampleFile"], dst / Path(spec["sampleFile"]).name)
            spec["sampleFile"] = f"formats/{NEW}/{Path(spec['sampleFile']).name}"
        row = s.get(ReportTemplate, NEW) or ReportTemplate(id=NEW)
        row.scope, row.workspace_id, row.owner_id, row.name, row.source_name, row.spec = "workspace", wid, src.owner_id, src.name, src.source_name, spec
        s.add(row)
        s.commit()
        print("양식", f"rt:{NEW}", "→", wid, "· 소제목", [st["title"] for p in bp["parts"] for st in p.get("subtopics") or []])
    st = json.loads(STATE.read_text(encoding="utf-8"))
    st["format"] = f"rt:{NEW}"
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
