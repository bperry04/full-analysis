"""The context object factors read from: every section's output, plus small accessors."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Ctx:
    symbol: str
    sections: dict[str, Any] = field(default_factory=dict)      # section name -> payload dict (jsonable-ish, may hold DataFrames)
    prov: dict[str, str] = field(default_factory=dict)          # section name -> primary prov_id
    objects: dict[str, Any] = field(default_factory=dict)       # rich objects (Fundamentals, metrics dict, DataFrames) by name

    def s(self, name: str, *path: str, default: Any = None) -> Any:
        cur: Any = self.sections.get(name)
        for p in path:
            if cur is None:
                return default
            if isinstance(cur, dict):
                cur = cur.get(p)
            else:
                cur = getattr(cur, p, None)
        return default if cur is None else cur

    def p(self, name: str) -> str | None:
        return self.prov.get(name)

    def metric(self, key: str):
        m = self.objects.get("metrics") or {}
        return m.get(key)

    def mval(self, key: str) -> float | None:
        m = self.metric(key)
        return None if m is None else m.value

    def mhist(self, key: str) -> list[float]:
        m = self.metric(key)
        return list((m.history or {}).values()) if m is not None else []
