"""
nseuniverse: Institutional Point-in-Time Python Client for the Entire National Stock Exchange (NSE) Universe.

Features:
- nse.Ticker("RELIANCE"): Per-instrument OHLCV, VWAP, Trades, Turnover, splits, bonuses, and metadata.
- nse.Index("NIFTY 50"): Official synthetic index levels, OHLCV, and valuation ratios (PE, PB, DivYield).
- nse.load("close", universe="nifty50"): Point-in-Time cross-sectional matrices with zero survivorship bias.
"""

from .ticker import Ticker
from .index import Index
from .universe import (
    load,
    load_universe,
    get_universe,
    get_canonical_dates,
    get_index_mask,
    invalidate_universe_cache,
    get_security_master,
    get_corporate_actions,
    get_dividends,
    get_dividend_matrix,
    compute_total_return_matrix,
    compute_dividend_yield_matrix,
    get_tradable_mask,
    get_tradable_universe_mask,
    get_holidays,
    is_trading_day,
    is_trading_holiday,
    get_trading_days,
    get_next_trading_day,
    get_prev_trading_day,
    INDEX_NAMES,
    TENSOR_NAMES
)

__version__ = "1.4.0"
__author__ = "Institutional Quantitative Research"

# Convenience aliases
download = load

__all__ = [
    "Ticker",
    "Index",
    "load",
    "load_universe",
    "get_universe",
    "get_canonical_dates",
    "get_index_mask",
    "invalidate_universe_cache",
    "download",
    "get_security_master",
    "get_corporate_actions",
    "get_dividends",
    "get_dividend_matrix",
    "compute_total_return_matrix",
    "compute_dividend_yield_matrix",
    "get_tradable_mask",
    "get_tradable_universe_mask",
    "get_holidays",
    "is_trading_day",
    "is_trading_holiday",
    "get_trading_days",
    "get_next_trading_day",
    "get_prev_trading_day",
    "INDEX_NAMES",
    "TENSOR_NAMES",
    "__version__",
]
