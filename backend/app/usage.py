"""사용 귀속 — 지금 요청·작업이 누구(user)·어느 워크스페이스(ws)·어떤 기능(feature)·어떤 실행(run)인지.

 - LLM 사용량 로그(`llm/client._log_usage`)가 줄마다 이 값을 남긴다 → 품질·이용 지표를 사람·워크스페이스·기능별로 본다.
 - 같은 실행(루틴·수집) 안의 LLM 호출 수를 센다 → 실행 상한(calls)에 쓴다.
 - 요청은 `UsageMiddleware` 가(헤더 X-User-Id·경로의 워크스페이스), 예약 작업은 시작점에서 `bind(...)` 로 정한다.
   ContextVar 라 요청 안에서 띄운 작업·스레드도 같은 값을 물려받는다.
"""
from __future__ import annotations

import logging
import re
from contextvars import ContextVar, Token
from typing import Any, Dict, Optional
from urllib.parse import parse_qs

log = logging.getLogger(__name__)

_ctx: ContextVar[Optional[Dict[str, Any]]] = ContextVar("dcf_usage", default=None)
_WS_RX = re.compile(r"/api/workspaces/([^/]+)")


def current() -> Dict[str, Any]:
    return _ctx.get() or {}


def bind(*, user: Optional[str] = None, ws: Optional[str] = None, feature: Optional[str] = None, run: Optional[str] = None, fresh_count: bool = False) -> Token:
    """값을 덧씌운다(None 은 그대로). fresh_count 면 LLM 호출 수를 새로 센다(실행 하나 = 새 카운터)."""
    cur = current()
    ctx = {**cur, **{k: v for k, v in {"user": user, "ws": ws, "feature": feature, "run": run}.items() if v is not None}}
    ctx["calls"] = [0] if fresh_count or "calls" not in cur else cur["calls"]  # 리스트 — 복사된 문맥끼리 같은 카운터를 센다
    return _ctx.set(ctx)


def reset(token: Token) -> None:
    try:
        _ctx.reset(token)
    except ValueError:  # 다른 문맥에서 만든 토큰(작업 안에서 다시 묶은 경우) — 그대로 둔다
        pass


def count_call() -> None:
    c = current().get("calls")
    if c:
        c[0] += 1


def calls() -> int:
    c = current().get("calls")
    return int(c[0]) if c else 0


def _feature(path: str) -> str:
    """/api/workspaces/{w}/search → search, /api/sessions/{s}/chat → chat — 마지막 '이름' 마디(id 처럼 숫자가 든 마디는 건너뜀)."""
    parts = [p for p in path.split("/")[2:] if p and not any(ch.isdigit() for ch in p) and len(p) < 24]
    return parts[-1] if parts else "api"


class UsageMiddleware:
    """순수 ASGI 미들웨어 — 스트리밍 응답(SSE)이 끝날 때까지 같은 문맥으로 돈다(BaseHTTPMiddleware 는 그렇지 않다)."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not str(scope.get("path", "")).startswith("/api/"):
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        user = headers.get("x-user-id") or (parse_qs((scope.get("query_string") or b"").decode("latin-1")).get("uid") or [None])[0]
        m = _WS_RX.match(path)
        token = bind(user=user, ws=m.group(1) if m else None, feature=_feature(path), fresh_count=True)
        try:
            await self.app(scope, receive, send)
        finally:
            reset(token)


def activity(kind: str, ref: Optional[Dict[str, Any]] = None, meta: Optional[Dict[str, Any]] = None, *, user: Optional[str] = None, ws: Optional[str] = None) -> None:
    """이용 기록 한 줄(짧은 세션). 실패해도 본 작업을 막지 않는다."""
    from sqlmodel import Session

    from app.db import ActivityEvent, engine
    from app.ids import id36

    ctx = current()
    try:
        with Session(engine) as s:
            s.add(ActivityEvent(id=id36("a", 6), user_id=user or ctx.get("user") or "", workspace_id=ws or ctx.get("ws") or "", kind=kind, ref=ref or {}, meta={**(meta or {}), "feature": ctx.get("feature") or ""}))
            s.commit()
    except Exception:  # noqa: BLE001
        log.exception("activity log failed: %s", kind)
