"""모델 호출 층 — OP `paper/agent/llm.py::PaperLlm` 의 축소판.

프로바이더는 NVIDIA build(.env 의 키·base_url), OPENROUTER_API_KEY 가 있으면 실패할 때만 쓰는 예비 경로 OpenRouter. 역할은 둘:
  - chat:   대화·도구 선택(에이전트 루프)
  - writer: 리포트 섹션 작성(작성 중 자료 검색 도구 루프)
같은 모델을 써도 되고(.env 기본), 나눠도 된다. 생각(추론) 길이는 호출마다 reasoning_effort("none"·"low"·"medium")로 고른다.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import time
import traceback
from typing import Any, AsyncIterator, Dict, List, Optional

from app import config
from app import usage as usage_ctx
from app.llm.base import ChatParams, ChatResult, LlmError, ProviderConfig, StreamDelta, merge_tool_call_deltas, tool_calls_from_acc
from app.llm.openai_compat import OpenAICompatAdapter
from app.llm.retry import stream_with_retry, with_retry

logger = logging.getLogger(__name__)

# 첫 토큰이 늦는 모델의 읽기 제한 시간(초) — NIM 대기열(OP 실측: kimi·gemma 200초대)
SLOW_MODEL_TIMEOUT: Dict[str, float] = {
    "moonshotai/kimi-k3": 480,
    "google/gemma-4-31b-it": 480,
    "z-ai/glm-5.3": 480,
}
DEFAULT_TIMEOUT = 180.0


# 호출마다 토큰 사용량 한 줄(모델·부른 곳·입력/출력/추론 토큰·걸린 시간) — 모델별 비용 견적·테스트 중 비용 추적용. 키·본문은 남기지 않는다
USAGE_LOG = config.DATA_DIR / "logs" / "llm_usage.jsonl"


def _caller() -> str:
    """app/llm 밖에서 이 호출을 부른 첫 함수(파일:함수)."""
    for fr in reversed(traceback.extract_stack()[:-3]):
        f = fr.filename.replace("\\", "/")
        if "/app/" in f and "/app/llm/" not in f:
            return f"{f.split('/app/')[-1]}:{fr.name}"
    return ""


def _log_usage(role: str, params: ChatParams, usage: Optional[Dict[str, Any]], started: float, content_chars: int, reasoning_chars: int, via: str = "nvidia") -> None:
    try:
        u = usage or {}
        ctx = usage_ctx.current()
        usage_ctx.count_call()  # 실행(루틴·수집) 상한
        row = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "user": ctx.get("user"),
            "ws": ctx.get("ws"),
            "feature": ctx.get("feature"),
            "run": ctx.get("run"),
            "role": role,
            "via": via,
            "model": params.model,
            "effort": params.reasoning_effort or ((params.extra_body.get("reasoning") or {}).get("effort")) or ((params.extra_body.get("chat_template_kwargs") or {}).get("reasoning_budget")),
            "caller": _caller(),
            "tools": len(params.tools or []),
            "messages": len(params.messages or []),
            "prompt": u.get("prompt_tokens"),
            "completion": u.get("completion_tokens"),
            "reasoning": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            "contentChars": content_chars,
            "reasoningChars": reasoning_chars,
            "sec": round(time.monotonic() - started, 2),
        }
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(USAGE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — 기록 실패가 호출을 막지 않게
        pass


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


# 생각(추론) 단계 — 호출마다 ChatParams.reasoning_effort 로 고른다: "none"(끔) · "low"(짧게) · "medium" · None(모델 기본)
# NVIDIA Nemotron: "none" 은 reasoning_effort 그대로 받고, "low" 만으로는 거의 줄지 않아(2026-10-29 실측 206 → 185 토큰)
# low·medium 은 chat_template_kwargs.reasoning_budget(추론 토큰 상한)으로 보낸다. OpenRouter 는 reasoning.effort 하나로 받는다.
NEMOTRON_BUDGET = {"low": 1024, "medium": 4096}


def _openrouter_provider() -> Dict[str, Any]:
    """OpenRouter 호스트 고르기(.env) — 순서·양자화 제한·데이터 수집 거부."""
    prov: Dict[str, Any] = {}
    if config.OPENROUTER_PROVIDERS:
        prov["order"] = config.OPENROUTER_PROVIDERS
    if config.OPENROUTER_QUANTIZATIONS:
        prov["quantizations"] = config.OPENROUTER_QUANTIZATIONS
    if config.OPENROUTER_DATA_COLLECTION in ("allow", "deny"):
        prov["data_collection"] = config.OPENROUTER_DATA_COLLECTION
    return prov


class ReportLlm:
    """한 턴 동안 쓰는 호출기 — 역할별 모델. 기본은 NVIDIA build, OPENROUTER_API_KEY 가 있으면
    NVIDIA 호출이 (재시도 뒤에도) 실패할 때 같은 모델을 OpenRouter 로 한 번 더 부른다(예비 경로). 스트림은 아직 아무것도 받지 않았을 때만 넘어간다."""

    def __init__(self, chat_model: Optional[str] = None, writer_model: Optional[str] = None):
        require_provider()
        self.chat_model = chat_model or config.CHAT_MODEL
        self.writer_model = writer_model or config.WRITER_MODEL
        self._adapter = OpenAICompatAdapter(ProviderConfig(base_url=config.NVIDIA_BASE_URL, api_key=config.NVIDIA_API_KEY, model=self.chat_model, options={}))
        self._fallback = (
            OpenAICompatAdapter(ProviderConfig(base_url=config.OPENROUTER_BASE_URL, api_key=config.OPENROUTER_API_KEY, model=config.FALLBACK_CHAT_MODEL, options={}))
            if config.OPENROUTER_API_KEY
            else None
        )

    def model_for(self, role: str) -> str:
        return self.writer_model if role == "writer" else self.chat_model

    @staticmethod
    def _fallback_model(role: str) -> str:
        return config.FALLBACK_WRITER_MODEL if role == "writer" else config.FALLBACK_CHAT_MODEL

    def _params(self, model: str, params: ChatParams, via: str = "nvidia") -> ChatParams:
        """호출자의 params 는 그대로 두고(예비 경로가 다시 쓴다) 이 경로에 맞춘 사본을 만든다."""
        p = dataclasses.replace(params, model=model, extra_body=dict(params.extra_body))
        if p.timeout_s is None:
            p.timeout_s = SLOW_MODEL_TIMEOUT.get(model, DEFAULT_TIMEOUT)
        effort = p.reasoning_effort
        if via == "openrouter":
            p.reasoning_effort = None
            if effort:
                p.extra_body["reasoning"] = {"effort": effort}
            prov = _openrouter_provider()
            if prov:
                p.extra_body["provider"] = prov
            return p
        if re.search(r"deepseek", model, re.I) and effort:
            # DeepSeek(NIM) 은 chat_template_kwargs {thinking, reasoning_effort} 로 받는다
            kwargs = {"thinking": False} if effort == "none" else {"thinking": True, "reasoning_effort": "low" if effort == "medium" else effort}
            p.extra_body["chat_template_kwargs"] = kwargs
            p.reasoning_effort = None
        elif re.search(r"nemotron", model, re.I) and effort in NEMOTRON_BUDGET:
            p.extra_body["chat_template_kwargs"] = {**(p.extra_body.get("chat_template_kwargs") or {}), "reasoning_budget": NEMOTRON_BUDGET[effort]}
            p.reasoning_effort = None
        return p

    async def stream(self, role: str, params: ChatParams) -> AsyncIterator[StreamDelta]:
        p = self._params(self.model_for(role), params)
        started, cc, rc, usage, used, got = time.monotonic(), 0, 0, None, p, False
        try:
            try:
                async for d in stream_with_retry(lambda: self._adapter.stream(p)):
                    got = True
                    cc += len(d.content or "")
                    rc += len(d.reasoning or "")
                    usage = d.usage or usage
                    yield d
            except Exception as e:  # noqa: BLE001 — 아무것도 받기 전에 실패했을 때만 예비 경로로
                if self._fallback is None or got:
                    raise
                used = self._params(self._fallback_model(role), params, via="openrouter")
                logger.warning("NVIDIA 호출 실패 → OpenRouter 예비 경로(%s): %s", used.model, str(e)[:200])
                async for d in stream_with_retry(lambda: self._fallback.stream(used)):
                    cc += len(d.content or "")
                    rc += len(d.reasoning or "")
                    usage = d.usage or usage
                    yield d
        finally:
            _log_usage(role, used, usage, started, cc, rc, via="openrouter" if used is not p else "nvidia")

    async def complete(self, role: str, params: ChatParams) -> ChatResult:
        p = self._params(self.model_for(role), params)
        started, used = time.monotonic(), p
        try:
            res = await with_retry(lambda: self._adapter.complete(p))
        except Exception as e:  # noqa: BLE001
            if self._fallback is None:
                raise
            used = self._params(self._fallback_model(role), params, via="openrouter")
            logger.warning("NVIDIA 호출 실패 → OpenRouter 예비 경로(%s): %s", used.model, str(e)[:200])
            res = await with_retry(lambda: self._fallback.complete(used))
        _log_usage(role, used, res.usage, started, len(res.content or ""), len(res.reasoning or ""), via="openrouter" if used is not p else "nvidia")
        return res

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
