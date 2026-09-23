"""Immutable raw-payload archive: every fetched payload is gzipped to C:\\fadata\\raw with its sha256.

This is the audit trail behind every provenance record — you can always open the exact bytes we used.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fa.core.settings import get_settings


def write_raw(provider: str, name: str, payload: bytes | str | dict | list) -> tuple[str, str]:
    """Returns (relative_path, sha256)."""
    if isinstance(payload, (dict, list)):
        data = json.dumps(payload, separators=(",", ":"), default=str).encode()
        ext = ".json"
    elif isinstance(payload, str):
        data = payload.encode("utf-8", "replace")
        ext = ".txt"
    else:
        data = payload
        ext = ".bin"
    sha = hashlib.sha256(data).hexdigest()
    now = datetime.now(timezone.utc)
    rel = Path(provider) / f"dt={now:%Y-%m-%d}" / f"{name}_{now:%H%M%S}_{sha[:8]}{ext}.gz"
    path = get_settings().raw_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with gzip.open(path, "wb", compresslevel=6) as f:
            f.write(data)
    return str(rel).replace("\\", "/"), sha


def read_raw(rel_path: str) -> bytes:
    with gzip.open(get_settings().raw_dir / rel_path, "rb") as f:
        return f.read()


def read_raw_json(rel_path: str) -> Any:
    return json.loads(read_raw(rel_path))
