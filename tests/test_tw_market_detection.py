# -*- coding: utf-8 -*-
"""
台股（TW）代码判别、标准化与市场路由的离线回归测试。

覆盖约定：
- TW2330 / tw2330 / 2330.TW / 6488.TWO / 裸 4 位数字 -> 台股
- 5 位纯数字维持港股判定（台股 5 位 ETF 需带 TW 前缀/后缀）
- 6 位纯数字维持 A 股判定
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestTwMarketHelpers(unittest.TestCase):
    """data_provider/tw_market.py 基础函数。"""

    def test_is_tw_stock_code(self):
        from data_provider.tw_market import is_tw_stock_code
        for code in ('TW2330', 'tw2330', '2330.TW', '6488.TWO', '2330', '0050',
                     'TW00878', '00878.TW', 'TW00675L'):
            self.assertTrue(is_tw_stock_code(code), code)
        for code in ('600519', '00700', 'HK00700', '0700.HK', 'AAPL', 'BRK.B',
                     'TW', 'TWLO', '', None):
            self.assertFalse(is_tw_stock_code(code), code)

    def test_canonical_tw_code(self):
        from data_provider.tw_market import canonical_tw_code
        self.assertEqual(canonical_tw_code('tw2330'), 'TW2330')
        self.assertEqual(canonical_tw_code('2330.TW'), 'TW2330')
        self.assertEqual(canonical_tw_code('6488.TWO'), 'TW6488')
        self.assertEqual(canonical_tw_code('2330'), 'TW2330')
        self.assertEqual(canonical_tw_code('00878.TW'), 'TW00878')
        self.assertIsNone(canonical_tw_code('600519'))
        self.assertIsNone(canonical_tw_code('00878'))  # 裸 5 位维持港股

    def test_to_finmind_stock_id(self):
        from data_provider.tw_market import to_finmind_stock_id
        self.assertEqual(to_finmind_stock_id('TW2330'), '2330')
        self.assertEqual(to_finmind_stock_id('00878.TW'), '00878')
        with self.assertRaises(ValueError):
            to_finmind_stock_id('600519')

    def test_to_yf_tw_symbols(self):
        from data_provider.tw_market import to_yf_tw_symbols
        self.assertEqual(to_yf_tw_symbols('TW2330'), ['2330.TW', '2330.TWO'])
        self.assertEqual(to_yf_tw_symbols('6488.TWO'), ['6488.TW', '6488.TWO'])


class TestNormalizeStockCode(unittest.TestCase):
    """data_provider/base.py normalize_stock_code 的台股与回归案例。"""

    def test_tw_codes(self):
        from data_provider.base import normalize_stock_code
        self.assertEqual(normalize_stock_code('tw2330'), 'TW2330')
        self.assertEqual(normalize_stock_code('2330.TW'), 'TW2330')
        self.assertEqual(normalize_stock_code('6488.TWO'), 'TW6488')
        self.assertEqual(normalize_stock_code('2330'), 'TW2330')

    def test_existing_markets_unchanged(self):
        from data_provider.base import normalize_stock_code
        self.assertEqual(normalize_stock_code('600519'), '600519')
        self.assertEqual(normalize_stock_code('SH600519'), '600519')
        self.assertEqual(normalize_stock_code('00878'), '00878')   # 5 位 -> 港股语义
        self.assertEqual(normalize_stock_code('hk00700'), 'HK00700')
        self.assertEqual(normalize_stock_code('1810.HK'), 'HK01810')
        self.assertEqual(normalize_stock_code('AAPL'), 'AAPL')


class TestMarketTag(unittest.TestCase):
    """data_provider/base.py _market_tag。"""

    def test_market_tags(self):
        from data_provider.base import _market_tag
        self.assertEqual(_market_tag('TW2330'), 'tw')
        self.assertEqual(_market_tag('2330'), 'tw')
        self.assertEqual(_market_tag('600519'), 'cn')
        self.assertEqual(_market_tag('00700'), 'hk')
        self.assertEqual(_market_tag('HK00700'), 'hk')
        self.assertEqual(_market_tag('AAPL'), 'us')


class TestDetectMarket(unittest.TestCase):
    """src/market_context.py detect_market 与 prompt 守则。"""

    def test_detect_tw(self):
        from src.market_context import detect_market
        for code in ('TW2330', 'tw2330', '2330.TW', '6488.TWO', '2330', '0050'):
            self.assertEqual(detect_market(code), 'tw', code)

    def test_detect_existing_markets_unchanged(self):
        from src.market_context import detect_market
        self.assertEqual(detect_market('600519'), 'cn')
        self.assertEqual(detect_market('00700'), 'hk')
        self.assertEqual(detect_market('hk00700'), 'hk')
        self.assertEqual(detect_market('AAPL'), 'us')
        self.assertEqual(detect_market('BRK.B'), 'us')
        self.assertEqual(detect_market(None), 'cn')

    def test_tw_role_and_guidelines(self):
        from src.market_context import get_market_role, get_market_guidelines
        self.assertIn('台股', get_market_role('TW2330', 'zh'))
        guidelines = get_market_guidelines('TW2330', 'zh')
        self.assertIn('台股', guidelines)
        self.assertIn('±10%', guidelines)
        self.assertIn('Taiwan', get_market_guidelines('TW2330', 'en'))


class TestTradingCalendar(unittest.TestCase):
    """src/core/trading_calendar.py 台股市场识别。"""

    def test_get_market_for_stock(self):
        from src.core.trading_calendar import get_market_for_stock
        self.assertEqual(get_market_for_stock('TW2330'), 'tw')
        self.assertEqual(get_market_for_stock('2330'), 'tw')
        self.assertEqual(get_market_for_stock('600519'), 'cn')
        self.assertEqual(get_market_for_stock('HK00700'), 'hk')
        self.assertEqual(get_market_for_stock('AAPL'), 'us')

    def test_market_constants(self):
        from src.core.trading_calendar import MARKET_EXCHANGE, MARKET_TIMEZONE
        self.assertEqual(MARKET_EXCHANGE.get('tw'), 'XTAI')
        self.assertEqual(MARKET_TIMEZONE.get('tw'), 'Asia/Taipei')


class TestYfinanceTwConversion(unittest.TestCase):
    """yfinance 台股代码转换与后缀缓存。"""

    def setUp(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher
        self.fetcher = YfinanceFetcher()

    def test_convert_tw_default_listed(self):
        self.assertEqual(self.fetcher._convert_stock_code('TW2330'), '2330.TW')
        self.assertEqual(self.fetcher._convert_stock_code('tw0050'), '0050.TW')

    def test_convert_tw_uses_resolved_suffix_cache(self):
        # 模拟已解析为上柜（.TWO）
        self.fetcher._tw_symbol_cache['6488.TW'] = '6488.TWO'
        self.assertEqual(self.fetcher._convert_stock_code('TW6488'), '6488.TWO')

    def test_convert_existing_markets_unchanged(self):
        self.assertEqual(self.fetcher._convert_stock_code('600519'), '600519.SS')
        self.assertEqual(self.fetcher._convert_stock_code('hk00700'), '0700.HK')
        self.assertEqual(self.fetcher._convert_stock_code('AAPL'), 'AAPL')

    def test_tw_symbol_candidates_order(self):
        self.assertEqual(self.fetcher._tw_symbol_candidates('TW2330'), ['2330.TW', '2330.TWO'])
        self.fetcher._tw_symbol_cache['2330.TW'] = '2330.TWO'
        self.assertEqual(self.fetcher._tw_symbol_candidates('TW2330'), ['2330.TWO', '2330.TW'])


class TestStockCodeUtils(unittest.TestCase):
    """src/services/stock_code_utils.py 的 Web/API 输入闸门。"""

    def test_is_code_like_tw(self):
        from src.services.stock_code_utils import is_code_like
        for code in ('2330', 'tw2330', '2330.TW', '6488.TWO', 'TW00878'):
            self.assertTrue(is_code_like(code), code)

    def test_normalize_code_tw(self):
        from src.services.stock_code_utils import normalize_code
        self.assertEqual(normalize_code('2330'), 'TW2330')
        self.assertEqual(normalize_code('tw2330'), 'TW2330')
        self.assertEqual(normalize_code('6488.TWO'), 'TW6488')

    def test_normalize_code_existing_unchanged(self):
        from src.services.stock_code_utils import normalize_code
        self.assertEqual(normalize_code('600519'), '600519')
        self.assertEqual(normalize_code('00700'), '00700')
        self.assertEqual(normalize_code('AAPL'), 'AAPL')
        self.assertEqual(normalize_code('SH600519'), '600519')


class TestDailyRoutingFilter(unittest.TestCase):
    """台股日线路由应只保留 FinMind 与 Yfinance。"""

    @patch('src.config.get_config')
    def test_tw_daily_fetcher_filter(self, mock_config):
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
        fetchers = mgr._get_fetchers_snapshot()
        kept = DataFetcherManager._filter_daily_fetchers_for_market(fetchers, 'tw')
        kept_names = {f.name for f in kept}
        self.assertEqual(kept_names, {'FinMindFetcher', 'YfinanceFetcher'})


if __name__ == '__main__':
    unittest.main()
