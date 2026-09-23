"""In-process progress bus: the orchestrator publishes section events, SSE subscribers consume them."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any


class Progress:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._subs: list[asyncio.Queue] = []
        self.done = False

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        for e in self.events:            # replay for late subscribers
            q.put_nowait(e)
        if self.done:
            q.put_nowait({"event": "run.done", "replay": True})
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subs:
            self._subs.remove(q)

    def emit(self, event: str, **data: Any) -> None:
        e = {"event": event, "ts": datetime.now(timezone.utc).isoformat(), **data}
        self.events.append(e)
        for q in list(self._subs):
            q.put_nowait(e)
        if event in ("run.done", "run.error"):
            self.done = True
