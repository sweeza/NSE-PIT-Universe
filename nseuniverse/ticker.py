"""
nseuniverse ticker module: Rich per-instrument interface matching and surpassing yfinance.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any
import numpy as np
import pandas as pd
from .data_source import (
    resolve_file,
    get_security_master_path,
    get_corporate_actions_path,
    get_dividends_path,
    get_tensor_path
)

_SEC_MASTER_DF: Optional[pd.DataFrame] = None
_CA_DF: Optional[pd.DataFrame] = None
_DIV_DF: Optional[pd.DataFrame] = None
_ALIAS_MAP: Optional[Dict[str, str]] = None


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


def _load_dividends() -> pd.DataFrame:
    global _DIV_DF
    if _DIV_DF is None:
        _DIV_DF = pd.read_parquet(get_dividends_path())
    return _DIV_DF


def _load_alias_map() -> Dict[str, str]:
    global _ALIAS_MAP
    if _ALIAS_MAP is None:
        try:
            alias_path = resolve_file("metadata/symbol_alias_map.json")
            if alias_path.exists():
                _ALIAS_MAP = json.loads(alias_path.read_text(encoding="utf-8"))
            else:
                _ALIAS_MAP = {}
        except Exception:
            _ALIAS_MAP = {}
    return _ALIAS_MAP


def _normalize_ticker(symbol_or_ticker: str) -> str:
    s = symbol_or_ticker.strip().upper()
    pure_sym = s.replace(".NS", "")
    aliases = _load_alias_map()
    if pure_sym in aliases:
        pure_sym = aliases[pure_sym]
    return f"{pure_sym}.NS"


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
            elif "sec_id" in self._sec_master.columns and (self._sec_master["sec_id"] == self.symbol).any():
                self.ticker = self._sec_master[self._sec_master["sec_id"] == self.symbol].index[0]
            elif "isin" in self._sec_master.columns and (self._sec_master["isin"] == self.symbol).any():
                self.ticker = self._sec_master[self._sec_master["isin"] == self.symbol].index[0]
            else:
                raise ValueError(
                    f"Ticker '{ticker}' (symbol: '{self.symbol}') not found in NSE Security Master ({len(self._sec_master):,} instruments)."
                )
            self.symbol = self.ticker.replace(".NS", "")

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
            "sec_id": self._meta.get("sec_id", None),
            "symbol": self.symbol,
            "ticker": self.ticker,
            "company_name": self._meta.get("company_name", ""),
            "asset_class": self._meta.get("asset_class", "EQUITY"),
            "sector": self._meta.get("sector", "Unclassified"),
            "series": self._meta.get("series", "EQ"),
            "isin": self._meta.get("isin", None),
            "listing_date": self._meta.get("listing_date", None),
            "first_traded_date": self._meta.get("first_traded_date", None),
            "last_traded_date": self._meta.get("last_traded_date", None),
            "face_value": self._meta.get("face_value", None),
            "is_active": bool(self._meta.get("is_active_currently", False)),
            "current_indices": indices,
        }

    @property
    def actions(self) -> pd.DataFrame:
        """Returns the complete corporate action history (splits, bonuses, and cash dividends)."""
        ca = _load_ca()
        div = _load_dividends()
        stock_ca = ca[ca["ticker"] == self.ticker].copy()
        stock_div = div[div["ticker"] == self.ticker].copy()

        parts = []
        if not stock_ca.empty:
            df_ca = stock_ca[["ex_date_dt", "action_type", "multiplier", "subject", "ex_date"]].copy()
            df_ca["amount"] = 0.0
            parts.append(df_ca)

        if not stock_div.empty:
            df_div = stock_div[["ex_date_dt", "dividend_type", "amount", "subject", "ex_date"]].copy()
            df_div.rename(columns={"dividend_type": "action_type"}, inplace=True)
            df_div["multiplier"] = 1.0
            parts.append(df_div)

        if not parts:
            return pd.DataFrame(columns=["action_type", "multiplier", "amount", "subject", "ex_date"])

        combined = pd.concat(parts, ignore_index=True)
        combined = combined.sort_values("ex_date_dt")
        combined.set_index("ex_date_dt", inplace=True)
        return combined[["action_type", "multiplier", "amount", "subject", "ex_date"]]

    @property
    def dividends(self) -> pd.Series:
        """Returns a Series of cash dividends per share indexed by ex-date."""
        div_df = _load_dividends()
        stock_div = div_df[div_df["ticker"] == self.ticker].copy()
        if stock_div.empty:
            return pd.Series(dtype=float, name="Dividends")
        stock_div = stock_div.sort_values("ex_date_dt")
        stock_div.set_index("ex_date_dt", inplace=True)
        s = stock_div["amount"].astype(float)
        s.name = "Dividends"
        return s

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
    def sec_id(self) -> Optional[str]:
        return self._meta.get("sec_id", None)

    @property
    def isin(self) -> Optional[str]:
        return self._meta.get("isin", None)

    @property
    def first_traded_date(self) -> Optional[str]:
        return self._meta.get("first_traded_date", None)

    @property
    def last_traded_date(self) -> Optional[str]:
        return self._meta.get("last_traded_date", None)

    @property
    def is_active(self) -> bool:
        return bool(self._meta.get("is_active_currently", False))

    def history(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        adjusted: Any = True,
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
        adjusted : bool or str, default True
            If True, backwards-adjusts prices for splits and bonuses and scales volumes.
            If 'tri' or 'total_return', computes the Total Return Index (compounding dividends).
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

        is_tri = isinstance(adjusted, str) and adjusted.lower().strip() in ("tri", "total_return")
        is_adj = bool(adjusted) or is_tri

        # Compute factor series for this ticker if adjusted
        factors = None
        if is_adj:
            stock_ca = ca_df[ca_df["ticker"] == self.ticker]

        for f in fields:
            f_clean = f.lower().strip()
            tensor_file = get_tensor_path(f_clean)
            df_col = pd.read_parquet(tensor_file, columns=[self.ticker])
            s = df_col[self.ticker]

            if factors is None and is_adj:
                dates = s.index
                f_arr = np.ones(len(dates), dtype=np.float64)
                if not stock_ca.empty:
                    grp_sorted = stock_ca.sort_values("ex_date_dt")
                    for _, row in grp_sorted.iterrows():
                        idx = dates.searchsorted(row["ex_date_dt"])
                        f_arr[:idx] *= row["multiplier"]
                factors = pd.Series(f_arr, index=dates)

            if is_adj:
                if f_clean in {"open", "high", "low", "close", "vwap", "last", "prevclose"}:
                    s = s / factors
                elif f_clean in {"volume", "tottrdqty"}:
                    s = s * factors

            if forward_fill:
                s = s.ffill()

            series_dict[f.capitalize()] = s

        res = pd.DataFrame(series_dict)
        res = res.dropna(how="all")

        if start:
            res = res.loc[res.index >= pd.to_datetime(start)]
        if end:
            res = res.loc[res.index <= pd.to_datetime(end)]

        # Total Return Index computation if adjusted='tri'
        if is_tri and "Close" in res.columns:
            s_p = res["Close"].dropna()
            if not s_p.empty:
                div_s = self.dividends
                div_aligned = pd.Series(0.0, index=s_p.index)
                if not div_s.empty:
                    for dt, amt in div_s.items():
                        if dt in div_aligned.index:
                            f = factors.loc[dt] if (factors is not None and dt in factors.index) else 1.0
                            div_aligned.loc[dt] += amt / f
                        elif len(s_p.index) > 0 and s_p.index[0] <= dt <= s_p.index[-1]:
                            idx = s_p.index.searchsorted(dt)
                            if idx < len(s_p.index):
                                eff_dt = s_p.index[idx]
                                f = factors.loc[eff_dt] if (factors is not None and eff_dt in factors.index) else 1.0
                                div_aligned.iloc[idx] += amt / f
                s_prev = s_p.shift(1)
                s_r = (s_p + div_aligned) / s_prev - 1.0
                s_r.iloc[0] = 0.0
                tri = s_p.iloc[0] * (1.0 + s_r).cumprod()
                res.loc[s_p.index, "Tri"] = tri
                res.loc[s_p.index, "Close"] = tri

        return res

    def __repr__(self) -> str:
        status = "Active" if self.is_active else "Delisted/Inactive"
        return f"<nseuniverse.Ticker: {self.ticker} ({self._meta.get('company_name', '')}) [{status}]>"
