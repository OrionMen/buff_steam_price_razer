import os
import tempfile
import unittest
from pathlib import Path


class AppTests(unittest.TestCase):
    def setUp(self):
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


if __name__ == "__main__":
    unittest.main()
