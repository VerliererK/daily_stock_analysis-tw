# -*- coding: utf-8 -*-
"""台股新闻搜索（繁体台湾用语查询/Brave locale/中文偏好）的回归测试。"""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.search_service import SearchService, SearchResponse, SearchResult


def _result(title: str) -> SearchResult:
    return SearchResult(
        title=title,
        url='https://example.com',
        snippet='snippet',
        source='example',
        published_date=datetime.now().date().isoformat(),
    )


def _response(results) -> SearchResponse:
    return SearchResponse(results=results, query='q', provider='mock')


def _make_service():
    service = SearchService(
        bocha_keys=['dummy_key'],
        searxng_public_instances_enabled=False,
        news_max_age_days=3,
        news_strategy_profile='short',
    )
    mock_search = MagicMock(return_value=_response([_result('item')]))
    service._providers[0].search = mock_search
    return service, mock_search


def _captured_queries(mock_search):
    queries = []
    for call in mock_search.call_args_list:
        query = call.args[0] if call.args else call.kwargs.get('query', '')
        queries.append(query)
    return ' || '.join(queries)


class TestPreferChineseNews(unittest.TestCase):
    def test_tw_codes_prefer_chinese(self):
        # 即使股名是英文（FinMind 失败时的 fallback），台股代码也应判定中文优先
        self.assertTrue(SearchService._should_prefer_chinese_news('TW2330', 'TSMC'))
        self.assertTrue(SearchService._should_prefer_chinese_news('2330', 'TSMC'))

    def test_existing_behavior_unchanged(self):
        self.assertTrue(SearchService._should_prefer_chinese_news('600519', 'Moutai'))
        self.assertFalse(SearchService._should_prefer_chinese_news('AAPL', 'Apple'))
        self.assertTrue(SearchService._should_prefer_chinese_news('AAPL', '苹果'))


class TestBraveLocale(unittest.TestCase):
    def test_tw_uses_traditional_taiwan(self):
        locale = SearchService._brave_search_locale('TW2330', prefer_chinese=True)
        self.assertEqual(locale, {'search_lang': 'zh-hant', 'country': 'TW'})

    def test_cn_keeps_simplified(self):
        locale = SearchService._brave_search_locale('600519', prefer_chinese=True)
        self.assertEqual(locale, {'search_lang': 'zh-hans', 'country': 'CN'})

    def test_us_unchanged(self):
        locale = SearchService._brave_search_locale('AAPL', prefer_chinese=False)
        self.assertEqual(locale, {'search_lang': 'en', 'country': 'US'})


class TestTwSearchQueries(unittest.TestCase):
    def test_comprehensive_intel_uses_tw_terms(self):
        service, mock_search = _make_service()
        with patch('src.search_service.time.sleep'):
            service.search_comprehensive_intel(
                stock_code='TW2330', stock_name='台積電', max_searches=6,
            )
        queries = _captured_queries(mock_search)
        # 台湾用语与纯数字代码
        self.assertIn('重大訊息', queries)
        self.assertIn('法說會', queries)
        self.assertIn('台股', queries)
        self.assertIn('2330', queries)
        self.assertNotIn('TW2330', queries)
        # 不应混入 A 股资讯生态用语
        self.assertNotIn('上交所', queries)
        self.assertNotIn('cninfo', queries)

    def test_comprehensive_intel_cn_unchanged(self):
        service, mock_search = _make_service()
        with patch('src.search_service.time.sleep'):
            service.search_comprehensive_intel(
                stock_code='600519', stock_name='贵州茅台', max_searches=6,
            )
        queries = _captured_queries(mock_search)
        self.assertIn('上交所', queries)
        self.assertNotIn('法說會', queries)

    def test_comprehensive_intel_us_unchanged(self):
        service, mock_search = _make_service()
        with patch('src.search_service.time.sleep'):
            service.search_comprehensive_intel(
                stock_code='AAPL', stock_name='Apple', max_searches=6,
            )
        queries = _captured_queries(mock_search)
        self.assertIn('earnings', queries)
        self.assertNotIn('法說會', queries)

    def test_stock_news_query_uses_digits_and_tw_context(self):
        service, mock_search = _make_service()
        with patch('src.search_service.time.sleep'):
            service.search_stock_news('TW2330', '台積電', max_results=5)
        query = _captured_queries(mock_search)
        self.assertIn('台積電 2330 台股 最新消息', query)
        self.assertNotIn('TW2330', query)


if __name__ == '__main__':
    unittest.main()
