"""모델 호출 층 — OP `paper/agent/llm.py::PaperLlm` 의 축소판.

프로바이더는 NVIDIA build 하나(.env 의 키·base_url). 역할은 둘:
  - chat:   대화·도구 선택(에이전트 루프)
  - writer: 리포트 섹션 작성(작성 중 자료 검색 도구 루프)
같은 모델을 써도 되고(.env 기본), 나눠도 된다.
"""
from __future__ import annotations

import re
from typing import Any, AsyncIterator, Dict, List, Optional

from app import config
from app.llm.base import ChatParams, ChatResult, LlmError, ProviderConfig, StreamDelta, merge_tool_call_deltas, tool_calls_from_acc
from app.llm.openai_compat import OpenAICompatAdapter
from app.llm.retry import stream_with_retry, with_retry

# 첫 토큰이 늦는 모델의 읽기 제한 시간(초) — NIM 대기열(OP 실측: kimi·gemma 200초대)
SLOW_MODEL_TIMEOUT: Dict[str, float] = {
    "moonshotai/kimi-k3": 480,
    "google/gemma-4-31b-it": 480,
    "z-ai/glm-5.3": 480,
}
DEFAULT_TIMEOUT = 180.0


def provider_ready() -> bool:
    return bool(config.NVIDIA_API_KEY)


def provider_info() -> Dict[str, Any]:
    """FE 상단 바 배지 — 키 값은 내보내지 않는다."""
    if not provider_ready():
        return {"kind": "none", "model": "", "writer": "", "embed": ""}
    return {"kind": "nvidia", "model": config.CHAT_MODEL, "writer": config.WRITER_MODEL, "embed": config.EMBED_MODEL}


def require_provider() -> None:
    if not provider_ready():
        raise LlmError("NO_PROVIDER", "NVIDIA_API_KEY 가 설정되지 않았습니다. backend/.env 를 확인하세요.", http_status=409)


class ReportLlm:
    """한 턴 동안 쓰는 호출기 — 프로바이더 하나, 역할별 모델."""

    def __init__(self, chat_model: Optional[str] = None, writer_model: Optional[str] = None):
        require_provider()
        self.chat_model = chat_model or config.CHAT_MODEL
        self.writer_model = writer_model or config.WRITER_MODEL
        self._adapter = OpenAICompatAdapter(ProviderConfig(base_url=config.NVIDIA_BASE_URL, api_key=config.NVIDIA_API_KEY, model=self.chat_model, options={}))

    def model_for(self, role: str) -> str:
        return self.writer_model if role == "writer" else self.chat_model

    def _params(self, model: str, params: ChatParams) -> ChatParams:
        params.model = model
        if params.timeout_s is None:
            params.timeout_s = SLOW_MODEL_TIMEOUT.get(model, DEFAULT_TIMEOUT)
        if re.search(r"deepseek", model, re.I) and params.reasoning_effort:
            # DeepSeek(NIM) 은 chat_template_kwargs {thinking, reasoning_effort} 로 받는다
            effort = "low" if params.reasoning_effort == "medium" else params.reasoning_effort
            params.extra_body = {**params.extra_body, "chat_template_kwargs": {"thinking": True, "reasoning_effort": effort}}
            params.reasoning_effort = None
        return params

    async def stream(self, role: str, params: ChatParams) -> AsyncIterator[StreamDelta]:
        p = self._params(self.model_for(role), params)
        async for d in stream_with_retry(lambda: self._adapter.stream(p)):
            yield d

    async def complete(self, role: str, params: ChatParams) -> ChatResult:
        p = self._params(self.model_for(role), params)
        return await with_retry(lambda: self._adapter.complete(p))

    async def collect(self, role: str, params: ChatParams) -> ChatResult:
        """스트림을 끝까지 모아 ChatResult 로(도구 호출 조각 누적 포함). NIM 게이트웨이는 비스트리밍 응답을 300초에 끊으므로 긴 작성은 이것으로."""
        acc: Dict[int, Dict[str, Any]] = {}
        content: List[str] = []
        reasoning: List[str] = []
        finish, usage = None, None
        async for d in self.stream(role, params):
            if d.content:
                content.append(d.content)
            if d.reasoning:
                reasoning.append(d.reasoning)
            if d.tool_calls:
                merge_tool_call_deltas(acc, d.tool_calls)
            if d.finish_reason is not None:
                finish, usage = d.finish_reason, d.usage
        return ChatResult(content="".join(content), reasoning="".join(reasoning), tool_calls=tool_calls_from_acc(acc), finish_reason=finish, usage=usage)
