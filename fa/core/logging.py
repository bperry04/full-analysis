from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from fa.core.settings import get_settings

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    _configured = True
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    try:
        fh = RotatingFileHandler(get_settings().logs_dir / "fa.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        pass
    for noisy in ("httpx", "httpcore", "yfinance", "peewee", "urllib3", "ib_async", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # IB reports "market data not subscribed" (354) as an ERROR per contract; we handle it by switching to delayed data
    logging.getLogger("ib_async.wrapper").setLevel(logging.CRITICAL)
