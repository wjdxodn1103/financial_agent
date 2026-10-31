"""양식 2.0 시험 — 문서 만들기 / 대화 한 턴(SSE)을 보내고 이벤트를 요약해 찍는다.

python -I demo/kirs/chat_turn.py new <양식 id> <제목>
python -I demo/kirs/chat_turn.py say <문서 id> "<말>"
"""
from __future__ import annotations

import json
import sys
import time

import httpx

B = "http://localhost:8200/api"
H = {"X-User-Id": "u_kim"}
W = "wmvu5ufki6238"
sys.stdout.reconfigure(encoding="utf-8")


def new(type_id: str, title: str) -> None:
    r = httpx.post(f"{B}/workspaces/{W}/reports", headers=H, json={"title": title, "reportType": type_id}, timeout=60)
    j = r.json()
    sess = j.get("session") or j
    print(r.status_code, sess.get("id"))
    for s in sess.get("sections") or []:
        print(f"  [{s['step']}] {s.get('part')} · {s.get('role')} · {s['title']} · blocks {s.get('blocks')}")


def say(sid: str, text: str) -> None:
    t0 = time.time()
    out, tools = [], []
    with httpx.stream("POST", f"{B}/sessions/{sid}/chat", headers=H, json={"text": text, "modes": {"research": False, "writing": True}}, timeout=1800) as r:
        if r.status_code != 200:
            print(r.status_code, r.read().decode("utf-8", "replace"))
            return
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:])
            except ValueError:
                continue
            t = ev.get("type")
            if t == "text":
                out.append(ev.get("delta") or "")
            elif t == "text_replace":
                out = [ev.get("text") or ""]
            elif t == "tool_start":
                tools.append(f"{ev.get('name')} {json.dumps(ev.get('args') or {}, ensure_ascii=False)[:300]}")
            elif t in ("section_update", "outline_update", "plan_update", "error", "done"):
                print(f"  · {t}: {json.dumps({k: v for k, v in ev.items() if k not in ('type', 'sections', 'content')}, ensure_ascii=False)[:240]}")
    print(f"--- {round(time.time() - t0)}s · 도구: ")
    for x in tools:
        print("   ", x)
    print("--- 답:\n" + "".join(out))


if __name__ == "__main__":
    if sys.argv[1] == "new":
        new(sys.argv[2], sys.argv[3])
    else:
        say(sys.argv[2], sys.argv[3])
