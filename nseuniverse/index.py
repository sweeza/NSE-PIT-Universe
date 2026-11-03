"""
Index representation module for nseuniverse.
Allows querying synthetic index levels (Nifty 50, Nifty Bank, India VIX, etc.)
along with official valuation ratios (PE, PB, DivYield).
"""

from typing import Optional, Dict, Any, List
import pandas as pd
import numpy as np
from .data_source import resolve_file

_INDEX_TENSORS: Dict[str, pd.DataFrame] = {}


def _get_index_tensor(field: str) -> pd.DataFrame:
    global _INDEX_TENSORS
    f_clean = field.lower().strip()
    if f_clean not in _INDEX_TENSORS:
        path = resolve_file(f"index_tensors/{f_clean}.parquet")
        _INDEX_TENSORS[f_clean] = pd.read_parquet(path)
    return _INDEX_TENSORS[f_clean]


def normalize_index_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if s.startswith("^"):
        s = s[1:]
    if s in ("NSEI", "NIFTY", "NIFTY50", "NIFTY 50"):
        return "NIFTY 50"
    if s in ("NSEBANK", "BANKNIFTY", "NIFTYBANK", "NIFTY BANK"):
        return "NIFTY BANK"
    if s in ("CNXIT", "NIFTYIT", "NIFTY IT"):
        return "NIFTY IT"
    if s in ("NIFTYNEXT50", "NIFTY NEXT 50", "JUNIOR"):
        return "NIFTY NEXT 50"
    if s in ("NIFTY100", "NIFTY 100"):
        return "NIFTY 100"
    if s in ("NIFTY200", "NIFTY 200"):
        return "NIFTY 200"
    if s in ("NIFTY500", "NIFTY 500"):
        return "NIFTY 500"
    if s in ("VIX", "INDIAVIX", "INDIA VIX"):
        return "INDIA VIX"
    return s


class Index:
    """
    Representation of an official NSE Synthetic Index (NIFTY 50, NIFTY BANK, etc.)
    with time series for OHLCV and official exchange valuation ratios (PE, PB, DivYield).
    """

    def __init__(self, index_name: str):
        self.raw_name = index_name.strip()
        self.symbol = normalize_index_symbol(index_name)

        close_matrix = _get_index_tensor("close")
        if self.symbol not in close_matrix.columns:
            # Try fuzzy match
            matches = [c for c in close_matrix.columns if self.symbol in c]
            if matches:
                self.symbol = matches[0]
            else:
                available = sorted([c for c in close_matrix.columns if c.startswith("NIFTY")][:15])
                raise ValueError(
                    f"Index '{index_name}' (normalized: '{self.symbol}') not found. Sample valid indices: {available}"
                )

    def history(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        fields: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Fetches historical index time series.

        Parameters
        ----------
        start : str, optional
            Start date string (e.g. '2015-01-01').
        end : str, optional
            End date string (e.g. '2025-12-31').
        fields : list of str, optional
            Fields to return. Defaults to:
            ['open', 'high', 'low', 'close', 'volume', 'pe', 'pb', 'div_yield']

        Returns
        -------
        pd.DataFrame
            Index: DatetimeIndex
            Columns: Requested index fields.
        """
        if fields is None:
            fields = ["open", "high", "low", "close", "volume", "pe", "pb", "div_yield"]

        series_dict = {}
        for f in fields:
            f_clean = f.lower().strip()
            tensor = _get_index_tensor(f_clean)
            if self.symbol in tensor.columns:
                series_dict[f.capitalize()] = tensor[self.symbol]

        res = pd.DataFrame(series_dict).dropna(how="all")

        if start:
            res = res.loc[res.index >= pd.to_datetime(start)]
        if end:
            res = res.loc[res.index <= pd.to_datetime(end)]

        return res

    def __repr__(self) -> str:
        return f"<nseuniverse.Index: {self.symbol}>"
