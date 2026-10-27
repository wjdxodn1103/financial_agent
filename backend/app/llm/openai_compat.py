"""OpenAI 호환 `/v1/chat/completions` 스트리밍 어댑터 (httpx).

NVIDIA build(integrate.api.nvidia.com/v1), vLLM, OpenAI 모두 이 규격을 따른다. SDK 는 쓰지 않는다(httpx 로 충분).
StatUpAI OP-BE `core/llm/openai_compat.py` 에서 그대로 옮겼다.

stream(params)/complete(params) 가 도구 호출(tools/tool_choice)·reasoning_effort·response_format·
stream_options.include_usage·호출별 타임아웃을 보내고, delta.reasoning_content(또는 reasoning)·delta.tool_calls[] 를
StreamDelta 로 옮긴다. stream_options 를 거부하는 서버는 옵션 없이 한 번 더 시도한다(_UnsupportedStreamOptions).
"""
import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.llm.base import (
    ChatParams,
    ChatResult,
    LlmError,
    ProviderConfig,
    StreamDelta,
    TestResult,
    ToolCallDelta,
    merge_tool_call_deltas,
    tool_calls_from_acc,
)

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
DEFAULT_TIMEOUT_SEC = 120


def _timeout_for(options: Dict[str, Any], timeout_s: Optional[float] = None) -> httpx.Timeout:
    """프로바이더별 응답 대기 시간(options.timeout_sec). read 에만 적용 — 연결·전송은 그대로 짧게.
    호출별 timeout_s(논문 채팅 ChatParams.timeout_s — 긴 작성 호출)가 있으면 그것이 우선한다."""
    if timeout_s:
        return httpx.Timeout(connect=10.0, read=float(timeout_s), write=10.0, pool=10.0)
    try:
        sec = int(options.get("timeout_sec") or DEFAULT_TIMEOUT_SEC)
    except (TypeError, ValueError):
        sec = DEFAULT_TIMEOUT_SEC
    sec = max(10, min(900, sec))
    return httpx.Timeout(connect=10.0, read=float(sec), write=10.0, pool=10.0)


def _map_http_error(status: int, body: str) -> LlmError:
    """업스트림 상태 코드를 정규화된 코드로. 본문은 앞부분만 메시지에 남긴다."""
    snippet = body.strip()[:300]
    if status in (401, 403):
        return LlmError("PROVIDER_AUTH", f"인증 실패 ({status}). API 키를 확인하세요. {snippet}")
    if status == 429:
        return LlmError("RATE_LIMITED", f"요청 한도 초과 (429). {snippet}")
    if status == 404:
        return LlmError("MODEL_NOT_FOUND", f"모델 또는 경로를 찾을 수 없음 (404). {snippet}")
    return LlmError("PROVIDER_ERROR", f"LLM 서버 오류 ({status}). {snippet}")


def _retry_after(headers: httpx.Headers) -> Optional[int]:
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _parse_tool_call_deltas(raw: Any) -> Optional[List[ToolCallDelta]]:
    if not isinstance(raw, list) or not raw:
        return None
    out: List[ToolCallDelta] = []
    for i, tc in enumerate(raw):
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        out.append(
            ToolCallDelta(
                index=int(tc.get("index", i)),
                id=tc.get("id") or None,
                name=fn.get("name") or None,
                arguments=fn.get("arguments") or "",
            )
        )
    return out or None


class _UnsupportedStreamOptions(Exception):
    """서버가 stream_options 를 모른다(400). 옵션 없이 재시도하라는 내부 신호."""

    def __init__(self, error: LlmError):
        super().__init__(error.message)
        self.error = error


