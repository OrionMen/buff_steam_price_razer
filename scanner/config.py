from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    scan_mode: str
    buff_cookie: str
    buff_min_price: float
    buff_max_price: float
    buff_page_size: int
    steam_request_interval: float
    cache_ttl_seconds: int
    database_path: Path
    usd_cny_fallback_rate: float = 7.0

    @property
    def is_demo(self) -> bool:
        return self.scan_mode.lower() != "live"


def load_settings() -> Settings:
    _load_dotenv(BASE_DIR / ".env")
    database_path = Path(os.getenv("DATABASE_PATH", "data/scanner.db"))
    if not database_path.is_absolute():
        database_path = BASE_DIR / database_path
    return Settings(
        scan_mode=os.getenv("SCAN_MODE", "demo"),
        buff_cookie=os.getenv("BUFF_COOKIE", ""),
        buff_min_price=float(os.getenv("BUFF_MIN_PRICE", "20")),
        buff_max_price=float(os.getenv("BUFF_MAX_PRICE", "2000")),
        buff_page_size=max(1, min(80, int(os.getenv("BUFF_PAGE_SIZE", "20")))),
        steam_request_interval=max(0.5, float(os.getenv("STEAM_REQUEST_INTERVAL", "1.5"))),
        cache_ttl_seconds=max(60, int(os.getenv("CACHE_TTL_SECONDS", "900"))),
        database_path=database_path,
        usd_cny_fallback_rate=float(os.getenv("USD_CNY_FALLBACK_RATE", "7.0")),
    )
