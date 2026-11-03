"""
Core universe and tensor loading functionality for nseuniverse.
"""

from typing import Union, Iterable, List, Optional, Dict
import pandas as pd
import numpy as np
from .data_source import (
    get_security_master_path,
    get_corporate_actions_path,
    get_tensor_path,
    get_index_path,
    INDEX_NAMES,
    TENSOR_NAMES
)

_SEC_MASTER_CACHE: Optional[pd.DataFrame] = None
_CA_CACHE: Optional[pd.DataFrame] = None

PRICE_FIELDS = {"open", "high", "low", "close", "vwap", "last", "prevclose"}
VOLUME_FIELDS = {"volume", "tottrdqty"}


def get_security_master(reload: bool = False) -> pd.DataFrame:
    """Returns the comprehensive NSE Master Security Master (6,089 instruments)."""
    global _SEC_MASTER_CACHE
    if _SEC_MASTER_CACHE is None or reload:
        _SEC_MASTER_CACHE = pd.read_parquet(get_security_master_path())
    return _SEC_MASTER_CACHE


def get_corporate_actions(reload: bool = False) -> pd.DataFrame:
    """Returns the verified applied corporate actions ledger (splits & bonuses)."""
    global _CA_CACHE
    if _CA_CACHE is None or reload:
        _CA_CACHE = pd.read_parquet(get_corporate_actions_path())
    return _CA_CACHE


def compute_adjustment_factors(
    dates: pd.DatetimeIndex,
    tickers: List[str],
    ca_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Computes vectorized cumulative backward adjustment factors for given dates and tickers.
    """
    if ca_df is None:
        ca_df = get_corporate_actions()

    if ca_df.empty:
        return pd.DataFrame(1.0, index=dates, columns=tickers, dtype=np.float64)

    sub_ca = ca_df[ca_df["ticker"].isin(tickers)]
    if sub_ca.empty:
        return pd.DataFrame(1.0, index=dates, columns=tickers, dtype=np.float64)

    ca_grouped = sub_ca.groupby("ticker")
    factors_dict = {}

    for ticker, grp in ca_grouped:
        grp_sorted = grp.sort_values("ex_date_dt")
        f = np.ones(len(dates), dtype=np.float64)
        for _, row in grp_sorted.iterrows():
            idx = dates.searchsorted(row["ex_date_dt"])
            f[:idx] *= row["multiplier"]
        factors_dict[ticker] = f

    return pd.DataFrame(factors_dict, index=dates).reindex(columns=tickers, fill_value=1.0)


def load(
    name: str,
    universe: str = "master",
    asset_class: Optional[str] = None,
    sector: Optional[str] = None,
    adjusted: bool = True,
    forward_fill: bool = False,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """
    Loads a market data tensor (matrix of Date x Tickers) with Point-in-Time universe filtering,
    optional split/bonus backward adjustment, and forward-fill.

    Parameters
    ----------
    name : str
        Tensor name: 'open', 'high', 'low', 'close', 'volume', 'turnover',
        'trades', 'vwap', 'last', 'prevclose', 'series', 'isin'.
        Metadata shortcuts: 'security_master', 'ca', 'corporate_actions'.
    universe : str, default 'master'
        - 'master' / 'all': Full panel of 6,089 tickers.
        - Broad market indices: 'nifty50', 'niftynext50', 'nifty100', 'nifty200',
          'largemid250', 'midcap150', 'smallcap250', 'midsmall400', 'nifty500', 'totalmarket'
        - Official sectoral: 'niftybank', 'niftyit', 'niftyauto', 'niftypharma',
          'niftyhealthcare', 'niftyfmcg', 'niftymetal', 'niftyenergy', 'niftyoilgas',
          'niftyfinance', 'niftyrealty', 'niftymedia', 'niftyconsumerdurables'
    asset_class : str, optional
        Filter by asset class: 'EQUITY', 'SME', 'ETF', 'MUTUAL_FUND', 'DEBT_INVIT_REIT'.
    sector : str, optional
        Filter by official NSE sector/industry name (e.g. 'Information Technology', 'Financial Services').
    adjusted : bool, default True
        If True, dynamically applies in-memory split and bonus adjustments to prices
        (dividing by cumulative multiplier) and volumes (multiplying by cumulative multiplier).
        Raw parquets remain 100% untainted.
    forward_fill : bool, default False
        If True, applies bounded forward filling in-memory for backtesting engines.
    start : str, optional
        Start date (e.g. '2015-01-01').
    end : str, optional
        End date (e.g. '2025-12-31').

    Returns
    -------
    pd.DataFrame
        Dates as DatetimeIndex, Tickers as Columns.
    """
    key = name.lower().strip()

    if key in ("security_master", "sec_master"):
        return get_security_master()
    if key in ("corporate_actions", "ca"):
        return get_corporate_actions()

    tensor_path = get_tensor_path(key)
    df = pd.read_parquet(tensor_path)
    sec_master = get_security_master()

    # 1. Filter by Asset Class if specified
    if asset_class:
        ac_key = asset_class.upper().strip()
        matching_tickers = sec_master[sec_master["asset_class"] == ac_key].index
        cols = [c for c in df.columns if c in matching_tickers]
        df = df[cols]

    # 2. Filter by Sector if specified
    if sector:
        sec_key = sector.strip()
        matching_tickers = sec_master[sec_master["sector"].str.contains(sec_key, case=False, na=False)].index
        cols = [c for c in df.columns if c in matching_tickers]
        df = df[cols]

    # 3. Apply Point-in-Time Index Universe Mask if not master
    univ_key = universe.lower().strip()
    if univ_key not in ("master", "all"):
        if univ_key in INDEX_NAMES:
            mask_path = get_index_path(univ_key)
            mask = pd.read_parquet(mask_path)
            common_dates = df.index.intersection(mask.index)
            common_cols = df.columns.intersection(mask.columns)
            active_mask = mask.loc[common_dates, common_cols]
            ever_active = common_cols[active_mask.any(axis=0)]
            df = df.loc[common_dates, ever_active].where(active_mask[ever_active], np.nan)
        else:
            raise ValueError(f"Unknown universe '{universe}'. Supported: {INDEX_NAMES} or 'master'")

    # 4. In-Memory Corporate Action Adjustment (Splits & Bonuses)
    if adjusted:
        if key in PRICE_FIELDS:
            factors = compute_adjustment_factors(df.index, df.columns.tolist())
            df = df / factors
        elif key in VOLUME_FIELDS:
            factors = compute_adjustment_factors(df.index, df.columns.tolist())
            df = df * factors

    # 5. Optional In-Memory Forward-Fill
    if forward_fill:
        df = df.ffill()

    # 6. Date filtering
    if start:
        df = df.loc[df.index >= pd.to_datetime(start)]
    if end:
        df = df.loc[df.index <= pd.to_datetime(end)]

    return df


def load_universe(
    fields: Optional[List[str]] = None,
    universe: str = "master",
    asset_class: Optional[str] = None,
    sector: Optional[str] = None,
    adjusted: bool = True,
    forward_fill: bool = False,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Loads multiple tensors into a dictionary of DataFrames aligned to the same universe.
    """
    if fields is None:
        fields = ["open", "high", "low", "close", "volume", "vwap"]

    return {
        f: load(
            f,
            universe=universe,
            asset_class=asset_class,
            sector=sector,
            adjusted=adjusted,
            forward_fill=forward_fill,
            start=start,
            end=end,
        )
        for f in fields
    }
