"""양식 2.0 시험 — 등록된 양식의 틀(blueprint)을 샘플 PDF 로 다시 만든다(LLM 일반화 포함). 문서 id 를 주면 그 문서에 복사된 틀도 바꾼다.

python -I demo/kirs/rebuild_format.py <양식 id(rt: 뺀 것)> [문서 id …]
양식 이름(사용자가 붙인 것)은 그대로 두고 틀·v1 섹션·에셋만 바꾼다. 표·그림 id 는 골격이 같으면 같다(문서 섹션의 blocks 가 그대로 맞는다).
"""
from __future__ import annotations

import asyncio
import copy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from sqlmodel import Session  # noqa: E402

from app.db import ReportSession, ReportTemplate, engine  # noqa: E402
from app.llm.client import ReportLlm  # noqa: E402
from app.templates_import.blueprint import build_blueprint  # noqa: E402

PDF = HERE.parent / "public_samples" / "07_kirs_sbbtech_2026-01.pdf"


async def main(tid: str, doc_ids: list[str]) -> None:
    out = await build_blueprint(str(PDF), PDF.name, ReportLlm())
    bp = out["blueprint"]
    with Session(engine) as s:
        t = s.get(ReportTemplate, tid)
        spec = copy.deepcopy(t.spec)
        old = spec.get("blueprint") or {}
        bp["name"] = old.get("name") or bp["name"]
        spec["blueprint"] = bp
        t.spec = spec
        s.add(t)
        for d in doc_ids:
            row = s.get(ReportSession, d)
            doc = copy.deepcopy(row.doc)
            doc["layout"] = copy.deepcopy(bp)
            # 섹션의 표·그림 자리도 새 틀대로(covers 'c4_1' = 장 c4 의 첫 소주제, 요약은 본문+사이드바)
            for sec in doc.get("sections") or []:
                cov = (sec.get("covers") or [""])[0]
                part = next((p for p in bp["parts"] if cov.startswith(p["id"] + "_")), None)
                if part is not None:
                    k = int(cov.split("_")[1]) - 1
                    if k < len(part.get("subtopics") or []):
                        sec["blocks"] = list(part["subtopics"][k].get("blocks") or [])
                elif cov == "summary":
                    summ = next((p for p in bp["parts"] if p["role"] == "summary"), {})
                    sec["blocks"] = list(summ.get("blocks") or []) + list(summ.get("sidebar") or [])
            row.doc = doc
            s.add(row)
        s.commit()
    missing = {b for p in bp["parts"] for st in p.get("subtopics") or [] for b in st.get("blocks") or []} - set(bp["forms"])
    print("forms", len(bp["forms"]), "missing ids", missing or "-")
    for f in bp["forms"].values():
        if f.get("sampleTitle"):
            print(f"  {f['kind']:6} {f['sampleTitle']}  →  {f['title']}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2:]))
