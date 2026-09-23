"""Shared async HTTP client with retry/backoff and per-provider rate limiting."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from fa.core.errors import NoData, ProviderError, RateLimited
from fa.core.ratelimit import bucket
from fa.core.settings import get_settings

log = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36"
)


def client() -> httpx.AsyncClient:
    """One client per event loop (the scheduler thread and the API loop each get their own)."""
    global _client, _client_loop
    loop = asyncio.get_event_loop()
    if _client is None or _client_loop is not loop or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(get_settings().http_timeout_s, connect=10.0),
            follow_redirects=True,
            http2=True,
            headers={"User-Agent": BROWSER_UA, "Accept": "*/*"},
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        )
        _client_loop = loop
    return _client


async def get(
    provider: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 3,
    timeout: float | None = None,
) -> httpx.Response:
    await bucket(provider).acquire()
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = await client().get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 429:
                raise RateLimited(provider, f"429 from {url}")
            if r.status_code == 404:
                raise NoData(provider, f"404 {url}")
            if r.status_code >= 500:
                raise ProviderError(provider, f"{r.status_code} {url}")
            if r.status_code >= 400:
                raise ProviderError(provider, f"{r.status_code} {url}")
            return r
        except (NoData,):
            raise
        except (RateLimited, ProviderError, httpx.HTTPError) as e:
            last = e
            if attempt < retries - 1:
                await asyncio.sleep(0.6 * (2**attempt))
    raise ProviderError(provider, f"failed after {retries} attempts: {last}")


async def get_json(provider: str, url: str, **kw: Any) -> Any:
    r = await get(provider, url, **kw)
    try:
        return r.json()
    except Exception as e:
        raise ProviderError(provider, f"bad JSON from {url}: {e}") from e


async def get_text(provider: str, url: str, **kw: Any) -> str:
    r = await get(provider, url, **kw)
    return r.text


async def get_bytes(provider: str, url: str, **kw: Any) -> bytes:
    r = await get(provider, url, **kw)
    return r.content