class OpenAICompatAdapter:
    def __init__(self, config: ProviderConfig):
        self.config = config

    # ── 요청 구성 ──────────────────────────────────────────────────────────
    def _url(self) -> str:
        return self.config.base_url.rstrip("/") + "/chat/completions"

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        extra = self.config.options.get("extra_headers") or {}
        headers.update({str(k): str(v) for k, v in extra.items()})
        return headers

    def _body(
        self, messages: List[Dict[str, str]], *, stream: bool, max_tokens: Optional[int] = None, include_usage: bool = False
    ) -> Dict[str, Any]:
        opts = self.config.options
        body: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": stream,
            "temperature": float(opts.get("temperature", 0.3)),
            "max_tokens": int(max_tokens if max_tokens is not None else opts.get("max_tokens", 4096)),
        }
        if stream and include_usage:
            # 마지막 청크에 usage 를 실어 달라는 요청 (OpenAI·vLLM). 모르는 서버는 400 을 줄 수 있어
            # stream_chat 이 그 경우 옵션 없이 한 번 더 시도한다.
            body["stream_options"] = {"include_usage": True}
        return body

    def _body_from_params(self, params: ChatParams, *, stream: bool, include_usage: Optional[bool] = None) -> Dict[str, Any]:
        """논문 채팅용 본문. 준 항목만 싣는다 — 안 준 항목은 프로바이더 옵션 기본값.
        include_usage 를 주면 params.include_usage 대신 쓴다(stream() 의 폴백 재시도용)."""
        usage = params.include_usage if include_usage is None else include_usage
        body = self._body(params.messages, stream=stream, max_tokens=params.max_tokens, include_usage=bool(usage))
        if params.model:
            body["model"] = params.model
        if params.temperature is not None:
            body["temperature"] = float(params.temperature)
        if params.tools:
            body["tools"] = params.tools
            body["tool_choice"] = params.tool_choice or "auto"
        if params.reasoning_effort:
            body["reasoning_effort"] = params.reasoning_effort
        if params.response_format:
            body["response_format"] = params.response_format
        if params.extra_body:
            body.update(params.extra_body)
        return body

    # ── 스트리밍 ───────────────────────────────────────────────────────────
    async def stream(self, params: ChatParams) -> AsyncIterator[StreamDelta]:
        """도구 호출·추론 조각까지 싣는 스트림. 마지막에 finish_reason(+usage) 조각 하나.

        usage 옵션(stream_options.include_usage)을 거부하는 서버(400 + stream_options 언급)면 옵션 없이 다시 시도한다."""
        first_error: Optional[LlmError] = None
        for include_usage in ((True, False) if params.include_usage else (False,)):
            try:
                async for delta in self._stream_once(params, include_usage=include_usage):
                    yield delta
                return
            except _UnsupportedStreamOptions as e:
                first_error = e.error
                logger.info("stream_options.include_usage 를 거부하는 서버 — 옵션 없이 재시도: %s", e.error.message[:120])
                continue
        if first_error is not None:
            raise first_error

    async def _stream_once(self, params: ChatParams, *, include_usage: bool) -> AsyncIterator[StreamDelta]:
        url = self._url()
        try:
            async with httpx.AsyncClient(timeout=_timeout_for(self.config.options, params.timeout_s)) as client:
                async with client.stream(
                    "POST", url, json=self._body_from_params(params, stream=True, include_usage=include_usage), headers=self._headers()
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        if include_usage and response.status_code == 400 and "stream_options" in body:
                            raise _UnsupportedStreamOptions(_map_http_error(response.status_code, body))
                        err = _map_http_error(response.status_code, body)
                        err.retry_after = _retry_after(response.headers)
                        raise err

                    finish_reason: Optional[str] = None
                    usage: Optional[Dict[str, Any]] = None
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue  # 코멘트(: ping)·빈 줄·event: 줄은 무시
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            obj = json.loads(payload)
                        except json.JSONDecodeError:
                            logger.warning("LLM 스트림 JSON 파싱 실패: %s", payload[:120])
                            continue
                        if obj.get("usage"):
                            usage = obj["usage"]
                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                        tool_calls = _parse_tool_call_deltas(delta.get("tool_calls"))
                        if content or reasoning or tool_calls:
                            yield StreamDelta(content=content or None, reasoning=reasoning or None, tool_calls=tool_calls)
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                    yield StreamDelta(finish_reason=finish_reason or "stop", usage=usage)
        except LlmError:
            raise
        except httpx.TimeoutException as e:
            raise LlmError("PROVIDER_UNREACHABLE", f"LLM 서버 응답 시간 초과: {e.__class__.__name__}") from e
        except httpx.HTTPError as e:
            raise LlmError("PROVIDER_UNREACHABLE", f"LLM 서버에 연결할 수 없음: {e}") from e

    async def stream_chat(self, messages: List[Dict[str, str]]) -> AsyncIterator[StreamDelta]:
        """분석 채팅용: 본문 조각만 그대로 흘리고 마지막 종료 조각(usage 포함)을 낸다(기존 계약).
        요청 본문은 _body(messages, include_usage=True) 와 같다 — 거부하는 서버는 stream() 이 옵션 없이 재시도."""
        async for delta in self.stream(ChatParams(messages=messages, include_usage=True)):
            if delta.finish_reason is not None:
                yield StreamDelta(finish_reason=delta.finish_reason, usage=delta.usage)
            elif delta.content:
                yield StreamDelta(content=delta.content)

    async def complete(self, params: ChatParams) -> ChatResult:
        """비스트리밍 한 번 호출. 짧은 판정·분류·카드 JSON 용."""
        url = self._url()
        try:
            async with httpx.AsyncClient(timeout=_timeout_for(self.config.options, params.timeout_s)) as client:
                response = await client.post(url, json=self._body_from_params(params, stream=False), headers=self._headers())
            if response.status_code != 200:
                err = _map_http_error(response.status_code, response.text)
                err.retry_after = _retry_after(response.headers)
                raise err
            try:
                obj = response.json()
            except ValueError as e:
                raise LlmError("PROVIDER_ERROR", "LLM 응답이 JSON 이 아닙니다.") from e
        except LlmError:
            raise
        except httpx.TimeoutException as e:
            raise LlmError("PROVIDER_UNREACHABLE", f"LLM 서버 응답 시간 초과: {e.__class__.__name__}") from e
        except httpx.HTTPError as e:
            raise LlmError("PROVIDER_UNREACHABLE", f"LLM 서버에 연결할 수 없음: {e}") from e

        choices = obj.get("choices") or []
        msg = (choices[0].get("message") if choices else None) or {}
        acc: Dict[int, Dict[str, Any]] = {}
        deltas = _parse_tool_call_deltas(msg.get("tool_calls"))
        if deltas:
            merge_tool_call_deltas(acc, deltas)
        return ChatResult(
            content=msg.get("content") or "",
            reasoning=msg.get("reasoning_content") or msg.get("reasoning") or "",
            tool_calls=tool_calls_from_acc(acc),
            finish_reason=(choices[0].get("finish_reason") if choices else None),
            usage=obj.get("usage"),
        )

    # ── 연결 테스트 ────────────────────────────────────────────────────────
    async def test(self) -> TestResult:
        """max_tokens=1 짜리 비스트리밍 요청 한 번. /models 는 서버마다 지원이 달라 기준으로 쓰지 않는다."""
        messages = [{"role": "user", "content": "ping"}]
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(
                    self._url(),
                    json=self._body(messages, stream=False, max_tokens=1),
                    headers=self._headers(),
                )
            latency = int((time.perf_counter() - started) * 1000)
            if response.status_code != 200:
                err = _map_http_error(response.status_code, response.text)
                err.retry_after = _retry_after(response.headers)
                return TestResult(ok=False, latency_ms=latency, error=err)
            try:
                model = response.json().get("model") or self.config.model
            except ValueError:
                model = self.config.model
            return TestResult(ok=True, latency_ms=latency, model=model)
        except httpx.TimeoutException as e:
            return TestResult(ok=False, error=LlmError("PROVIDER_UNREACHABLE", f"응답 시간 초과: {e.__class__.__name__}"))
        except httpx.HTTPError as e:
            return TestResult(ok=False, error=LlmError("PROVIDER_UNREACHABLE", f"연결 실패: {e}"))
