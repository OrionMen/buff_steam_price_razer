from __future__ import annotations

import json
from pathlib import Path

from .clients import BuffClient, RemoteAPIError, SteamClient
from .config import Settings
from .db import Database
from .pricing import calculate_quote


class ScannerService:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database

    def scan(self) -> int:
        run_id = self.database.start_run("demo" if self.settings.is_demo else "live")
        quotes: list[dict] = []
        try:
            if self.settings.is_demo:
                quotes = self._demo_quotes()
            else:
                steam = SteamClient(self.settings, self.database)
                steam_items = steam.top_by_volume(self.settings.buff_page_size)
                buff = BuffClient(self.settings)
                steam_errors: list[str] = []
                for steam_item in steam_items:
                    try:
                        item = buff.item_by_hash_name(steam_item["market_hash_name"])
                    except RemoteAPIError as exc:
                        steam_errors.append(str(exc))
                        continue
                    if item:
                        quotes.append(calculate_quote(item, steam_item))
                if not quotes and steam_errors:
                    raise RemoteAPIError(steam_errors[0])
            if not self.settings.is_demo and quotes:
                self.database.clear_latest_quotes()
            self.database.save_quotes(run_id, quotes)
            self.database.finish_run(run_id, "success", len(quotes))
            return len(quotes)
        except Exception as exc:
            self.database.finish_run(run_id, "failed", len(quotes), str(exc)[:300])
            raise

    def _demo_quotes(self) -> list[dict]:
        path = Path(__file__).resolve().parent.parent / "data" / "watchlist.json"
        items = json.loads(path.read_text(encoding="utf-8"))
        return [
            calculate_quote(
                {
                    "market_hash_name": item["market_hash_name"],
                    "chinese_name": item.get("chinese_name"),
                    "buff_goods_id": None,
                    "buff_price": item["buff_price"],
                },
                {"steam_price": item["steam_price"], "steam_volume": item["steam_volume"]},
            )
            for item in items
        ]
