import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


class AppTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(os.environ)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["SCAN_MODE"] = "demo"
        os.environ["DATABASE_PATH"] = str(Path(self.temp_dir.name) / "test.db")
        from app import create_app
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_scan_flow(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="scan-loading"', response.get_data(as_text=True))
        self.assertIn("正在扫描实时市场", response.get_data(as_text=True))
        response = self.client.post("/scan", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("AK-47 | Redline", response.get_data(as_text=True))
        self.assertIn("AK-47 | 红线", response.get_data(as_text=True))
        self.assertIn("成功 · 8 件", response.get_data(as_text=True))
        self.assertIn("北京时间", response.get_data(as_text=True))

    def test_partial_scan_is_visible_with_old_quotes(self):
        from scanner.db import Database
        from scanner.pricing import calculate_quote
        db = Database(Path(os.environ['DATABASE_PATH']))
        old = calculate_quote({'market_hash_name': 'old', 'buff_price': 10},
                              {'steam_price': 20, 'steam_volume': 10})
        db.save_quotes(db.start_run('live'), [old])
        with db.connect() as connection:
            connection.execute("UPDATE latest_quotes SET captured_at='2020-01-01T00:00:00+00:00'")

        def partial_scan():
            db.finish_run(db.start_run('live'), 'partial', 14, '保留旧报价',
                          {'counts': {'saved': 14}, 'issues': ['BUFF HTTP 429']})
            return 14

        with patch('app.ScannerService.scan', side_effect=partial_scan):
            response = self.client.post('/scan', follow_redirects=True)
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('部分完成', html)
        self.assertIn('旧报价', html)
        self.assertIn('BUFF HTTP 429', html)


if __name__ == "__main__":
    unittest.main()
