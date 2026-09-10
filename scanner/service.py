from __future__ import annotations

import json
import logging
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
        details = {"counts": {}, "issues": []}
        saved_count = 0
        try:
            if self.settings.is_demo:
                quotes = self._demo_quotes()
            else:
                steam = SteamClient(self.settings, self.database)
                steam_items = steam.top_by_volume(self.settings.buff_page_size)
                details["counts"].update(steam.stats)
                details["issues"].extend(steam.issues)
                buff = BuffClient(self.settings)
                attempted = 0
                for steam_item in steam_items:
                    attempted += 1
                    try:
                        item = buff.item_by_hash_name(steam_item["market_hash_name"])
                    except RemoteAPIError as exc:
                        details["issues"].append(f"BUFF {steam_item['market_hash_name']}：{exc}")
                        if exc.status_code in (429, 401, 403):
                            break
                        continue
                    if item:
                        quotes.append(calculate_quote(item, steam_item))
                    else:
                        details["issues"].append(f"BUFF {steam_item['market_hash_name']}：无精确匹配或无有效价格")
                details["counts"].update(buff_attempted=attempted, buff_raw=buff.raw_count,
                                         buff_matched=len(quotes), buff_unattempted=len(steam_items) - attempted)
                if not quotes:
                    raise RemoteAPIError("本轮未取得可用结果，已保留旧报价；" + (details["issues"][0] if details["issues"] else "未返回候选"))
            partial = bool(details["issues"])
            self.database.save_quotes(run_id, quotes, replace=not self.settings.is_demo and not partial)
            saved_count = len(quotes)
            details["counts"].update(saved=saved_count, displayed=len(self.database.top_quotes(50)))
            self.database.finish_run(run_id, "partial" if partial else "success", saved_count,
                                     "部分商品未更新，保留其旧报价（如有）" if partial else None, details)
            logging.getLogger(__name__).info("Scan %s: %s", run_id, json.dumps(details, ensure_ascii=False))
            return len(quotes)
        except Exception as exc:
            details["counts"]["saved"] = saved_count
            self.database.finish_run(run_id, "failed", saved_count, str(exc)[:300], details)
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
