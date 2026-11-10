"""대시보드 양식 — 요청이 양식에 맞으면 AI 는 양식 이름과 인자만 고르고, 구성(spec)은 코드가 만든다(위젯 배치를 AI 가 지어내지 않게).

양식을 더할 때: TEMPLATES 에 한 줄 + build 가지 + 그 양식의 위젯(widgets.WIDGETS·resolve.widget_data·화면 widgets.tsx).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from app.db import User

TEMPLATES: Dict[str, Dict[str, Any]] = {
    "peer": {
        "label": "피어 비교",
        "desc": "상장사 2~3곳의 실적·밸류에이션·주가·산업 전망을 맞대어 보고, 관련 뉴스·리포트를 함께 본다",
        "kinds": ("workspace",),
        "answer": '{"summary": "무엇을 만들었는지 한 문장", "template": "peer", "companies": ["회사 이름", "회사 이름"]}',
    },
}


def catalog_text(kind: str) -> str:
    rows = [(k, t) for k, t in TEMPLATES.items() if kind in t["kinds"]]
    if not rows:
        return ""
    lines = ["양식(요청이 아래에 맞으면 spec 대신 그 양식의 답 꼴로만 답한다):"]
    lines += [f"- {k}: {t['label']} — {t['desc']} · 답: {t['answer']}" for k, t in rows]
    return "\n".join(lines)


def label_of(spec: Dict[str, Any]) -> Optional[Dict[str, str]]:
    t = TEMPLATES.get(str((spec or {}).get("template") or ""))
    return {"id": spec["template"], "label": t["label"]} if t else None


async def build(got: Dict[str, Any], kind: str, workspace_id: str, user: User, llm: Any = None) -> Optional[Dict[str, Any]]:
    """AI 답이 양식이면 → 구성(spec). 양식이 아니면 None. 자료가 없으면 받아 온다(DART·일봉·뉴스 제목)."""
    tid = str(got.get("template") or "")
    if tid not in TEMPLATES or kind not in TEMPLATES[tid]["kinds"]:
        return None
    if tid == "peer":
        from app.dashboards import peer

        names: List[str] = [str(n) for n in got.get("companies") or [] if str(n).strip()]
        companies = await run_in_threadpool(peer.resolve_companies, names)
        if len(companies) < 2:
            raise HTTPException(400, "비교할 상장사 2곳을 찾지 못했습니다. 회사 이름을 다시 적어 주세요.")
        await run_in_threadpool(peer.ensure_data, workspace_id, user.id, companies)
        outlook = await peer.outlook(workspace_id, companies, llm)
        title = " · ".join(c["name"] for c in companies)
        return {"template": "peer", "widgets": [{"type": "peer_board", "title": f"{title} 피어 비교", "size": "full", "params": {"companies": companies, "outlook": outlook}}]}
    return None
