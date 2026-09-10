import unittest
from datetime import datetime, timedelta, timezone

from scanner.pricing import analyze_market_risk, calculate_quote, parse_money, parse_volume, steam_net_from_buyer_price


class PricingTests(unittest.TestCase):
    def test_parsers(self):
        self.assertEqual(parse_money("¥ 1,234.56 CNY"), 1234.56)
        self.assertEqual(parse_volume("12,345"), 12345)

    def test_quote_calculation(self):
        quote = calculate_quote(
            {"market_hash_name": "Test", "buff_price": 700},
            {"steam_price": 1000, "steam_volume": 50},
        )
        self.assertEqual(steam_net_from_buyer_price(1000), 869.57)
        self.assertAlmostEqual(quote["surface_discount"], 0.7)
        self.assertAlmostEqual(quote["balance_cost_rate"], 0.805, places=3)
        self.assertAlmostEqual(quote["balance_return"], 0.2422, places=3)
        self.assertEqual(quote["platform_fee"], 130.43)
        self.assertEqual(quote["net_profit"], 169.57)

    def test_seven_day_risk_and_liquidity(self):
        start = datetime.now(timezone.utc) - timedelta(days=6)
        history = [
            ((start + timedelta(days=i * 2)).isoformat(), price)
            for i, price in enumerate((100, 103, 101, 99))
        ]
        risk = analyze_market_risk(history, buff_price=70, volume=120)
        self.assertTrue(risk["history_ready"])
        self.assertEqual(risk["stability"], "稳定")
        self.assertEqual(risk["liquidity"], "快")
        self.assertAlmostEqual(risk["max_drawdown_7d"], 4 / 103)

    def test_history_is_not_claimed_stable_too_early(self):
        now = datetime.now(timezone.utc).isoformat()
        risk = analyze_market_risk([(now, 100), (now, 100)], buff_price=70, volume=5)
        self.assertFalse(risk["history_ready"])
        self.assertEqual(risk["stability"], "积累中")
        self.assertEqual(risk["liquidity"], "慢")


if __name__ == "__main__":
    unittest.main()
