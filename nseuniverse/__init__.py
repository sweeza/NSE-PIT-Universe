"""
nseuniverse: Institutional Point-in-Time Python Client for the Entire National Stock Exchange (NSE) Universe.

Inspired by yfinance, but engineered with zero survivorship bias, zero lookahead bias,
instant columnar parquets, exact exchange metrics, and point-in-time index memberships.
"""

from .ticker import Ticker
from .universe import (
    load,
    load_universe,
    get_security_master,
    get_corporate_actions,
    INDEX_NAMES,
    TENSOR_NAMES
)

__version__ = "1.0.0"
__author__ = "Institutional Quantitative Research"

# Convenience aliases
download = load

__all__ = [
    "Ticker",
    "load",
    "load_universe",
    "download",
    "get_security_master",
    "get_corporate_actions",
    "INDEX_NAMES",
    "TENSOR_NAMES",
    "__version__",
]
