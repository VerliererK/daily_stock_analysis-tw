# -*- coding: utf-8 -*-
"""台股筹码面（三大法人/融资融券/外资持股）注入 LLM 分析上下文的回归测试。"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from src.analyzer import GeminiAnalyzer


_SAMPLE_TW_CHIP = {
    'latest_date': '2026-06-12',
    'institutional': {
        'days': 5,
        'foreign_net_today': -1000,
        'trust_net_today': 300,
        'dealer_net_today': -50,
        'foreign_net_nd': 1000,
        'trust_net_nd': -200,
        'dealer_net_nd': 150,
    },
    'margin': {
        'days': 5,
        'margin_balance': 27470,
        'margin_change_today': -530,
        'margin_change_nd': -1030,
        'short_balance': 1000,
        'short_change_today': -200,
        'short_change_nd': -100,
    },
    'foreign_holding_ratio': 69.96,
}


def _make_analyzer():
    with patch.object(GeminiAnalyzer, '_init_litellm', return_value=None):
        return GeminiAnalyzer()


class TestTwChipPromptSection(unittest.TestCase):
    def setUp(self):
        # 显式固定语言变体，避免真实 .env 的 REPORT_LANGUAGE=zh-tw 影响断言文案
        from src import report_language as rl
        self._rl = rl
        self._orig_variant = rl.get_active_report_language_variant()
        rl.set_active_report_language_variant(None)

    def tearDown(self):
        self._rl.set_active_report_language_variant(self._orig_variant)

    def _base_context(self, **extra):
        context = {
            'code': 'TW2330',
            'stock_name': '台積電',
            'date': '2026-06-12',
            'today': {'close': 2310.0, 'ma5': 2283.0, 'ma10': 2320.0, 'ma20': 2298.5},
        }
        context.update(extra)
        return context

    def test_prompt_includes_tw_chip_section(self):
        analyzer = _make_analyzer()
        prompt = analyzer._format_prompt(
            self._base_context(tw_chip=_SAMPLE_TW_CHIP), '台積電', news_context=None,
        )
        self.assertIn('台股筹码面（法人与信用交易，截至 2026-06-12）', prompt)
        self.assertIn('外资买卖超', prompt)
        self.assertIn('-1,000 张', prompt)
        self.assertIn('+1,000 张', prompt)
        self.assertIn('融资余额', prompt)
        self.assertIn('27,470 张', prompt)
        self.assertIn('外资持股比率', prompt)
        self.assertIn('69.96%', prompt)
        self.assertIn('轧空', prompt)

    def test_tw_chip_suppresses_chip_unavailable_hint(self):
        analyzer = _make_analyzer()
        prompt = analyzer._format_prompt(
            self._base_context(tw_chip=_SAMPLE_TW_CHIP), '台積電', news_context=None,
        )
        self.assertNotIn('筹码分布未启用或数据源暂不可用', prompt)

    def test_without_tw_chip_keeps_unavailable_hint(self):
        analyzer = _make_analyzer()
        prompt = analyzer._format_prompt(self._base_context(), '台積電', news_context=None)
        self.assertIn('筹码分布未启用或数据源暂不可用', prompt)
        self.assertNotIn('台股筹码面', prompt)

    def test_partial_tw_chip_renders_available_rows_only(self):
        analyzer = _make_analyzer()
        partial = {'latest_date': '2026-06-12', 'institutional': _SAMPLE_TW_CHIP['institutional']}
        prompt = analyzer._format_prompt(
            self._base_context(tw_chip=partial), '台積電', news_context=None,
        )
        self.assertIn('外资买卖超', prompt)
        # 指引文字会提到融资/外资持股概念，断言只检查数据表格行不存在
        self.assertNotIn('| 融资余额 |', prompt)
        self.assertNotIn('| 外资持股比率 |', prompt)


class TestManagerTwChipDelegation(unittest.TestCase):
    """DataFetcherManager.get_tw_chip_summary 的能力探测与市场过滤。"""

    def test_delegates_to_capable_fetcher_for_tw(self):
        from data_provider.base import DataFetcherManager

        finmind = MagicMock()
        finmind.name = 'FinMindFetcher'
        finmind.priority = 1
        finmind.get_tw_chip_summary.return_value = _SAMPLE_TW_CHIP

        yfinance = MagicMock(spec=['name', 'priority'])
        yfinance.name = 'YfinanceFetcher'
        yfinance.priority = 4

        mgr = DataFetcherManager(fetchers=[finmind, yfinance])
        summary = mgr.get_tw_chip_summary('2330')
        self.assertEqual(summary, _SAMPLE_TW_CHIP)
        finmind.get_tw_chip_summary.assert_called_once_with('TW2330')

    def test_non_tw_returns_none_without_calls(self):
        from data_provider.base import DataFetcherManager

        finmind = MagicMock()
        finmind.name = 'FinMindFetcher'
        finmind.priority = 1

        mgr = DataFetcherManager(fetchers=[finmind])
        self.assertIsNone(mgr.get_tw_chip_summary('600519'))
        self.assertIsNone(mgr.get_tw_chip_summary('AAPL'))
        finmind.get_tw_chip_summary.assert_not_called()


class TestChipStructurePreservation(unittest.TestCase):
    """有台股筹码面时，LLM 写入的 chip_structure 不得被 unavailable 后处理清空。"""

    @staticmethod
    def _make_result(chip_structure):
        from src.analyzer import AnalysisResult
        result = AnalysisResult(
            code='TW2330', name='台積電',
            sentiment_score=50, trend_prediction='震盪', operation_advice='觀望',
        )
        result.report_language = 'zh'
        result.dashboard = {'data_perspective': {'chip_structure': dict(chip_structure)}}
        return result

    def test_preserves_llm_chip_structure_with_tw_chip(self):
        from src.analyzer import normalize_chip_structure_availability
        cs = {'profit_ratio': '外資近5日賣超5.2萬張，籌碼鬆動', 'concentration': '法人持股集中'}
        result = self._make_result(cs)
        normalize_chip_structure_availability(result, None, _SAMPLE_TW_CHIP)
        kept = result.dashboard['data_perspective']['chip_structure']
        self.assertEqual(kept, cs)
        self.assertNotIn('chip_unavailable_reason', result.dashboard['data_perspective'])

    def test_marks_unavailable_when_llm_left_placeholders(self):
        """LLM 留占位值时，应用台股筹码面数据直接填充（确定性，不依赖 LLM）。"""
        from src.analyzer import normalize_chip_structure_availability
        result = self._make_result({'profit_ratio': '数据缺失', 'avg_cost': 'N/A'})
        normalize_chip_structure_availability(result, None, _SAMPLE_TW_CHIP)
        filled = result.dashboard['data_perspective']['chip_structure']
        self.assertIn('外资', filled['profit_ratio'])
        self.assertIn('1,000张', filled['profit_ratio'])
        self.assertIn('融资余额27,470张', filled['avg_cost'])
        self.assertIn('外资持股69.96%', filled['concentration'])
        # 外资近5日买超且融资余额下降 -> 健康
        self.assertEqual(filled['chip_health'], '健康')
        self.assertNotIn('chip_unavailable_reason', result.dashboard['data_perspective'])

    def test_llm_null_chip_structure_gets_filled(self):
        """LLM 输出 chip_structure: null 时也应被填充。"""
        from src.analyzer import normalize_chip_structure_availability
        result = self._make_result({})
        result.dashboard['data_perspective']['chip_structure'] = None
        normalize_chip_structure_availability(result, None, _SAMPLE_TW_CHIP)
        filled = result.dashboard['data_perspective']['chip_structure']
        self.assertTrue(filled)
        self.assertIn('外资', filled['profit_ratio'])

    def test_marks_unavailable_without_any_chip_source(self):
        from src.analyzer import normalize_chip_structure_availability
        result = self._make_result({'profit_ratio': '看起来健康'})
        normalize_chip_structure_availability(result, None, None)
        self.assertEqual(result.dashboard['data_perspective']['chip_structure'], {})


if __name__ == '__main__':
    unittest.main()
