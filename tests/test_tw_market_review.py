# -*- coding: utf-8 -*-
"""台股大盘 review（region=tw）的回归测试。"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestTwMarketProfileAndStrategy(unittest.TestCase):
    def test_get_profile_tw(self):
        from src.core.market_profile import get_profile
        profile = get_profile('tw')
        self.assertEqual(profile.region, 'tw')
        self.assertEqual(profile.mood_index_code, 'TWII')
        self.assertFalse(profile.has_market_stats)
        self.assertTrue(any('台股' in q for q in profile.news_queries))

    def test_get_profile_existing_regions_unchanged(self):
        from src.core.market_profile import get_profile
        self.assertEqual(get_profile('cn').mood_index_code, '000001')
        self.assertEqual(get_profile('us').mood_index_code, 'SPX')
        self.assertEqual(get_profile('hk').mood_index_code, 'HSI')
        self.assertEqual(get_profile('unknown').region, 'cn')

    def test_strategy_blueprint_tw(self):
        from src.core.market_strategy import get_market_strategy_blueprint
        bp = get_market_strategy_blueprint('tw')
        self.assertEqual(bp.region, 'tw')
        self.assertIn('加权指数', bp.positioning)
        self.assertIn('外资', bp.positioning + ''.join(bp.action_framework))


class TestMarketReviewRegionParsing(unittest.TestCase):
    def test_config_parse_accepts_tw(self):
        from src.config import Config
        self.assertEqual(Config._parse_market_review_region('tw'), 'tw')
        self.assertEqual(Config._parse_market_review_region('tw,us'), 'tw,us')
        self.assertEqual(Config._parse_market_review_region('both'), 'both')
        self.assertEqual(Config._parse_market_review_region('cn'), 'cn')
        self.assertEqual(Config._parse_market_review_region('invalid'), 'cn')

    def test_resolve_regions_includes_tw(self):
        from src.core.market_review import _resolve_market_review_regions
        self.assertEqual(_resolve_market_review_regions('tw'), ['tw'])
        self.assertEqual(_resolve_market_review_regions('tw,us'), ['us', 'tw'])
        self.assertIn('tw', _resolve_market_review_regions('both'))

    def test_compute_effective_region_tw(self):
        from src.core.trading_calendar import compute_effective_region
        self.assertEqual(compute_effective_region('tw', {'tw'}), 'tw')
        self.assertEqual(compute_effective_region('tw', {'cn', 'us'}), '')
        self.assertEqual(compute_effective_region('tw,us', {'us'}), 'us')
        self.assertEqual(compute_effective_region('tw,us', {'tw', 'us'}), 'tw,us')
        self.assertEqual(compute_effective_region('both', {'cn', 'tw'}), 'cn,tw')

    def test_compute_effective_region_existing_unchanged(self):
        from src.core.trading_calendar import compute_effective_region
        self.assertEqual(compute_effective_region('cn', {'cn'}), 'cn')
        self.assertEqual(compute_effective_region('cn', set()), '')
        self.assertEqual(compute_effective_region('both', {'cn', 'hk', 'us'}), 'cn,hk,us')
        self.assertEqual(compute_effective_region('garbage', {'cn'}), 'cn')


class TestMarketAnalyzerTwRegion(unittest.TestCase):
    @staticmethod
    def _make_analyzer():
        from src.market_analyzer import MarketAnalyzer
        config = MagicMock(report_language='zh', market_review_color_scheme='green_up')
        with patch('src.market_analyzer.DataFetcherManager'):
            return MarketAnalyzer(config=config, region='tw')

    def test_region_gate_accepts_tw(self):
        analyzer = self._make_analyzer()
        self.assertEqual(analyzer.region, 'tw')
        self.assertEqual(analyzer.profile.mood_index_code, 'TWII')
        self.assertEqual(analyzer.strategy.region, 'tw')

    def test_scope_name_and_title(self):
        analyzer = self._make_analyzer()
        self.assertEqual(analyzer._get_market_scope_name('zh'), '台股市场')
        self.assertEqual(analyzer._get_market_scope_name('en'), 'Taiwan market')
        self.assertIn('台股大盘复盘', analyzer._get_review_title('2026-06-13'))

    def test_unknown_region_still_falls_back_to_cn(self):
        from src.market_analyzer import MarketAnalyzer
        config = MagicMock(report_language='zh')
        with patch('src.market_analyzer.DataFetcherManager'):
            analyzer = MarketAnalyzer(config=config, region='jp')
        self.assertEqual(analyzer.region, 'cn')


class TestYfinanceTwIndices(unittest.TestCase):
    def test_get_main_indices_tw_routes_to_tw_indices(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher
        fetcher = YfinanceFetcher()

        def fake_fetch(yf, yf_symbol, name, code):
            return {'code': code, 'name': name, 'current': 100.0, 'change': 1.0,
                    'change_pct': 1.0, 'open': 99.0, 'high': 101.0, 'low': 98.0,
                    'prev_close': 99.0, 'volume': 0, 'amount': 0, 'amplitude': 3.0}

        with patch.object(fetcher, '_fetch_yf_ticker_data', side_effect=fake_fetch):
            result = fetcher.get_main_indices(region='tw')

        codes = [item['code'] for item in result]
        self.assertIn('TWII', codes)
        self.assertIn('0050', codes)
        names = [item['name'] for item in result]
        self.assertIn('加权指数', names)

    def test_get_main_indices_tw_filters_nan_items(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher
        fetcher = YfinanceFetcher()

        def fake_fetch(yf, yf_symbol, name, code):
            current = float('nan') if code == '0050' else 100.0
            return {'code': code, 'name': name, 'current': current, 'change': 1.0,
                    'change_pct': 1.0, 'open': 99.0, 'high': 101.0, 'low': 98.0,
                    'prev_close': 99.0, 'volume': 0, 'amount': 0, 'amplitude': 3.0}

        with patch.object(fetcher, '_fetch_yf_ticker_data', side_effect=fake_fetch):
            result = fetcher.get_main_indices(region='tw')

        codes = [item['code'] for item in result]
        self.assertNotIn('0050', codes)
        self.assertIn('TWII', codes)

    def test_market_light_schema_accepts_tw(self):
        from src.schemas.market_light import MarketRegion
        from typing import get_args
        self.assertIn('tw', get_args(MarketRegion))

    def test_other_fetchers_return_none_for_tw(self):
        from data_provider.efinance_fetcher import EfinanceFetcher
        from data_provider.akshare_fetcher import AkshareFetcher
        self.assertIsNone(EfinanceFetcher().get_main_indices(region='tw'))
        self.assertIsNone(AkshareFetcher().get_main_indices(region='tw'))


if __name__ == '__main__':
    unittest.main()
