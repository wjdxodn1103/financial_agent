"""'삼성전자 기업분석' 문서 — 사내 양식으로 문서를 만들고 대화로 몇 섹션만 쓴다(쓰는 장면 캡처용, 전체를 다 쓰지 않는다).
python -I demo/semi/write_samsung.py new            문서 만들기 + 대상·자료 범위 → state.json 에 id
python -I demo/semi/write_samsung.py say "<말>"     대화 한 턴(SSE)"""
import json
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
B = "http://127.0.0.1:8200/api"
H = {"X-User-Id": "u_kim"}
STATE = Path(__file__).with_name("state.json")
st = json.loads(STATE.read_text(encoding="utf-8"))
W = st["workspace"]


def new() -> None:
    r = httpx.post(f"{B}/workspaces/{W}/reports", headers=H, json={"title": "삼성전자 기업분석", "reportType": st["format"]}, timeout=120)
    j = r.json()
    sess = j.get("session") or j
    print(r.status_code, sess.get("id"))
    sid = sess["id"]
    for body in ({"setup": {"subject": "삼성전자"}}, {"dataScope": {"groups": {"workspace": True, "company": False, "personal": False}}}):
        p = httpx.patch(f"{B}/sessions/{sid}", headers=H, json=body, timeout=120)
        print("  patch", list(body), p.status_code, p.text[:120] if p.status_code != 200 else "")
    for s in (httpx.get(f"{B}/sessions/{sid}", headers=H, timeout=120).json().get("session") or {}).get("sections") or []:
        print(f"  [{s['step']}] {s.get('part')} · {s.get('role')} · {s['title']} · blocks {s.get('blocks')}")
    st["report"] = sid
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def say(text: str) -> None:
    sid = st["report"]
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
                tools.append(f"{ev.get('name')} {json.dumps(ev.get('args') or {}, ensure_ascii=False)[:200]}")
            elif t in ("outline_update", "plan_update", "error", "done"):
                print(f"  · {t}: {json.dumps({k: v for k, v in ev.items() if k not in ('type', 'sections', 'content')}, ensure_ascii=False)[:240]}")
    print(f"--- {round(time.time() - t0)}s · 도구 {len(tools)}:")
    for x in tools:
        print("   ", x)
    print("--- 답:\n" + "".join(out))


if __name__ == "__main__":
    if sys.argv[1] == "new":
        new()
    else:
        say(sys.argv[2])
