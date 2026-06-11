# -*- coding: utf-8 -*-
"""
台股（台灣證交所/櫃買中心）代碼判別與轉換工具

代碼格式約定（本 fork 的台灣友善預設）：
- 明確形式：``TW2330`` / ``tw2330`` / ``2330.TW`` / ``2330.TWO`` -> 台股
- 裸 4 位純數字（``2330``、``0050``）直接視為台股（A 股 6 位、港股 5 位，無衝突）
- 5 位純數字維持港股判定；台股 5 位 ETF（如 00878）與含字母代碼（如 00675L）
  必須帶 ``TW`` 前綴或 ``.TW``/``.TWO`` 後綴
- 內部 canonical 形式為 ``TW`` 前綴（``TW2330``），比照港股 ``HK00700`` 慣例

上市（TWSE -> yfinance ``.TW``）與上櫃（TPEX -> ``.TWO``）無法從代碼本身判斷，
由 YfinanceFetcher 先試 ``.TW`` 再試 ``.TWO``。
"""

import re
from typing import List, Optional

# TW 前綴後的本體：4-6 位數字，可帶最多兩位字母尾碼（槓桿 ETF 00675L、權證等）
_TW_BODY_RE = re.compile(r'^\d{4,6}[A-Z]{0,2}$')


def _extract_tw_body(code: str) -> Optional[str]:
    """從各種輸入形式抽出台股代碼本體（如 ``2330``、``00878``、``00675L``）。"""
    normalized = (code or "").strip().upper()
    if not normalized:
        return None

    # 後綴形式：2330.TW / 6488.TWO
    if normalized.endswith(".TWO"):
        body = normalized[:-4]
    elif normalized.endswith(".TW"):
        body = normalized[:-3]
    # 前綴形式：TW2330（排除 TWO/.TW 已處理後的純 TW 前綴）
    elif normalized.startswith("TW"):
        body = normalized[2:]
    # 裸 4 位純數字視為台股（A 股 6 位、港股 5 位）
    elif normalized.isdigit() and len(normalized) == 4:
        body = normalized
    else:
        return None

    if body and _TW_BODY_RE.match(body):
        return body
    return None


def is_tw_stock_code(code: str) -> bool:
    """判定是否為台股代碼（含 ETF）。"""
    return _extract_tw_body(code) is not None


def canonical_tw_code(code: str) -> Optional[str]:
    """轉為 canonical 形式 ``TW<本體>``（如 ``TW2330``）；非台股代碼回 None。"""
    body = _extract_tw_body(code)
    return f"TW{body}" if body else None


def to_finmind_stock_id(code: str) -> str:
    """轉為 FinMind 的 stock_id（純本體，如 ``2330``）。"""
    body = _extract_tw_body(code)
    if not body:
        raise ValueError(f"非台股代碼: {code}")
    return body


def to_yf_tw_symbols(code: str) -> List[str]:
    """轉為 yfinance 候選 symbol，依序嘗試上市 ``.TW`` 與上櫃 ``.TWO``。"""
    body = to_finmind_stock_id(code)
    return [f"{body}.TW", f"{body}.TWO"]
