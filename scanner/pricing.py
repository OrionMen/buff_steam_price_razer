from __future__ import annotations

import re
from datetime import datetime


def parse_money(value: str | int | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^0-9.,-]", "", value).replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_volume(value: str | int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).replace(",", "").strip())
    except ValueError:
        return None


def steam_net_from_buyer_price(buyer_price: float) -> float:
    """Estimated seller receipt for a CS2 listing; low-price rounding may differ."""
    return round(buyer_price / 1.15, 2)


def analyze_market_risk(history: list[tuple[str, float]], buff_price: float, volume: int | None) -> dict:
    """Turn locally collected seven-day snapshots into hold-risk indicators."""
    prices = [float(price) for _, price in history if price and price > 0]
    if prices:
        average = sum(prices) / len(prices)
        range_rate = (max(prices) - min(prices)) / average
        peak = prices[0]
        max_drawdown = 0.0
        for price in prices:
            peak = max(peak, price)
            max_drawdown = max(max_drawdown, (peak - price) / peak)
        observed_days = (
            datetime.fromisoformat(history[-1][0]) - datetime.fromisoformat(history[0][0])
        ).total_seconds() / 86400
        stress_return = steam_net_from_buyer_price(min(prices)) / buff_price - 1
    else:
        range_rate = max_drawdown = observed_days = 0.0
        stress_return = None

    data_ready = len(prices) >= 4 and observed_days >= 5.5
    if not data_ready:
        stability = "积累中"
        stability_key = "pending"
        stability_penalty = 0.04
    elif range_rate <= 0.05 and max_drawdown <= 0.04:
        stability = "稳定"
        stability_key = "stable"
        stability_penalty = 0.0
    elif range_rate <= 0.10 and max_drawdown <= 0.08:
        stability = "一般"
        stability_key = "normal"
        stability_penalty = 0.03
    else:
        stability = "波动大"
        stability_key = "volatile"
        stability_penalty = 0.08

    if volume is None:
        liquidity, liquidity_key, liquidity_penalty = "未知", "unknown", 0.08
    elif volume >= 100:
        liquidity, liquidity_key, liquidity_penalty = "快", "fast", 0.0
    elif volume >= 20:
        liquidity, liquidity_key, liquidity_penalty = "中", "medium", 0.02
    else:
        liquidity, liquidity_key, liquidity_penalty = "慢", "slow", 0.06

    return {
        "history_samples": len(prices),
        "observed_days": observed_days,
        "range_7d": range_rate,
        "max_drawdown_7d": max_drawdown,
        "stress_return_7d": stress_return,
        "stability": stability,
        "stability_key": stability_key,
        "liquidity": liquidity,
        "liquidity_key": liquidity_key,
        "risk_penalty": stability_penalty + liquidity_penalty,
        "history_ready": data_ready,
    }


def calculate_quote(buff_item: dict, steam_item: dict) -> dict:
    buff_price = float(buff_item["buff_price"])
    steam_price = float(steam_item["steam_price"])
    if buff_price <= 0 or steam_price <= 0:
        raise ValueError("Prices must be positive")
    steam_net = steam_net_from_buyer_price(steam_price)
    cost_rate = buff_price / steam_net
    balance_return = steam_net / buff_price - 1
    volume = steam_item.get("steam_volume")
    if cost_rate <= 0.72 and (volume or 0) >= 20:
        grade = "A"
    elif cost_rate <= 0.80 and (volume or 0) >= 10:
        grade = "B"
    elif cost_rate <= 0.88:
        grade = "C"
    else:
        grade = "D"
    return {
        **buff_item,
        **steam_item,
        "steam_net": steam_net,
        "platform_fee": round(steam_price - steam_net, 2),
        "net_profit": round(steam_net - buff_price, 2),
        "surface_discount": buff_price / steam_price,
        "balance_cost_rate": cost_rate,
        "balance_return": balance_return,
        "grade": grade,
    }
