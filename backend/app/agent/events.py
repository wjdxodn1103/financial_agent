"""SSE 이벤트 계약 — OP paper/agent/events.py 그대로(서버 → 화면).

이벤트는 `{"type": ..., ...}` dict 그대로 보낸다. 타입:
meta / thinking / text / text_replace / tool_start / tool_end / section_update / outline_update /
approval / plan_update / suggestions / setup_update / status / error / done
"""
from typing import Any, Callable, Dict

Event = Dict[str, Any]
Emit = Callable[[Event], None]


def ev(type_: str, **fields: Any) -> Event:
    """None 값은 뺀다(TS 의 undefined 필드는 JSON 에 나가지 않는다)."""
    out: Event = {"type": type_}
    for k, v in fields.items():
        if v is not None:
            out[k] = v
    return out
