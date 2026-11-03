"""
nseuniverse ticker module: Rich per-instrument interface matching and surpassing yfinance.
"""

from typing import Optional, Dict, Any
import numpy as np
import pandas as pd
from .data_source import (
    resolve_file,
    get_security_master_path,
    get_corporate_actions_path,
    get_tensor_path
)

_SEC_MASTER_DF: Optional[pd.DataFrame] = None
_CA_DF: Optional[pd.DataFrame] = None


def _load_sec_master() -> pd.DataFrame:
    global _SEC_MASTER_DF
    if _SEC_MASTER_DF is None:
        _SEC_MASTER_DF = pd.read_parquet(get_security_master_path())
    return _SEC_MASTER_DF


def _load_ca() -> pd.DataFrame:
    global _CA_DF
    if _CA_DF is None:
        _CA_DF = pd.read_parquet(get_corporate_actions_path())
    return _CA_DF


def _normalize_ticker(symbol_or_ticker: str) -> str:
    s = symbol_or_ticker.strip().upper()
    if not s.endswith(".NS"):
        s = f"{s}.NS"
    return s


class Ticker:
    """
    Representation of an individual NSE instrument (Equity, SME, ETF, etc.)
    with methods closely modeled after yfinance.Ticker, enhanced with
    institutional point-in-time attributes and exact exchange metrics.
    """

    def __init__(self, ticker: str):
        self.ticker = _normalize_ticker(ticker)
        self.symbol = self.ticker.replace(".NS", "")
        self._sec_master = _load_sec_master()

        if self.ticker not in self._sec_master.index:
            # Try finding by pure symbol
            match = self._sec_master[self._sec_master["symbol"] == self.symbol]
            if not match.empty:
                self.ticker = match.index[0]
            else:
                raise ValueError(
                    f"Ticker '{ticker}' (symbol: '{self.symbol}') not found in NSE Security Master (6,089 instruments)."
                )

        self._meta = self._sec_master.loc[self.ticker]

    @property
    def info(self) -> Dict[str, Any]:
        """Returns comprehensive instrument metadata dictionary."""
        indices = [
            col.replace("in_", "")
            for col in self._meta.index
            if col.startswith("in_") and bool(self._meta[col])
        ]
        return {
            "symbol": self.symbol,
            "ticker": self.ticker,
            "company_name": self._meta.get("company_name", ""),
            "asset_class": self._meta.get("asset_class", "EQUITY"),
            "sector": self._meta.get("sector", "Unclassified"),
            "series": self._meta.get("series", "EQ"),
            "isin": self._meta.get("isin", None),
            "listing_date": self._meta.get("listing_date", None),
            "face_value": self._meta.get("face_value", None),
            "is_active": bool(self._meta.get("is_active_currently", False)),
            "current_indices": indices,
        }

    @property
    def actions(self) -> pd.DataFrame:
        """Returns the complete corporate action history (splits and bonuses) for this instrument."""
        ca = _load_ca()
        stock_ca = ca[ca["ticker"] == self.ticker].copy()
        if stock_ca.empty:
            return pd.DataFrame(columns=["action_type", "multiplier", "subject", "ex_date", "ex_date_dt"])
        stock_ca = stock_ca.sort_values("ex_date_dt")
        stock_ca.set_index("ex_date_dt", inplace=True)
        return stock_ca[["action_type", "multiplier", "subject", "ex_date"]]

    @property
    def splits(self) -> pd.Series:
        """Returns a Series of split multipliers indexed by ex-date."""
        act = self.actions
        if act.empty:
            return pd.Series(dtype=float)
        splits_df = act[act["action_type"].str.contains("SPLIT", na=False)]
        return splits_df["multiplier"]

    @property
    def bonuses(self) -> pd.Series:
        """Returns a Series of bonus multipliers indexed by ex-date."""
        act = self.actions
        if act.empty:
            return pd.Series(dtype=float)
        bonus_df = act[act["action_type"].str.contains("BONUS", na=False)]
        return bonus_df["multiplier"]

    @property
    def isin(self) -> Optional[str]:
        return self._meta.get("isin", None)

    @property
    def is_active(self) -> bool:
        return bool(self._meta.get("is_active_currently", False))

    def history(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        adjusted: bool = True,
        forward_fill: bool = False,
        fields: Optional[list] = None,
    ) -> pd.DataFrame:
        """
        Fetches historical price, volume, and trade data for this ticker.

        Parameters
        ----------
        start : str, optional
            Start date string (e.g. '2015-01-01').
        end : str, optional
            End date string (e.g. '2025-12-31').
        adjusted : bool, default True
            If True, backwards-adjusts prices for splits and bonuses and scales volumes.
        forward_fill : bool, default False
            If True, forward fills non-trading days in-memory.
        fields : list of str, optional
            List of fields to return. Defaults to:
            ['open', 'high', 'low', 'close', 'volume', 'vwap', 'turnover', 'trades']

        Returns
        -------
        pd.DataFrame
            Index: DatetimeIndex
            Columns: Requested market fields (Capitalized or lowercase matching fields).
        """
        if fields is None:
            fields = ["open", "high", "low", "close", "volume", "vwap", "turnover", "trades"]

        series_dict = {}
        ca_df = _load_ca()

        # Compute factor series for this ticker if adjusted
        factors = None
        if adjusted:
            stock_ca = ca_df[ca_df["ticker"] == self.ticker]

        for f in fields:
            f_clean = f.lower().strip()
            tensor_file = get_tensor_path(f_clean)
            # Read single column from tensor
            df_col = pd.read_parquet(tensor_file, columns=[self.ticker])
            s = df_col[self.ticker]

            if factors is None and adjusted:
                # Precompute factors aligned with date index
                dates = s.index
                f_arr = np.ones(len(dates), dtype=np.float64)
                if not stock_ca.empty:
                    grp_sorted = stock_ca.sort_values("ex_date_dt")
                    for _, row in grp_sorted.iterrows():
                        idx = dates.searchsorted(row["ex_date_dt"])
                        f_arr[:idx] *= row["multiplier"]
                factors = pd.Series(f_arr, index=dates)

            if adjusted:
                if f_clean in {"open", "high", "low", "close", "vwap", "last", "prevclose"}:
                    s = s / factors
                elif f_clean in {"volume", "tottrdqty"}:
                    s = s * factors

            if forward_fill:
                s = s.ffill()

            series_dict[f.capitalize()] = s

        res = pd.DataFrame(series_dict)
        # Drop rows where ticker was not listed / all NaN
        res = res.dropna(how="all")

        if start:
            res = res.loc[res.index >= pd.to_datetime(start)]
        if end:
            res = res.loc[res.index <= pd.to_datetime(end)]

        return res

    def __repr__(self) -> str:
        status = "Active" if self.is_active else "Delisted/Inactive"
        return f"<nseuniverse.Ticker: {self.ticker} ({self._meta.get('company_name', '')}) [{status}]>"
