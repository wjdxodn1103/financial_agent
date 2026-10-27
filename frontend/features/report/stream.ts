/**
 * 채팅 한 턴 스트리밍 — POST /api/sessions/{id}/chat (SSE). OP-FE paperStream.ts + features/chat/services/sse.ts 를 합쳤다.
 * 스트림 시작 전 오류는 HTTP JSON `{code, message}` → onError. 그 뒤는 전부 StreamEvent 로 onEvent.
 * `: ping` 코멘트는 버린다. done 없이 끊기면 error+done 을 합성한다.
 * 한글은 멀티바이트라 TextDecoder 를 stream:true 로 쓴다(청크 경계에서 글자가 잘리지 않게).
 */
import { authHeaders } from "../workspace/auth";
import { API_BASE } from "./constants";
import type { ChatTurnBody, StreamError, StreamEvent } from "./types";

export interface StreamHandlers {
  onEvent: (e: StreamEvent) => void;
  onError: (error: StreamError) => void;
  onAbort?: () => void;
}

async function readSse(res: Response, onBlock: (event: string, data: string) => void): Promise<void> {
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  const flush = (block: string) => {
    let event = "message";
    const data: string[] = [];
    for (const raw of block.split("\n")) {
      const line = raw.replace(/\r$/, "");
      if (!line || line.startsWith(":")) continue;
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (data.length) onBlock(event, data.join("\n"));
  };
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      flush(buffer.slice(0, idx));
      buffer = buffer.slice(idx + 2);
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) flush(buffer);
}

export async function streamChat(sessionId: string, body: ChatTurnBody, handlers: StreamHandlers, signal?: AbortSignal): Promise<void> {
  return streamPost<StreamEvent>(`/api/sessions/${encodeURIComponent(sessionId)}/chat`, body, handlers, signal);
}

/** 같은 SSE 규칙의 다른 채팅(AI 채팅 — /api/research/chats/{id}/chat). 이벤트 모양은 호출자가 정한다 */
export async function streamPost<E extends { type: string }>(path: string, body: unknown, handlers: { onEvent: (e: E) => void; onError: (error: StreamError) => void; onAbort?: () => void }, signal?: AbortSignal): Promise<void> {
  const { onError, onAbort } = handlers;
  const onEvent = handlers.onEvent as (e: unknown) => void;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if ((e as DOMException)?.name === "AbortError") return onAbort?.();
    return onError({ code: "PROVIDER_UNREACHABLE", message: `백엔드에 연결할 수 없습니다(${API_BASE}).` });
  }
  if (!res.ok) {
    let err: StreamError = { message: `HTTP ${res.status}` };
    try {
      const j = await res.json();
      err = { code: j.code, message: j.message ?? j.detail ?? err.message };
    } catch {
      /* 본문 없음 */
    }
    return onError(err);
  }
  let finished = false;
  try {
    await readSse(res, (event, data) => {
      let payload: Record<string, unknown> | null = null;
      try {
        payload = JSON.parse(data);
      } catch {
        return;
      }
      if (!payload || typeof payload !== "object") return;
      const ev = (payload.type ? payload : { ...payload, type: event }) as { type: string };
      if (ev.type === "done") finished = true;
      onEvent(ev);
    });
    if (!finished) {
      onEvent({ type: "error", code: "PROVIDER_UNREACHABLE", message: "응답이 중간에 끊겼습니다." });
      onEvent({ type: "done" });
    }
  } catch (e) {
    if ((e as DOMException)?.name === "AbortError") return onAbort?.();
    if (!finished) {
      onEvent({ type: "error", code: "PROVIDER_UNREACHABLE", message: String(e) });
      onEvent({ type: "done" });
    }
  }
}
