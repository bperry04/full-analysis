from __future__ import annotations


class FAError(Exception):
    """Base class."""


class ProviderError(FAError):
    def __init__(self, provider: str, msg: str):
        self.provider = provider
        super().__init__(f"{provider}: {msg}")


class RateLimited(ProviderError):
    pass


class NoData(ProviderError):
    """Provider answered but had nothing for this request (not an outage)."""


class Invalid(ProviderError):
    """Provider answered but the payload failed validation."""


class ConditionNotMet(FAError):
    """A route binding's `when` condition is false (e.g. IB Gateway not connected)."""


class AllRoutesFailed(FAError):
    def __init__(self, need: str, attempts: list):
        self.need = need
        self.attempts = attempts
        detail = "; ".join(f"{a.provider}={a.result}({a.reason})" for a in attempts) or "no providers"
        super().__init__(f"all routes failed for {need}: {detail}")


class RealtimeRequired(FAError):
    """Raised when require_realtime is set and only delayed data was available."""
