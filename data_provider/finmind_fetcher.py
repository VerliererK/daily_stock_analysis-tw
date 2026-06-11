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
