from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .pricing import analyze_market_risk


SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL REFERENCES scan_runs(id),
    captured_at TEXT NOT NULL,
    market_hash_name TEXT NOT NULL,
    buff_goods_id TEXT,
    buff_price REAL NOT NULL,
    steam_price REAL NOT NULL,
    steam_volume INTEGER,
    steam_net REAL NOT NULL,
    surface_discount REAL NOT NULL,
    balance_cost_rate REAL NOT NULL,
    balance_return REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_name_time
    ON price_history(market_hash_name, captured_at DESC);
CREATE TABLE IF NOT EXISTS latest_quotes (
    market_hash_name TEXT PRIMARY KEY,
    chinese_name TEXT,
    steam_source TEXT,
    steam_listings INTEGER,
    buff_goods_id TEXT,
    buff_price REAL NOT NULL,
    steam_price REAL NOT NULL,
    steam_volume INTEGER,
    steam_net REAL NOT NULL,
    surface_discount REAL NOT NULL,
    balance_cost_rate REAL NOT NULL,
    balance_return REAL NOT NULL,
    grade TEXT NOT NULL,
    captured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS http_cache (
    cache_key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(latest_quotes)")}
            if "chinese_name" not in columns:
                connection.execute("ALTER TABLE latest_quotes ADD COLUMN chinese_name TEXT")
            if "steam_source" not in columns:
                connection.execute("ALTER TABLE latest_quotes ADD COLUMN steam_source TEXT")
            if "steam_listings" not in columns:
                connection.execute("ALTER TABLE latest_quotes ADD COLUMN steam_listings INTEGER")

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def start_run(self, mode: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO scan_runs(started_at, mode, status) VALUES (?, ?, 'running')",
                (utc_now(), mode),
            )
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, count: int, error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE scan_runs SET finished_at=?, status=?, item_count=?, error=? WHERE id=?",
                (utc_now(), status, count, error, run_id),
            )

    def save_quotes(self, run_id: int, quotes: list[dict[str, Any]]) -> None:
        captured_at = utc_now()
        history_sql = """INSERT INTO price_history(
            scan_id, captured_at, market_hash_name, buff_goods_id, buff_price,
            steam_price, steam_volume, steam_net, surface_discount,
            balance_cost_rate, balance_return
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        latest_sql = """INSERT INTO latest_quotes(
            market_hash_name, chinese_name, steam_source, steam_listings, buff_goods_id, buff_price, steam_price, steam_volume,
            steam_net, surface_discount, balance_cost_rate, balance_return, grade, captured_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(market_hash_name) DO UPDATE SET
            chinese_name=excluded.chinese_name, buff_goods_id=excluded.buff_goods_id, buff_price=excluded.buff_price,
            steam_source=excluded.steam_source, steam_listings=excluded.steam_listings,
            steam_price=excluded.steam_price, steam_volume=excluded.steam_volume,
            steam_net=excluded.steam_net, surface_discount=excluded.surface_discount,
            balance_cost_rate=excluded.balance_cost_rate,
            balance_return=excluded.balance_return, grade=excluded.grade,
            captured_at=excluded.captured_at"""
        with self.connect() as connection:
            for quote in quotes:
                common = (
                    quote["market_hash_name"], quote.get("buff_goods_id"), quote["buff_price"],
                    quote["steam_price"], quote.get("steam_volume"), quote["steam_net"],
                    quote["surface_discount"], quote["balance_cost_rate"], quote["balance_return"],
                )
                connection.execute(history_sql, (run_id, captured_at, *common))
                connection.execute(latest_sql, (
                    quote["market_hash_name"], quote.get("chinese_name"), quote.get("steam_source", "priceoverview"),
                    quote.get("steam_listings"), quote.get("buff_goods_id"),
                    quote["buff_price"], quote["steam_price"], quote.get("steam_volume"),
                    quote["steam_net"], quote["surface_discount"], quote["balance_cost_rate"],
                    quote["balance_return"], quote["grade"], captured_at,
                ))

    def clear_latest_quotes(self) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM latest_quotes")

    def top_quotes(self, limit: int = 50) -> list[dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
        with self.connect() as connection:
            latest = connection.execute("SELECT * FROM latest_quotes").fetchall()
            results: list[dict[str, Any]] = []
            for row in latest:
                history = connection.execute(
                    """SELECT captured_at, steam_price FROM price_history
                       WHERE market_hash_name=? AND captured_at>=?
                       ORDER BY captured_at ASC, id ASC""",
                    (row["market_hash_name"], cutoff),
                ).fetchall()
                item = dict(row)
                risk = analyze_market_risk(
                    [(point["captured_at"], point["steam_price"]) for point in history],
                    row["buff_price"],
                    row["steam_volume"],
                )
                item.update(risk)
                item["platform_fee"] = round(item["steam_price"] - item["steam_net"], 2)
                item["net_profit"] = round(item["steam_net"] - item["buff_price"], 2)
                item["risk_adjusted_cost"] = item["balance_cost_rate"] + risk["risk_penalty"]
                results.append(item)
        results.sort(key=lambda item: (item["risk_adjusted_cost"], -(item["steam_volume"] or 0)))
        return results[:limit]

    def latest_run(self) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute("SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()

    def cache_get(self, key: str, min_fetched_at: float) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM http_cache WHERE cache_key=? AND fetched_at>=?",
                (key, min_fetched_at),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def cache_get_any(self, key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT payload FROM http_cache WHERE cache_key=?", (key,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def cache_set(self, key: str, payload: dict[str, Any], fetched_at: float) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO http_cache(cache_key, payload, fetched_at) VALUES (?, ?, ?)
                   ON CONFLICT(cache_key) DO UPDATE SET payload=excluded.payload, fetched_at=excluded.fetched_at""",
                (key, json.dumps(payload, ensure_ascii=False), fetched_at),
            )
