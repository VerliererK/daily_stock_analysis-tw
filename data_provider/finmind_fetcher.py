# -*- coding: utf-8 -*-
"""
FinMindFetcher — 台股数据源（Priority 1）

数据来源：FinMind Open Data HTTP API（https://finmindtrade.com/）
- 免 token 可用（300 次/小时），配置 FINMIND_TOKEN 后提升到 600 次/小时
- 日线：dataset=TaiwanStockPrice
- 实时快照：dataset=taiwan_stock_tick_snapshot（部分等级 token 不可用，失败时静默
  降级返回 None，由 DataFetcherManager fallback 到 Yfinance）
- 股票名称：dataset=TaiwanStockInfo（全表拉取后内存缓存）

Markets: TW only
"""

import logging
from threading import RLock
from typing import Any, Dict, Optional

import pandas as pd
import requests

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS
from .realtime_types import UnifiedRealtimeQuote, RealtimeSource
from .tw_market import is_tw_stock_code, to_finmind_stock_id

logger = logging.getLogger(__name__)

_FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"


class FinMindFetcher(BaseFetcher):
    name = "FinMindFetcher"
    priority = 1

    def __init__(self):
        from src.config import get_config
        config = get_config()
        self._token = (getattr(config, 'finmind_token', None) or "").strip()
        self._stock_info_cache: Optional[Dict[str, Dict[str, str]]] = None
        self._stock_info_lock = RLock()
        if not self._token:
            logger.debug("[FinMind] 未配置 FINMIND_TOKEN，使用免认证限额（300 次/小时）")

    def _request(self, params: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        """调用 FinMind v4 data API，返回解析后的 JSON。"""
        if self._token:
            params = {**params, 'token': self._token}
        resp = requests.get(_FINMIND_API_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        status = data.get('status')
        if status != 200:
            raise DataFetchError(f"[FinMind] API 返回异常: status={status}, msg={data.get('msg')}")
        return data

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        if not is_tw_stock_code(stock_code):
            raise DataFetchError(f"[FinMind] {stock_code} 不是台股代码")

        stock_id = to_finmind_stock_id(stock_code)
        try:
            self.random_sleep(0.3, 0.8)
            data = self._request({
                'dataset': 'TaiwanStockPrice',
                'data_id': stock_id,
                'start_date': start_date,
                'end_date': end_date,
            })
        except DataFetchError:
            raise
        except Exception as e:
            raise DataFetchError(f"[FinMind] 获取 {stock_id} 日线失败: {e}") from e

        rows = data.get('data') or []
        if not rows:
            raise DataFetchError(f"[FinMind] {stock_id} 无日线数据")
        return pd.DataFrame(rows)

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        if df.empty:
            return df

        df = df.copy()
        # TaiwanStockPrice 字段: date, stock_id, Trading_Volume, Trading_money,
        # open, max, min, close, spread, Trading_turnover
        df['date'] = pd.to_datetime(df['date']).dt.date
        df = df.rename(columns={
            'max': 'high',
            'min': 'low',
            'Trading_Volume': 'volume',
            'Trading_money': 'amount',
        })
        df['pct_chg'] = df['close'].pct_change() * 100
        df['pct_chg'] = df['pct_chg'].fillna(0).round(2)
        df['code'] = stock_code

        keep = ['code'] + STANDARD_COLUMNS
        df = df[[col for col in keep if col in df.columns]]
        return df

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        if not is_tw_stock_code(stock_code):
            return None

        stock_id = to_finmind_stock_id(stock_code)
        try:
            self.random_sleep(0.3, 0.8)
            data = self._request({
                'dataset': 'taiwan_stock_tick_snapshot',
                'data_id': stock_id,
            })
        except Exception as e:
            # 实时快照对 token 等级有要求，失败时静默降级（fallback 到 Yfinance）
            logger.debug(f"[FinMind] 获取 {stock_id} 实时快照失败: {e}")
            return None

        rows = data.get('data') or []
        if not rows:
            return None
        snap = rows[-1] if isinstance(rows, list) else rows

        price = snap.get('close') or snap.get('deal_price')
        if not price:
            return None

        change_pct = snap.get('change_rate')
        change_amount = snap.get('change_price')
        high = snap.get('high')
        low = snap.get('low')
        open_price = snap.get('open')
        volume = snap.get('total_volume') or snap.get('volume')
        amount = snap.get('total_amount') or snap.get('amount')

        pre_close = None
        if price is not None and change_amount is not None:
            pre_close = round(float(price) - float(change_amount), 4)

        amplitude = None
        if high and low and pre_close and pre_close > 0:
            amplitude = round((float(high) - float(low)) / pre_close * 100, 2)

        return UnifiedRealtimeQuote(
            code=stock_code.strip().upper(),
            name=self.get_stock_name(stock_code) or "",
            source=RealtimeSource.FALLBACK,
            price=float(price),
            change_pct=round(float(change_pct), 2) if change_pct is not None else None,
            change_amount=round(float(change_amount), 4) if change_amount is not None else None,
            volume=volume,
            amount=amount,
            volume_ratio=snap.get('volume_ratio'),
            turnover_rate=None,
            amplitude=amplitude,
            open_price=open_price,
            high=high,
            low=low,
            pre_close=pre_close,
        )

    def _load_stock_info(self) -> Dict[str, Dict[str, str]]:
        """拉取 TaiwanStockInfo 全表并缓存为 {stock_id: {name, type}}。"""
        with self._stock_info_lock:
            if self._stock_info_cache is not None:
                return self._stock_info_cache
            try:
                data = self._request({'dataset': 'TaiwanStockInfo'}, timeout=30)
                cache: Dict[str, Dict[str, str]] = {}
                for item in data.get('data') or []:
                    sid = item.get('stock_id')
                    if sid:
                        cache[str(sid)] = {
                            'name': item.get('stock_name') or '',
                            'type': item.get('type') or '',
                        }
                self._stock_info_cache = cache
                logger.info(f"[FinMind] TaiwanStockInfo 缓存完成，共 {len(cache)} 档")
            except Exception as e:
                logger.warning(f"[FinMind] 拉取 TaiwanStockInfo 失败: {e}")
                self._stock_info_cache = {}
            return self._stock_info_cache

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        if not is_tw_stock_code(stock_code):
            return None
        info = self._load_stock_info().get(to_finmind_stock_id(stock_code))
        return (info or {}).get('name') or None

    def get_tw_listing_type(self, stock_code: str) -> Optional[str]:
        """返回上市别：'twse'（上市）/ 'tpex'（上柜），未知返回 None。"""
        if not is_tw_stock_code(stock_code):
            return None
        info = self._load_stock_info().get(to_finmind_stock_id(stock_code))
        return (info or {}).get('type') or None

    # ------------------------------------------------------------------
    # 台股筹码面（三大法人买卖超 / 融资融券 / 外资持股）
    # ------------------------------------------------------------------

    def _fetch_dataset_rows(self, dataset: str, stock_id: str, start_date: str) -> list:
        """拉取单一筹码面 dataset 的原始 rows（失败返回空 list，fail-soft）。"""
        try:
            self.random_sleep(0.3, 0.8)
            data = self._request({
                'dataset': dataset,
                'data_id': stock_id,
                'start_date': start_date,
            })
            return data.get('data') or []
        except Exception as e:
            logger.debug(f"[FinMind] 获取 {dataset}({stock_id}) 失败: {e}")
            return []

    def get_tw_market_institutional_summary(self) -> Optional[Dict[str, Any]]:
        """汇总台股【全市场】三大法人买卖超（亿元），供大盘复盘使用。

        使用 TaiwanStockTotalInstitutionalInvestors（免 token 可用、无需 data_id，
        与个股 TaiwanStockInstitutionalInvestorsBuySell 不同，后者已转赞助等级）。
        取最近一个交易日的外资/投信/自营商净买卖超。

        Returns:
            {'date', 'foreign_net', 'trust_net', 'dealer_net', 'total_net'}
            单位：亿元（正值为买超）；无数据时返回 None（fail-soft）。
        """
        from datetime import datetime, timedelta
        start_date = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d')
        try:
            self.random_sleep(0.3, 0.8)
            data = self._request({
                'dataset': 'TaiwanStockTotalInstitutionalInvestors',
                'start_date': start_date,
            })
            rows = data.get('data') or []
        except Exception as e:
            logger.debug(f"[FinMind] 获取全市场三大法人失败: {e}")
            return None
        if not rows:
            return None

        latest_date = sorted({r['date'] for r in rows})[-1]
        group_of = {
            'Foreign_Investor': 'foreign',
            'Foreign_Dealer_Self': 'foreign',
            'Investment_Trust': 'trust',
            'Dealer_self': 'dealer',
            'Dealer_Hedging': 'dealer',
        }
        net = {'foreign': 0.0, 'trust': 0.0, 'dealer': 0.0}
        total_net: Optional[float] = None
        for r in rows:
            if r.get('date') != latest_date:
                continue
            delta = (r.get('buy') or 0) - (r.get('sell') or 0)
            if r.get('name') == 'total':
                total_net = delta
            group = group_of.get(r.get('name'))
            if group is not None:
                net[group] += delta
        if total_net is None:
            total_net = net['foreign'] + net['trust'] + net['dealer']

        yi = 1e8  # 元 -> 亿元
        return {
            'date': latest_date,
            'foreign_net': round(net['foreign'] / yi, 1),
            'trust_net': round(net['trust'] / yi, 1),
            'dealer_net': round(net['dealer'] / yi, 1),
            'total_net': round(total_net / yi, 1),
        }

    def get_tw_chip_summary(self, stock_code: str, days: int = 5) -> Optional[Dict[str, Any]]:
        """汇总台股筹码面数据，供 LLM 分析上下文使用。

        Returns:
            {
              'latest_date': 'YYYY-MM-DD',
              'institutional': {       # 单位：张（1000 股），正值为买超
                  'foreign_net_today', 'trust_net_today', 'dealer_net_today',
                  'foreign_net_nd', 'trust_net_nd', 'dealer_net_nd', 'days',
              },
              'margin': {              # 单位：张
                  'margin_balance', 'margin_change_today', 'margin_change_nd',
                  'short_balance', 'short_change_today', 'short_change_nd',
              },
              'foreign_holding_ratio': float,  # 外资持股比率（%）
            }
            三个子数据全部缺失时返回 None。
        """
        if not is_tw_stock_code(stock_code):
            return None

        from datetime import datetime, timedelta
        stock_id = to_finmind_stock_id(stock_code)
        # 取约 days 个交易日：日历天数放宽到 2 倍 + 假日缓冲
        start_date = (datetime.now() - timedelta(days=days * 2 + 6)).strftime('%Y-%m-%d')

        summary: Dict[str, Any] = {}

        # --- 三大法人买卖超 ---
        rows = self._fetch_dataset_rows('TaiwanStockInstitutionalInvestorsBuySell', stock_id, start_date)
        if rows:
            group_of = {
                'Foreign_Investor': 'foreign',
                'Foreign_Dealer_Self': 'foreign',
                'Investment_Trust': 'trust',
                'Dealer_self': 'dealer',
                'Dealer_Hedging': 'dealer',
            }
            dates = sorted({r['date'] for r in rows})[-days:]
            latest_date = dates[-1]
            net_nd = {'foreign': 0, 'trust': 0, 'dealer': 0}
            net_today = {'foreign': 0, 'trust': 0, 'dealer': 0}
            for r in rows:
                group = group_of.get(r.get('name'))
                if group is None or r['date'] not in dates:
                    continue
                net = (r.get('buy') or 0) - (r.get('sell') or 0)
                net_nd[group] += net
                if r['date'] == latest_date:
                    net_today[group] += net
            summary['latest_date'] = latest_date
            summary['institutional'] = {
                'days': len(dates),
                # 股 -> 张
                'foreign_net_today': round(net_today['foreign'] / 1000),
                'trust_net_today': round(net_today['trust'] / 1000),
                'dealer_net_today': round(net_today['dealer'] / 1000),
                'foreign_net_nd': round(net_nd['foreign'] / 1000),
                'trust_net_nd': round(net_nd['trust'] / 1000),
                'dealer_net_nd': round(net_nd['dealer'] / 1000),
            }

        # --- 融资融券（单位：张）---
        rows = self._fetch_dataset_rows('TaiwanStockMarginPurchaseShortSale', stock_id, start_date)
        if rows:
            rows = sorted(rows, key=lambda r: r['date'])[-days:]
            latest = rows[-1]
            margin_balance = latest.get('MarginPurchaseTodayBalance')
            short_balance = latest.get('ShortSaleTodayBalance')
            if margin_balance is not None:
                summary.setdefault('latest_date', latest['date'])
                summary['margin'] = {
                    'margin_balance': margin_balance,
                    'margin_change_today': margin_balance - (latest.get('MarginPurchaseYesterdayBalance') or margin_balance),
                    'margin_change_nd': margin_balance - (rows[0].get('MarginPurchaseYesterdayBalance') or margin_balance),
                    'short_balance': short_balance,
                    'short_change_today': (short_balance or 0) - (latest.get('ShortSaleYesterdayBalance') or short_balance or 0),
                    'short_change_nd': (short_balance or 0) - (rows[0].get('ShortSaleYesterdayBalance') or short_balance or 0),
                    'days': len(rows),
                }

        # --- 外资持股比率（%）---
        rows = self._fetch_dataset_rows('TaiwanStockShareholding', stock_id, start_date)
        if rows:
            latest = sorted(rows, key=lambda r: r['date'])[-1]
            ratio = latest.get('ForeignInvestmentSharesRatio')
            if ratio is not None:
                summary['foreign_holding_ratio'] = float(ratio)

        if not summary:
            logger.debug(f"[FinMind] {stock_id} 筹码面数据全部缺失")
            return None
        logger.info(f"[FinMind] {stock_id} 台股筹码面汇总完成: {sorted(summary.keys())}")
        return summary
