"""짧은 id — OP `paper/jsx.py::id36` 와 같은 꼴: 접두어 + base36(ms) + 난수."""
from __future__ import annotations

import random
import time

_ALPHA = "0123456789abcdefghijklmnopqrstuvwxyz"


def _b36(n: int) -> str:
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = _ALPHA[r] + out
        if n == 0:
            return out


def id36(prefix: str, rand_len: int = 4) -> str:
    return prefix + _b36(int(time.time() * 1000)) + "".join(random.choice(_ALPHA) for _ in range(rand_len))


def now_iso() -> str:
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{int((t % 1) * 1000):03d}Z"
