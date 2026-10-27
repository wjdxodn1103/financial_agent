"""일시적 업스트림 오류 1회 재시도 — StatUpAI OP-BE `core/llm/retry.py` 그대로.

5xx·429·"overloaded|timeout|index out of range" 이면 1.5초 뒤 한 번 더.
스트림은 첫 조각을 받기 전까지만 재시도한다 — 조각을 낸 뒤 실패하면 그대로 올린다(중복 출력 방지).
"""
import asyncio
import re
from typing import AsyncIterator, Awaitable, Callable, TypeVar

from app.llm.base import LlmError, StreamDelta

_TRANSIENT = re.compile(r"index out of range|overloaded|timeout|timed out|ECONNRESET|connection", re.IGNORECASE)

T = TypeVar("T")


def is_transient(err: BaseException) -> bool:
    if not isinstance(err, LlmError):
        return False
    if err.code in ("RATE_LIMITED", "PROVIDER_UNREACHABLE"):
        return True
    if err.code == "PROVIDER_ERROR" and _TRANSIENT.search(err.message or ""):
        return True
    # 5xx 는 메시지에 상태 코드가 들어 있다("LLM 서버 오류 (503)")
    return bool(err.code == "PROVIDER_ERROR" and re.search(r"\((5\d\d)\)", err.message or ""))


async def with_retry(call: Callable[[], Awaitable[T]], *, attempts: int = 2, delay_s: float = 1.5) -> T:
    """비스트리밍 호출 재시도."""
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return await call()
        except LlmError as e:
            last = e
            if i + 1 >= attempts or not is_transient(e):
                raise
            await asyncio.sleep(delay_s)
    assert last is not None
    raise last


async def stream_with_retry(
    make: Callable[[], AsyncIterator[StreamDelta]], *, attempts: int = 2, delay_s: float = 1.5
) -> AsyncIterator[StreamDelta]:
    """스트림 재시도 — 아직 아무 조각도 내지 않았을 때만."""
    for i in range(attempts):
        yielded = False
        try:
            async for delta in make():
                yielded = True
                yield delta
            return
        except LlmError as e:
            if yielded or i + 1 >= attempts or not is_transient(e):
                raise
            await asyncio.sleep(delay_s)
