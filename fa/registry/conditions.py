"""Tiny predicate language for route bindings: `ibkr_connected`, `has_key:fred`, `market_open`, `not X`, `A and B`."""
from __future__ import annotations

from fa.core.clock import market_open
from fa.core.settings import get_settings


def _atom(name: str, ctx: dict) -> bool:
    name = name.strip()
    if name.startswith("not "):
        return not _atom(name[4:], ctx)
    if name == "market_open":
        return market_open()
    if name == "ibkr_connected":
        return bool(ctx.get("ibkr_connected", False))
    if name == "schwab_authed":
        return bool(ctx.get("schwab_authed", False))
    if name.startswith("has_key:"):
        key = name.split(":", 1)[1]
        s = get_settings()
        return bool(getattr(s, f"{key}_api_key", "") or getattr(s, f"{key}_client_id", ""))
    if name == "true":
        return True
    if name == "false":
        return False
    return bool(ctx.get(name, False))


def evaluate(expr: str | None, ctx: dict) -> bool:
    if not expr:
        return True
    return all(_atom(part, ctx) for part in expr.split(" and "))
