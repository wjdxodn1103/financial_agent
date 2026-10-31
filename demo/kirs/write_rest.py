"""양식 2.0 시험 — 남은 장의 목차를 대화로 정하고(한 턴) 안 쓴 소주제를 차례로, 요약은 맨 끝에 쓴다(섹션마다 한 턴).

python -I demo/kirs/write_rest.py <문서 id> [--no-outline]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from sqlmodel import Session  # noqa: E402

from app.db import ReportSession, engine  # noqa: E402

PY = sys.executable


def say(sid: str, text: str) -> None:
    print(f"##### {text}", flush=True)
    out = subprocess.run([PY, "-I", str(HERE / "chat_turn.py"), "say", sid, text], capture_output=True, text=True, encoding="utf-8", timeout=1800)
    print("\n".join(l for l in out.stdout.splitlines() if not l.startswith("  · section_update")), flush=True)


def todo(sid: str) -> list:
    with Session(engine) as s:
        secs = s.get(ReportSession, sid).doc.get("sections") or []
    rest = [x for x in secs if x.get("status") != "written"]
    return [x["title"] for x in rest if x.get("role") != "summary"] + [x["title"] for x in rest if x.get("role") == "summary"]


def main(sid: str, outline: bool = True) -> None:
    if outline:
        say(sid, "산업현황부터 리스크요인까지 장마다 소제목을 자료를 보고 주장 한 줄로 정해서 바로 반영해 줘. 자료가 없는 자리는 지금 이름 그대로 둬.")
    for title in todo(sid):
        say(sid, f"'{title}' 섹션 써 줘.")
    print("DONE", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], "--no-outline" not in sys.argv)
