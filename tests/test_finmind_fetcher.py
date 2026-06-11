# -*- coding: utf-8 -*-
"""
FinMindFetcher offline unit tests.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _make_mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def _daily_payload(rows):
    return {'msg': 'success', 'status': 200, 'data': rows}


_SAMPLE_DAILY_ROWS = [
    {
        'date': '2024-06-10', 'stock_id': '2330',
        'Trading_Volume': 20000000, 'Trading_money': 17000000000,
        'open': 850.0, 'max': 860.0, 'min': 845.0, 'close': 855.0,
        'spread': 5.0, 'Trading_turnover': 50000,
    },
    {
        'date': '2024-06-11', 'stock_id': '2330',
        'Trading_Volume': 18000000, 'Trading_money': 15500000000,
        'open': 856.0, 'max': 872.1, 'min': 855.0, 'close': 872.1,
        'spread': 17.1, 'Trading_turnover': 48000,
    },
]


class TestFinMindFetcherNormalize(unittest.TestCase):
    """Test _normalize_data with raw TaiwanStockPrice rows."""

    def setUp(self):
        import pandas as pd
        from data_provider.finmind_fetcher import FinMindFetcher
        self.fetcher = FinMindFetcher()
        self.raw = pd.DataFrame(_SAMPLE_DAILY_ROWS)

    def test_normalize_columns(self):
        result = self.fetcher._normalize_data(self.raw, 'TW2330')
        for col in ('date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg'):
            self.assertIn(col, result.columns)
        self.assertEqual(result.iloc[0]['code'], 'TW2330')
        self.assertAlmostEqual(result.iloc[0]['high'], 860.0)
        self.assertAlmostEqual(result.iloc[0]['low'], 845.0)

    def test_normalize_calculates_pct_chg(self):
        result = self.fetcher._normalize_data(self.raw, 'TW2330')
        self.assertAlmostEqual(result.iloc[1]['pct_chg'], 2.0)
        self.assertAlmostEqual(result.iloc[0]['pct_chg'], 0.0)

    def test_normalize_empty_df(self):
        import pandas as pd
        result = self.fetcher._normalize_data(pd.DataFrame(), 'TW2330')
        self.assertTrue(result.empty)


class TestFinMindFetcherFetchRaw(unittest.TestCase):
    """Test _fetch_raw_data with mocked HTTP."""

    def setUp(self):
        from data_provider.finmind_fetcher import FinMindFetcher
        self.fetcher = FinMindFetcher()
        self.fetcher._token = 'test_token'

    @patch('data_provider.finmind_fetcher.requests.get')
    def test_fetch_raw_success(self, mock_get):
        mock_get.return_value = _make_mock_response(_daily_payload(_SAMPLE_DAILY_ROWS))
        df = self.fetcher._fetch_raw_data('TW2330', '2024-06-10', '2024-06-11')
        self.assertFalse(df.empty)
        self.assertIn('close', df.columns)
        # token 应随请求一起发送
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs['params'].get('token'), 'test_token')
        self.assertEqual(kwargs['params'].get('data_id'), '2330')

    @patch('data_provider.finmind_fetcher.requests.get')
    def test_fetch_raw_without_token(self, mock_get):
        self.fetcher._token = ''
        mock_get.return_value = _make_mock_response(_daily_payload(_SAMPLE_DAILY_ROWS))
        df = self.fetcher._fetch_raw_data('TW2330', '2024-06-10', '2024-06-11')
        self.assertFalse(df.empty)
        _, kwargs = mock_get.call_args
        self.assertNotIn('token', kwargs['params'])

    @patch('data_provider.finmind_fetcher.requests.get')
    def test_fetch_raw_empty_response(self, mock_get):
        from data_provider.base import DataFetchError
        mock_get.return_value = _make_mock_response(_daily_payload([]))
        with self.assertRaises(DataFetchError):
            self.fetcher._fetch_raw_data('TW9999', '2024-06-10', '2024-06-11')

    @patch('data_provider.finmind_fetcher.requests.get')
    def test_fetch_raw_api_error_status(self, mock_get):
        from data_provider.base import DataFetchError
        mock_get.return_value = _make_mock_response({'msg': 'quota exceeded', 'status': 402, 'data': []})
        with self.assertRaises(DataFetchError):
            self.fetcher._fetch_raw_data('TW2330', '2024-06-10', '2024-06-11')

    @patch('data_provider.finmind_fetcher.requests.get')
    def test_fetch_raw_http_error(self, mock_get):
        from data_provider.base import DataFetchError
        mock_get.side_effect = Exception('connection timeout')
        with self.assertRaises(DataFetchError):
            self.fetcher._fetch_raw_data('TW2330', '2024-06-10', '2024-06-11')

    def test_fetch_raw_rejects_non_tw(self):
        from data_provider.base import DataFetchError
        with self.assertRaises(DataFetchError):
            self.fetcher._fetch_raw_data('600519', '2024-06-10', '2024-06-11')
        with self.assertRaises(DataFetchError):
            self.fetcher._fetch_raw_data('AAPL', '2024-06-10', '2024-06-11')


class TestFinMindFetcherRealtimeQuote(unittest.TestCase):
    """Test get_realtime_quote with mocked HTTP."""

    def setUp(self):
        from data_provider.finmind_fetcher import FinMindFetcher
        self.fetcher = FinMindFetcher()
        self.fetcher._token = 'test_token'
        # 预置名称缓存，避免 get_stock_name 触发额外请求
        self.fetcher._stock_info_cache = {'2330': {'name': '台积电', 'type': 'twse'}}

    @patch('data_provider.finmind_fetcher.requests.get')
    def test_realtime_quote_success(self, mock_get):
        mock_get.return_value = _make_mock_response({
            'msg': 'success', 'status': 200,
            'data': [{
                'stock_id': '2330', 'open': 850.0, 'high': 860.0, 'low': 845.0,
                'close': 855.0, 'change_price': 5.0, 'change_rate': 0.59,
                'total_volume': 20000, 'total_amount': 17000000000,
                'volume_ratio': 1.2,
            }],
        })
        quote = self.fetcher.get_realtime_quote('TW2330')
        self.assertIsNotNone(quote)
        self.assertEqual(quote.code, 'TW2330')
        self.assertEqual(quote.name, '台积电')
        self.assertAlmostEqual(quote.price, 855.0)
        self.assertAlmostEqual(quote.change_pct, 0.59)
        self.assertAlmostEqual(quote.pre_close, 850.0)

    @patch('data_provider.finmind_fetcher.requests.get')
    def test_realtime_quote_api_failure_degrades_to_none(self, mock_get):
        """实时快照对 token 等级有要求，失败时必须静默返回 None。"""
        mock_get.return_value = _make_mock_response({'msg': 'permission denied', 'status': 402, 'data': []})
        quote = self.fetcher.get_realtime_quote('TW2330')
        self.assertIsNone(quote)

    @patch('data_provider.finmind_fetcher.requests.get')
    def test_realtime_quote_http_failure(self, mock_get):
        mock_get.side_effect = Exception('timeout')
        quote = self.fetcher.get_realtime_quote('TW2330')
        self.assertIsNone(quote)

    def test_realtime_quote_non_tw(self):
        self.assertIsNone(self.fetcher.get_realtime_quote('600519'))
        self.assertIsNone(self.fetcher.get_realtime_quote('AAPL'))


class TestFinMindFetcherStockName(unittest.TestCase):
    """Test get_stock_name / get_tw_listing_type with mocked TaiwanStockInfo."""

    def setUp(self):
        from data_provider.finmind_fetcher import FinMindFetcher
        self.fetcher = FinMindFetcher()
        self.fetcher._token = 'test_token'

    @patch('data_provider.finmind_fetcher.requests.get')
    def test_get_stock_name_found(self, mock_get):
        mock_get.return_value = _make_mock_response({
            'msg': 'success', 'status': 200,
            'data': [
                {'stock_id': '2330', 'stock_name': '台积电', 'type': 'twse'},
                {'stock_id': '6488', 'stock_name': '环球晶', 'type': 'tpex'},
            ],
        })
        self.assertEqual(self.fetcher.get_stock_name('TW2330'), '台积电')
        self.assertEqual(self.fetcher.get_stock_name('tw6488'), '环球晶')
        # 全表只拉一次（缓存生效）
        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(self.fetcher.get_tw_listing_type('TW6488'), 'tpex')

    @patch('data_provider.finmind_fetcher.requests.get')
    def test_get_stock_name_fetch_failure(self, mock_get):
        mock_get.side_effect = Exception('timeout')
        self.assertIsNone(self.fetcher.get_stock_name('TW2330'))

    def test_get_stock_name_non_tw(self):
        self.assertIsNone(self.fetcher.get_stock_name('600519'))


class TestFinMindFetcherRegistration(unittest.TestCase):
    """FinMindFetcher 应无条件注册（免 token 可用）。"""

    @patch('src.config.get_config')
    def test_always_registered(self, mock_config):
        mock_config.return_value = MagicMock(
            finnhub_api_key=None,
            alphavantage_api_key=None,
            finmind_token=None,
            tushare_token=None,
            longbridge_app_key=None,
            longbridge_app_secret=None,
            longbridge_access_token=None,
            tickflow_api_key=None,
        )
        from data_provider.base import DataFetcherManager
        mgr = DataFetcherManager()
        names = [f.name for f in mgr._get_fetchers_snapshot()]
        self.assertIn('FinMindFetcher', names)
        # 台股日线路由排序：FinMind 应优先于 Yfinance
        self.assertLess(names.index('FinMindFetcher'), names.index('YfinanceFetcher'))


if __name__ == '__main__':
    unittest.main()
