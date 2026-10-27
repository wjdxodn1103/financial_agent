"""LLM 어댑터 공통 타입 — StatUpAI OP-BE `core/llm/base.py` 에서 그대로 옮겼다.

업스트림 오류는 LlmError 로 정규화해서 라우터·FE 가 코드로 분기하게 한다.
  - StreamDelta: 본문·추론 텍스트(reasoning)·도구 호출 조각(tool_calls), 마지막 조각에 finish_reason(+usage).
  - ChatParams / ChatResult: 도구 호출·reasoning_effort·응답 형식·호출별 타임아웃을 담는 요청/비스트리밍 응답 형태.
"""
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Protocol, Union

LlmErrorCode = Literal[
    "NO_PROVIDER",
    "PROVIDER_AUTH",
    "RATE_LIMITED",
    "MODEL_NOT_FOUND",
    "PROVIDER_UNREACHABLE",
    "PROVIDER_ERROR",
]


class LlmError(Exception):
    """정규화된 LLM 오류. http_status 는 스트림 시작 전에 HTTP 로 낼 때의 상태 코드."""

    def __init__(
        self,
        code: LlmErrorCode,
        message: str,
        *,
        http_status: int = 502,
        retry_after: Optional[int] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retry_after = retry_after

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.retry_after is not None:
            payload["retry_after"] = self.retry_after
        return payload


@dataclass
class ToolCallDelta:
    """스트림에 실려 오는 도구 호출 조각. 같은 index 의 arguments 를 호출자가 이어 붙인다(OpenAI 규격)."""
    index: int
    id: Optional[str] = None
    name: Optional[str] = None
    arguments: str = ""


@dataclass
class StreamDelta:
    """스트림 조각. content/reasoning/tool_calls 가 모두 None 이고 finish_reason 이 있으면 종료 신호."""
    content: Optional[str] = None
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    # 2026-09-18 추가 — 추론 모델의 delta.reasoning_content(또는 reasoning), 도구 호출 조각
    reasoning: Optional[str] = None
    tool_calls: Optional[List[ToolCallDelta]] = None


@dataclass
class ChatParams:
    """한 번의 chat/completions 호출 인자. 어댑터가 프로바이더 규격으로 옮긴다.

    - model: None 이면 ProviderConfig.model. 논문 작성 모델을 따로 둘 때 덮어쓴다.
    - timeout_s: 읽기 타임아웃(초). None 이면 어댑터 기본(120초). 느린 모델·긴 작성은 호출자가 올린다.
    - extra_body: 프로바이더 고유 필드(예: DeepSeek 의 chat_template_kwargs)를 그대로 합친다.
    """
    messages: List[Dict[str, Any]]
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    reasoning_effort: Optional[str] = None
    response_format: Optional[Dict[str, Any]] = None
    timeout_s: Optional[float] = None
    model: Optional[str] = None
    include_usage: bool = True
    extra_body: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResult:
    """비스트리밍 응답(또는 스트림을 끝까지 모은 것)."""
    content: str = ""
    reasoning: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)  # OpenAI message.tool_calls 형태
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None


@dataclass
class TestResult:
    ok: bool
    latency_ms: Optional[int] = None
    model: Optional[str] = None
    error: Optional[LlmError] = None


@dataclass
class ProviderConfig:
    base_url: str
    api_key: str
    model: str
    options: Dict[str, Any] = field(default_factory=dict)


class LlmAdapter(Protocol):
    async def stream_chat(
        self, messages: List[Dict[str, str]]
    ) -> AsyncIterator[StreamDelta]: ...

    def stream(self, params: ChatParams) -> AsyncIterator[StreamDelta]: ...

    async def complete(self, params: ChatParams) -> ChatResult: ...

    async def test(self) -> TestResult: ...


def merge_tool_call_deltas(acc: Dict[int, Dict[str, Any]], deltas: List[ToolCallDelta]) -> None:
    """스트림 조각을 index 별로 누적한다(호출자 공용). acc[index] = {"id","name","arguments"}."""
    for d in deltas:
        slot = acc.setdefault(d.index, {"id": None, "name": None, "arguments": ""})
        if d.id:
            slot["id"] = d.id
        if d.name:
            slot["name"] = (slot["name"] or "") + d.name  # 이름도 조각으로 올 수 있다(gpt-oss/NIM)
        if d.arguments:
            slot["arguments"] += d.arguments


def tool_calls_from_acc(acc: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """누적된 조각을 OpenAI assistant 메시지의 tool_calls 배열로."""
    out: List[Dict[str, Any]] = []
    for idx in sorted(acc):
        slot = acc[idx]
        if not slot.get("name"):
            continue
        out.append(
            {
                "id": slot.get("id") or f"call_{idx}",
                "type": "function",
                "function": {"name": slot["name"], "arguments": slot.get("arguments") or "{}"},
            }
        )
    return out
