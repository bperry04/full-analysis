"""Circuit breaker per (provider, need): after N consecutive failures, skip for a cooldown."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class _State:
    failures: int = 0
    opened_at: float | None = None
    ok: int = 0
    fail: int = 0
    last_error: str = ""
    durations: list[int] = field(default_factory=list)


class CircuitBreaker:
    def __init__(self, threshold: int = 3, cooldown_s: float = 300.0):
        self.threshold = threshold
        self.cooldown = cooldown_s
        self._s: dict[tuple[str, str], _State] = {}

    def _get(self, provider: str, need: str) -> _State:
        return self._s.setdefault((provider, need), _State())

    def is_open(self, provider: str, need: str) -> bool:
        st = self._get(provider, need)
        if st.opened_at is None:
            return False
        if time.monotonic() - st.opened_at > self.cooldown:
            st.opened_at = None      # half-open: allow one try
            st.failures = 0
            return False
        return True

    def record_success(self, provider: str, need: str, duration_ms: int) -> None:
        st = self._get(provider, need)
        st.failures = 0
        st.opened_at = None
        st.ok += 1
        st.durations.append(duration_ms)
        st.durations = st.durations[-200:]

    def record_failure(self, provider: str, need: str, error: str) -> None:
        st = self._get(provider, need)
        st.failures += 1
        st.fail += 1
        st.last_error = error[:300]
        if st.failures >= self.threshold:
            st.opened_at = time.monotonic()

    def reset(self, provider: str) -> None:
        for (p, _), st in self._s.items():
            if p == provider:
                st.failures = 0
                st.opened_at = None

    def snapshot(self) -> list[dict]:
        out = []
        for (p, n), st in sorted(self._s.items()):
            d = sorted(st.durations)
            p50 = d[len(d) // 2] if d else None
            p95 = d[int(len(d) * 0.95)] if d else None
            out.append(
                {
                    "provider": p, "need": n, "ok": st.ok, "fail": st.fail,
                    "circuit": "open" if self.is_open(p, n) else "closed",
                    "p50_ms": p50, "p95_ms": p95, "last_error": st.last_error,
                }
            )
        return out
