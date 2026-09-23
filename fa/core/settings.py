"""Central settings. Every filesystem path in the system derives from here — no literals elsewhere.

Values come from environment variables prefixed FA_ (or a .env file in the project root).
The data root defaults to C:\\fadata and must live OUTSIDE OneDrive.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FA_", env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    data_root: Path = Field(default=Path(r"C:\fadata"))

    # Identity / keys (all free)
    sec_user_agent: str = "FullAnalysis research contact@example.com"
    fred_api_key: str = ""
    finnhub_api_key: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "fa-analyzer/0.1"

    # IBKR
    ib_host: str = "127.0.0.1"
    ib_port: int = 4001
    ib_client_id: int = 17
    ib_connect_timeout_s: float = 4.0

    # Schwab
    schwab_app_key: str = ""
    schwab_app_secret: str = ""
    schwab_callback_url: str = "https://127.0.0.1:8182"

    # API
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    web_origin: str = "http://localhost:5173"

    # Behaviour
    require_realtime: bool = False        # fail loudly instead of degrading to delayed data
    store_strict: bool = True             # API refuses to start if another process owns the DuckDB file (set 0 for a second, read-only-ish instance)
    auto_watch: bool = True               # every analysed ticker joins the watchlist so its chain/IV/bars history accrues daily
    http_timeout_s: float = 30.0
    default_depth: str = "standard"       # quick | standard | deep

    # ---- derived paths ----
    @property
    def lake_dir(self) -> Path:
        return self.data_root / "lake"

    @property
    def raw_dir(self) -> Path:
        return self.data_root / "raw"

    @property
    def cache_dir(self) -> Path:
        return self.data_root / "cache"

    @property
    def runs_dir(self) -> Path:
        return self.data_root / "runs"

    @property
    def logs_dir(self) -> Path:
        return self.data_root / "logs"

    @property
    def tmp_dir(self) -> Path:
        return self.data_root / "tmp"

    @property
    def duckdb_path(self) -> Path:
        return self.data_root / "fa.duckdb"

    def ensure_dirs(self) -> None:
        for d in (self.lake_dir, self.raw_dir, self.cache_dir, self.runs_dir, self.logs_dir, self.tmp_dir):
            d.mkdir(parents=True, exist_ok=True)

    def assert_not_onedrive(self) -> None:
        if "onedrive" in str(self.data_root).lower():
            raise RuntimeError(
                f"FA_DATA_ROOT={self.data_root} is inside OneDrive. The lake and DuckDB file must live "
                "outside OneDrive (default C:\\fadata) — sync will corrupt them."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.assert_not_onedrive()
    s.ensure_dirs()
    return s
