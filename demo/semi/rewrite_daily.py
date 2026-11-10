"""이미 만든 '전날 증시 요약 리포트'의 본문(시장 리뷰)만 다시 쓴다 — 루틴 실행 횟수(하루 5번)를 쓰지 않고 문구를 고칠 때.
python -I demo/semi/rewrite_daily.py"""
import asyncio
import copy
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))


async def main() -> None:
    from sqlmodel import Session

    from app.agent.session import mark_ai_draft, set_section
    from app.db import ReportSession, engine
    from app.docs.citations import token_doc_ids
    from app.llm.client import ReportLlm
    from app.market import daily
    from app.services.report_service import _persist_doc

    sid = json.loads(Path(__file__).with_name("state.json").read_text(encoding="utf-8"))["dailyReport"]
    with Session(engine) as s:
        doc = copy.deepcopy(s.get(ReportSession, sid).doc)
    step = doc["sections"][0]["step"]
    res = await daily.write_section(ReportLlm(), doc, step, None)
    set_section(doc, step, res["content"], {"docIds": token_doc_ids(res["content"]), "checks": res["checks"], "warnings": res["warnings"], "calcs": [], "memo": "", "criteria": []})
    mark_ai_draft(doc, step, res["content"])
    _persist_doc(sid, doc)
    print(res["content"])
    print("warnings", res["warnings"])


asyncio.run(main())
