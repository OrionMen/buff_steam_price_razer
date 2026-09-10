import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scanner.clients import BuffClient, SteamClient, RemoteAPIError, _get_json_curl
from scanner.config import Settings
from scanner.db import Database
from scanner.pricing import calculate_quote
from scanner.service import ScannerService


class ScanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = Settings('live', 'test-cookie', 20, 2000, 20, 1.5, 900,
                                 Path(self.temp.name) / 'test.db')
        self.db = Database(self.settings.database_path)

    def quote(self, name):
        return calculate_quote({'market_hash_name': name, 'buff_price': 10},
                               {'steam_price': 20, 'steam_volume': 100})

    def test_curl_preserves_http_status(self):
        with patch('scanner.clients.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'blocked\n429')):
            with self.assertRaises(RemoteAPIError) as caught:
                _get_json_curl('https://example.test', {})
        self.assertEqual(caught.exception.status_code, 429)

    def test_curl_utf8_and_invalid_json(self):
        with patch('scanner.clients.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '{"lowest_price":"¥ 12.34"}\n200')) as run:
            self.assertEqual(_get_json_curl('https://example.test', {})['lowest_price'], '¥ 12.34')
            self.assertEqual(run.call_args.kwargs['encoding'], 'utf-8')
        with patch('scanner.clients.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '<html>\n200')):
            with self.assertRaises(RemoteAPIError):
                _get_json_curl('https://example.test', {})

    def test_steam_429_reaches_fallback(self):
        steam = SteamClient(self.settings, self.db)
        with patch('scanner.clients._get_json_curl', side_effect=RemoteAPIError('limited', 429)), \
             patch.object(steam, '_search_price', return_value={'steam_price': 20}) as fallback, \
             patch('scanner.clients.time.sleep'):
            self.assertEqual(steam.price('A')['steam_price'], 20)
        fallback.assert_called_once_with('A')

    def test_buff_retry_and_spacing(self):
        buff = BuffClient(self.settings)
        payload = {'code': 'OK', 'data': {'items': []}}
        with patch('scanner.clients._get_json', side_effect=[RemoteAPIError('limited', 429, 25), payload, payload]) as request, \
             patch('scanner.clients.time.monotonic', return_value=100), \
             patch('scanner.clients.time.sleep') as sleep:
            buff.item_by_hash_name('A')
            buff.item_by_hash_name('B')
        self.assertEqual(request.call_count, 3)
        self.assertIn(25, [c.args[0] for c in sleep.call_args_list])
        self.assertGreaterEqual([c.args[0] for c in sleep.call_args_list].count(5), 2)

    def test_buff_long_retry_after_stops_without_early_retry(self):
        with patch('scanner.clients._get_json', side_effect=RemoteAPIError('limited', 429, 120)) as request:
            with self.assertRaises(RemoteAPIError):
                BuffClient(self.settings).item_by_hash_name('A')
        self.assertEqual(request.call_count, 1)

    def test_buff_business_error_is_not_empty_success(self):
        with patch('scanner.clients._get_json', return_value={'code': 'Login Required'}):
            with self.assertRaises(RemoteAPIError):
                BuffClient(self.settings).item_by_hash_name('A')

    def test_partial_preserves_old_and_stops_on_rate_limit(self):
        self.db.save_quotes(self.db.start_run('live'), [self.quote('old')])
        with patch('scanner.service.SteamClient') as steam_cls, patch('scanner.service.BuffClient') as buff_cls:
            steam = steam_cls.return_value
            steam.stats = {'steam_raw': 3, 'steam_candidates': 3, 'steam_success': 3}
            steam.issues = []
            steam.top_by_volume.return_value = [self.quote(n) for n in ['A', 'B', 'C']]
            buff = buff_cls.return_value
            buff.raw_count = 1
            buff.item_by_hash_name.side_effect = [{'market_hash_name': 'A', 'buff_price': 10}, RemoteAPIError('HTTP 429', 429)]
            self.assertEqual(ScannerService(self.settings, self.db).scan(), 1)
            self.assertEqual(buff.item_by_hash_name.call_count, 2)
        self.assertEqual({q['market_hash_name'] for q in self.db.top_quotes()}, {'old', 'A'})
        run = self.db.latest_run()
        self.assertEqual(run['status'], 'partial')
        counts = json.loads(run['details'])['counts']
        self.assertEqual(counts['buff_unattempted'], 1)
        self.assertEqual(counts['saved'], 1)
        self.assertEqual(counts['displayed'], 2)

    def test_complete_scan_replaces_old_results(self):
        self.db.save_quotes(self.db.start_run('live'), [self.quote('old')])
        with patch('scanner.service.SteamClient') as steam_cls, patch('scanner.service.BuffClient') as buff_cls:
            steam = steam_cls.return_value
            steam.stats = {'steam_raw': 1, 'steam_candidates': 1, 'steam_success': 1}
            steam.issues = []
            steam.top_by_volume.return_value = [self.quote('A')]
            buff_cls.return_value.raw_count = 1
            buff_cls.return_value.item_by_hash_name.return_value = {'market_hash_name': 'A', 'buff_price': 10}
            ScannerService(self.settings, self.db).scan()
        self.assertEqual([q['market_hash_name'] for q in self.db.top_quotes()], ['A'])
        self.assertEqual(self.db.latest_run()['status'], 'success')

    def test_twenty_candidates_fourteen_matches_are_partial(self):
        names = [str(i) for i in range(20)]
        self.db.save_quotes(self.db.start_run('live'), [self.quote(n) for n in names])
        with patch('scanner.service.SteamClient') as steam_cls, patch('scanner.service.BuffClient') as buff_cls:
            steam = steam_cls.return_value
            steam.stats = {'steam_raw': 20, 'steam_candidates': 20, 'steam_success': 20}
            steam.issues = []
            steam.top_by_volume.return_value = [self.quote(n) for n in names]
            buff_cls.return_value.raw_count = 14
            buff_cls.return_value.item_by_hash_name.side_effect = [
                {'market_hash_name': n, 'buff_price': 10} for n in names[:14]
            ] + [None] * 6
            self.assertEqual(ScannerService(self.settings, self.db).scan(), 14)
        run = self.db.latest_run()
        self.assertEqual(run['status'], 'partial')
        details = json.loads(run['details'])
        self.assertEqual(len(details['issues']), 6)
        self.assertEqual(details['counts']['buff_matched'], 14)
        self.assertEqual(details['counts']['displayed'], 20)

    def test_steam_failures_are_counted(self):
        steam = SteamClient(self.settings, self.db)
        self.db.cache_set('steam:popular:0:10', {'results': [{'hash_name': 'A'}, {'hash_name': 'B'}]}, 10**12)
        with patch.object(steam, 'price', side_effect=[{'steam_price': 20}, RemoteAPIError('HTTP 403', 403)]):
            results = steam.top_by_volume(2)
        self.assertEqual(len(results), 1)
        self.assertEqual(steam.stats, {'steam_raw': 2, 'steam_candidates': 2, 'steam_success': 1})
        self.assertIn('403', steam.issues[0])

    def test_zero_results_fail_and_preserve_old(self):
        self.db.save_quotes(self.db.start_run('live'), [self.quote('old')])
        with patch('scanner.service.SteamClient') as steam_cls:
            steam_cls.return_value.stats = {}
            steam_cls.return_value.issues = ['Steam HTTP 403']
            steam_cls.return_value.top_by_volume.return_value = []
            with self.assertRaises(RemoteAPIError):
                ScannerService(self.settings, self.db).scan()
        self.assertEqual(self.db.latest_run()['status'], 'failed')
        self.assertEqual(len(self.db.top_quotes()), 1)

    def test_replacement_rolls_back_on_bad_quote(self):
        run_id = self.db.start_run('live')
        self.db.save_quotes(run_id, [self.quote('old')])
        with self.assertRaises(KeyError):
            self.db.save_quotes(run_id, [self.quote('A'), {}], replace=True)
        self.assertEqual([q['market_hash_name'] for q in self.db.top_quotes()], ['old'])


if __name__ == '__main__':
    unittest.main()
