# -*- coding: utf-8 -*-
"""REPORT_LANGUAGE=zh-tw（台湾繁体中文）支持的回归测试。

约定：
- 内部基础语言仍为 zh（既有 zh/en 分支与模板逻辑不变）
- config.report_language_variant 记录 'zh-tw' 变体
- LLM prompt 指示原生输出台湾繁体；模板文案经 OpenCC s2twp 兜底转换（臺→台 归一）
- 语义解析 map（operation_advice / trend 等）必须认得繁体词
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src import report_language as rl


class TestActiveVariantPushModel(unittest.TestCase):
    """variant 由 config 加载时 push；report_language 不得反向触发 get_config()。"""

    def tearDown(self):
        rl.set_active_report_language_variant(None)

    def test_setter_and_getter(self):
        rl.set_active_report_language_variant('zh-tw')
        self.assertEqual(rl.get_active_report_language_variant(), 'zh-tw')
        rl.set_active_report_language_variant(None)
        self.assertIsNone(rl.get_active_report_language_variant())

    def test_setter_rejects_unknown_variant(self):
        rl.set_active_report_language_variant('zh-hk')
        self.assertIsNone(rl.get_active_report_language_variant())

    def test_setter_clears_labels_cache(self):
        rl.set_active_report_language_variant('zh-tw')
        rl.get_report_labels('zh')  # 填充缓存
        self.assertTrue(rl._TW_LABELS_CACHE)
        rl.set_active_report_language_variant(None)
        self.assertFalse(rl._TW_LABELS_CACHE)

    def test_getter_does_not_import_config(self):
        import sys
        with patch.dict(sys.modules, {'src.config': None}):
            # 即使 config 模块不可用也不应抛错（无反向依赖）
            self.assertIsNone(rl.get_active_report_language_variant())


class TestVariantDetection(unittest.TestCase):
    def test_variant_aliases(self):
        for raw in ('zh-tw', 'zh_TW', 'ZH-TW', 'zh-hant', 'zh_hant'):
            self.assertEqual(rl.get_report_language_variant(raw), 'zh-tw', raw)

    def test_non_variant_values(self):
        for raw in ('zh', 'zh-cn', 'en', '', None, 'invalid'):
            self.assertIsNone(rl.get_report_language_variant(raw), raw)

    def test_normalize_keeps_zh_base(self):
        self.assertEqual(rl.normalize_report_language('zh-tw'), 'zh')
        self.assertEqual(rl.normalize_report_language('zh-hant'), 'zh')


class TestApplyVariantConversion(unittest.TestCase):
    def test_simplified_to_taiwan_traditional(self):
        self.assertEqual(rl.apply_report_language_variant('观望', 'zh-tw'), '觀望')
        self.assertEqual(rl.apply_report_language_variant('涨跌幅', 'zh-tw'), '漲跌幅')
        # 台湾用语转换（s2twp）：软件->軟體、数据->資料
        self.assertEqual(rl.apply_report_language_variant('软件和数据', 'zh-tw'), '軟體和資料')

    def test_tai_char_normalized(self):
        # OpenCC 会输出「臺」，应归一为现代惯用的「台」
        self.assertEqual(rl.apply_report_language_variant('台积电', 'zh-tw'), '台積電')
        self.assertEqual(rl.apply_report_language_variant('台股大盘', 'zh-tw'), '台股大盤')

    def test_idempotent_on_traditional(self):
        for text in ('台積電', '本益比與量能', '法人買賣超'):
            self.assertEqual(rl.apply_report_language_variant(text, 'zh-tw'), text)

    def test_no_variant_returns_unchanged(self):
        self.assertEqual(rl.apply_report_language_variant('观望', None), '观望')
        self.assertEqual(rl.apply_report_language_variant('观望', 'zh-cn'), '观望')

    def test_empty_text(self):
        self.assertEqual(rl.apply_report_language_variant('', 'zh-tw'), '')
        self.assertIsNone(rl.apply_report_language_variant(None, 'zh-tw'))


class TestTraditionalSemanticParsing(unittest.TestCase):
    """LLM 以繁体输出 operation_advice / trend 时，语义解析不得失效。"""

    def test_infer_decision_type_traditional(self):
        cases = {
            '觀望': 'hold',
            '買入': 'buy',
            '強烈買入': 'buy',
            '加碼': 'buy',
            '賣出': 'sell',
            '強烈賣出': 'sell',
            '減碼': 'sell',
            '減倉': 'sell',
            '持有': 'hold',
            '洗盤觀察': 'hold',
        }
        for advice, expected in cases.items():
            self.assertEqual(rl.infer_decision_type_from_advice(advice), expected, advice)

    def test_infer_decision_type_traditional_negation(self):
        self.assertEqual(rl.infer_decision_type_from_advice('不建議買入，繼續觀望'), 'hold')

    def test_signal_level_traditional(self):
        _, emoji, tag = rl.get_signal_level('觀望', 50, 'zh')
        self.assertEqual(tag, 'watch')
        _, _, tag = rl.get_signal_level('買入', 70, 'zh')
        self.assertEqual(tag, 'buy')

    def test_trend_prediction_traditional(self):
        # zh 输出下繁体中文视为已是中文，原样保留
        self.assertEqual(rl.localize_trend_prediction('震盪', 'zh'), '震盪')
        # en 输出下繁体可被翻译
        self.assertEqual(rl.localize_trend_prediction('震盪', 'en'), 'Sideways')
        self.assertEqual(rl.localize_trend_prediction('強勢空頭', 'en'), 'Strong Bearish')

    def test_chip_placeholder_traditional(self):
        self.assertTrue(rl.is_chip_placeholder_value('數據缺失'))
        self.assertTrue(rl.is_chip_placeholder_value('資料缺失，無法判斷'))


class TestLabelsLocalizedUnderVariant(unittest.TestCase):
    def setUp(self):
        rl._TW_LABELS_CACHE.clear()

    def tearDown(self):
        rl._TW_LABELS_CACHE.clear()

    def test_report_labels_converted(self):
        with patch.object(rl, 'get_active_report_language_variant', return_value='zh-tw'):
            labels = rl.get_report_labels('zh')
        self.assertEqual(labels['dashboard_title'], '決策儀表盤')
        self.assertEqual(labels['buy_label'], '買入')
        self.assertEqual(labels['watch_label'], '觀望')

    def test_report_labels_unchanged_without_variant(self):
        with patch.object(rl, 'get_active_report_language_variant', return_value=None):
            labels = rl.get_report_labels('zh')
        self.assertEqual(labels['dashboard_title'], '决策仪表盘')

    def test_placeholder_texts_converted(self):
        with patch.object(rl, 'get_active_report_language_variant', return_value='zh-tw'):
            self.assertEqual(rl.get_placeholder_text('zh'), '待補充')
            self.assertEqual(rl.get_no_data_text('zh'), '資料缺失')

    def test_english_labels_unaffected(self):
        with patch.object(rl, 'get_active_report_language_variant', return_value='zh-tw'):
            labels = rl.get_report_labels('en')
        self.assertEqual(labels['dashboard_title'], 'Decision Dashboard')


class TestConfigVariantParsing(unittest.TestCase):
    def test_parse_report_language_zh_tw(self):
        from src.config import Config
        self.assertEqual(Config._parse_report_language('zh-tw'), 'zh')
        self.assertEqual(rl.get_report_language_variant('zh-tw'), 'zh-tw')

    def test_supported_value_check(self):
        self.assertTrue(rl.is_supported_report_language_value('zh-tw'))
        self.assertTrue(rl.is_supported_report_language_value('zh-hant'))


class TestPromptLanguageSections(unittest.TestCase):
    def test_agent_language_section_zh_tw(self):
        from src.agent import executor
        with patch.object(executor, 'get_active_report_language_variant', return_value='zh-tw'):
            section = executor._build_language_section('zh')
            chat_section = executor._build_language_section('zh', chat_mode=True)
        self.assertIn('台灣繁體中文', section)
        self.assertIn('本益比', section)
        self.assertIn('台灣繁體中文', chat_section)

    def test_agent_language_section_default_zh(self):
        from src.agent import executor
        with patch.object(executor, 'get_active_report_language_variant', return_value=None):
            section = executor._build_language_section('zh')
        self.assertNotIn('台灣繁體中文', section)
        self.assertIn('使用中文', section)

    def test_agent_language_section_en_unaffected(self):
        from src.agent import executor
        with patch.object(executor, 'get_active_report_language_variant', return_value='zh-tw'):
            section = executor._build_language_section('en')
        self.assertIn('English', section)
        self.assertNotIn('台灣繁體中文', section)


if __name__ == '__main__':
    unittest.main()
