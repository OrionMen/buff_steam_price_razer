from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import Settings
from .db import Database
from .pricing import parse_money, parse_volume


USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36"


class RemoteAPIError(RuntimeError):
    pass


def _get_json(
    url: str,
    headers: dict[str, str],
    timeout: int = 15,
    attempts: int = 3,
) -> dict[str, Any]:
    """Fetch JSON with bounded backoff for transient errors and rate limiting."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                break
            retry_after = exc.headers.get("Retry-After")
            delay = min(15.0, float(retry_after)) if retry_after and retry_after.isdigit() else 2.0 ** attempt
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(2.0 ** attempt)
    if isinstance(last_error, urllib.error.HTTPError):
        raise RemoteAPIError(f"远端接口返回 HTTP {last_error.code}；请稍后重试或调高请求间隔") from last_error
    raise RemoteAPIError(f"请求失败：{type(last_error).__name__}") from last_error


def _get_json_curl(url: str, headers: dict[str, str], timeout: int = 20) -> dict[str, Any]:
    """Use the system HTTPS client for Steam, whose edge rejects urllib TLS clients."""
    command = ["curl", "--fail-with-body", "--silent", "--show-error", "--max-time", str(timeout)]
    for key, value in headers.items():
        command.extend(["-H", f"{key}: {value}"])
    command.append(url)
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout + 5)
        return json.loads(completed.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise RemoteAPIError(f"请求失败：{type(exc).__name__}") from exc


class BuffClient:
    ENDPOINT = "https://buff.163.com/api/market/goods"

    def __init__(self, settings: Settings):
        self.settings = settings

    def popular_items(self) -> list[dict[str, Any]]:
        if not self.settings.buff_cookie:
            raise RemoteAPIError("实时模式需要在 .env 中配置 BUFF_COOKIE")
        params = urllib.parse.urlencode({
            "game": "csgo",
            "page_num": 1,
            "page_size": self.settings.buff_page_size,
            "sort_by": "sell_num.desc",
            "min_price": self.settings.buff_min_price,
            "max_price": self.settings.buff_max_price,
        })
        payload = _get_json(
            f"{self.ENDPOINT}?{params}",
            {"User-Agent": USER_AGENT, "Cookie": self.settings.buff_cookie, "Referer": "https://buff.163.com/market/csgo"},
        )
        items = payload.get("data", {}).get("items", [])
        parsed: list[dict[str, Any]] = []
        for item in items:
            goods_info = item.get("goods_info") or {}
            name = item.get("market_hash_name") or goods_info.get("market_hash_name")
            chinese_name = item.get("name") or item.get("short_name") or goods_info.get("name")
            price = parse_money(item.get("sell_min_price"))
            if name and price and self.settings.buff_min_price <= price <= self.settings.buff_max_price:
                parsed.append({
                    "market_hash_name": name,
                    "chinese_name": chinese_name or name,
                    "buff_goods_id": str(item.get("id", "")),
                    "buff_price": price,
                })
        if not parsed:
            raise RemoteAPIError("BUFF 未返回可用商品；Cookie 可能已失效或筛选区间无结果")
        return parsed[: self.settings.buff_page_size]

    def item_by_hash_name(self, market_hash_name: str) -> dict[str, Any] | None:
        if not self.settings.buff_cookie:
            raise RemoteAPIError("实时模式需要在 .env 中配置 BUFF_COOKIE")
        params = urllib.parse.urlencode({"game": "csgo", "search": market_hash_name, "page_num": 1})
        payload = _get_json(
            f"{self.ENDPOINT}?{params}",
            {"User-Agent": USER_AGENT, "Cookie": self.settings.buff_cookie, "Referer": "https://buff.163.com/market/csgo"},
        )
        for item in payload.get("data", {}).get("items", []):
            goods_info = item.get("goods_info") or {}
            name = item.get("market_hash_name") or goods_info.get("market_hash_name")
            if name != market_hash_name:
                continue
            price = parse_money(item.get("sell_min_price"))
            if not price:
                return None
            return {
                "market_hash_name": name,
                "chinese_name": item.get("name") or item.get("short_name") or goods_info.get("name") or name,
                "buff_goods_id": str(item.get("id", "")),
                "buff_price": price,
            }
        return None


class SteamClient:
    ENDPOINT = "https://steamcommunity.com/market/priceoverview/"
    SEARCH_ENDPOINT = "https://steamcommunity.com/market/search/render/"
    FX_ENDPOINT = "https://api.frankfurter.app/latest?from=USD&to=CNY"

    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self._last_request = 0.0
        self._use_search_fallback = False
        self._search_exact_blocked = False
        self._popular_search_cache: dict[str, dict[str, Any]] | None = None

    def price(self, market_hash_name: str) -> dict[str, Any] | None:
        cache_key = f"steam:cny:{market_hash_name}"
        cached = self.database.cache_get(cache_key, time.time() - self.settings.cache_ttl_seconds)
        if cached is not None:
            return cached
        wait_for = max(2.5, self.settings.steam_request_interval) - (time.monotonic() - self._last_request)
        if wait_for > 0:
            time.sleep(wait_for)
        if self._use_search_fallback:
            result = self._search_price(market_hash_name)
        else:
            params = urllib.parse.urlencode({
                "appid": 730,
                "currency": 23,
                "country": "CN",
                "market_hash_name": market_hash_name,
            })
            try:
                payload = _get_json_curl(f"{self.ENDPOINT}?{params}", {"User-Agent": USER_AGENT})
                price = parse_money(payload.get("lowest_price"))
                if not payload.get("success") or not price:
                    return None
                result = {
                    "steam_price": price,
                    "steam_volume": parse_volume(payload.get("volume")),
                    "steam_source": "priceoverview",
                    "steam_listings": None,
                }
            except RemoteAPIError as exc:
                if "HTTP 429" not in str(exc):
                    raise
                self._use_search_fallback = True
                result = self._search_price(market_hash_name)
        self._last_request = time.monotonic()
        if result is None:
            return None
        self.database.cache_set(cache_key, result, time.time())
        return result

    def top_by_volume(self, limit: int = 20) -> list[dict[str, Any]]:
        """Use Steam's popular market order as a small candidate pool, then rank by 24h volume."""
        names: list[str] = []
        popular_items: dict[str, dict[str, Any]] = {}
        for start in range(0, limit, 10):
            cache_key = f"steam:popular:{start}:10"
            payload = self.database.cache_get(cache_key, time.time() - self.settings.cache_ttl_seconds)
            if payload is None:
                self._throttle()
                params = urllib.parse.urlencode({
                    "query": "", "start": start, "count": min(10, limit - start),
                    "search_descriptions": 0, "sort_column": "popular", "sort_dir": "desc",
                    "appid": 730, "norender": 1,
                })
                try:
                    payload = _get_json(f"{self.SEARCH_ENDPOINT}?{params}", {"User-Agent": USER_AGENT})
                    self.database.cache_set(cache_key, payload, time.time())
                    self._last_request = time.monotonic()
                except RemoteAPIError:
                    payload = self.database.cache_get_any(cache_key)
                    if payload is None:
                        raise
            for item in payload.get("results") or []:
                if item.get("hash_name"):
                    names.append(item["hash_name"])
                    popular_items[item["hash_name"]] = item
        self._popular_search_cache = popular_items
        results: list[dict[str, Any]] = []
        for name in dict.fromkeys(names):
            try:
                quote = self.price(name)
            except RemoteAPIError:
                continue
            if quote:
                results.append({"market_hash_name": name, **quote})
        results.sort(key=lambda item: (item.get("steam_volume") is None, -(item.get("steam_volume") or 0)))
        return results[:limit]

    def _throttle(self) -> None:
        wait_for = max(2.5, self.settings.steam_request_interval) - (time.monotonic() - self._last_request)
        if wait_for > 0:
            time.sleep(wait_for)

    def _search_price(self, market_hash_name: str) -> dict[str, Any] | None:
        if self._search_exact_blocked:
            return self._popular_search_price(market_hash_name)
        params = urllib.parse.urlencode({
            "query": market_hash_name,
            "start": 0,
            "count": 10,
            "search_descriptions": 0,
            "appid": 730,
            "norender": 1,
        })
        try:
            payload = _get_json(
                f"{self.SEARCH_ENDPOINT}?{params}",
                {"User-Agent": USER_AGENT},
                attempts=1,
            )
        except RemoteAPIError as exc:
            if "HTTP 429" not in str(exc):
                raise
            self._search_exact_blocked = True
            return self._popular_search_price(market_hash_name)
        for item in payload.get("results") or []:
            if item.get("hash_name") == market_hash_name and item.get("sell_price") is not None:
                return self._search_result(item)
        return None

    def _popular_search_price(self, market_hash_name: str) -> dict[str, Any] | None:
        if self._popular_search_cache is None:
            params = urllib.parse.urlencode({
                "query": "",
                "start": 0,
                "count": 100,
                "search_descriptions": 0,
                "sort_column": "popular",
                "sort_dir": "desc",
                "appid": 730,
                "norender": 1,
            })
            payload = _get_json(f"{self.SEARCH_ENDPOINT}?{params}", {"User-Agent": USER_AGENT})
            self._popular_search_cache = {
                item["hash_name"]: item
                for item in payload.get("results") or []
                if item.get("hash_name") and item.get("sell_price") is not None
            }
        item = self._popular_search_cache.get(market_hash_name)
        return self._search_result(item) if item else None

    def _search_result(self, item: dict[str, Any]) -> dict[str, Any]:
        cny_price = round(float(item["sell_price"]) / 100 * self._usd_cny_rate(), 2)
        return {
            "steam_price": cny_price,
            "steam_volume": None,
            "steam_source": "search_usd_fx",
            "steam_listings": int(item.get("sell_listings") or 0),
        }

    def _usd_cny_rate(self) -> float:
        cache_key = "fx:USD:CNY"
        cached = self.database.cache_get(cache_key, time.time() - 21600)
        if cached and cached.get("rate"):
            return float(cached["rate"])
        try:
            payload = _get_json(self.FX_ENDPOINT, {"User-Agent": USER_AGENT}, attempts=2)
            rate = float(payload["rates"]["CNY"])
            self.database.cache_set(cache_key, {"rate": rate, "date": payload.get("date")}, time.time())
            return rate
        except (RemoteAPIError, KeyError, TypeError, ValueError):
            return self.settings.usd_cny_fallback_rate
