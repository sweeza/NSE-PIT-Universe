"""
nseuniverse_io: Canonical Unified Loader Library for All NSE Instruments.

Features:
- Access to 12 Synchronous Market Data Tensors (open, high, low, close, volume, turnover,
  trades, vwap, last, prevclose, series, isin).
- Zero-Taint Invariant: Default forward_fill=False, adjusted=False returns pure exchange data.
- In-Memory Corporate Action Adjustment: Optional adjusted=True smoothly backwards-adjusts prices
  and forward-scales volumes for all stock splits and bonuses without altering raw disk parquets.
- In-Memory Forward-Fill: Optional forward_fill=True provides continuous backtesting price lines
  without mutating disk parquets.
- Universe Filtering:
    * Broad Market / Mcap: 'nifty50', 'niftynext50', 'nifty100', 'nifty200',
      'largemid250', 'midcap150', 'smallcap250', 'midsmall400', 'nifty500', 'totalmarket'
    * Official Sectoral: 'niftybank', 'niftyit', 'niftyauto', 'niftypharma',
      'niftyhealthcare', 'niftyfmcg', 'niftymetal', 'niftyenergy', 'niftyoilgas',
      'niftyfinance', 'niftyrealty', 'niftymedia', 'niftyconsumerdurables'
    * Master / All: 'master' or 'all'
- Asset Class Filtering:
    * 'EQUITY' (default when selecting indices), 'SME', 'ETF', 'MUTUAL_FUND', 'DEBT_INVIT_REIT'
- Sector / Industry Filtering:
    * Select any official NSE sector string (e.g. sector='Information Technology')
"""

from typing import Union, Iterable, List, Optional
import pandas as pd
import numpy as np
import config

_SEC_MASTER_CACHE: Optional[pd.DataFrame] = None
_CA_CACHE: Optional[pd.DataFrame] = None

PRICE_FIELDS = {"open", "high", "low", "close", "vwap", "last", "prevclose"}
VOLUME_FIELDS = {"volume", "tottrdqty"}


def get_security_master(reload: bool = False) -> pd.DataFrame:
    """Returns the comprehensive NSE Master Security Master."""
    global _SEC_MASTER_CACHE
    if _SEC_MASTER_CACHE is None or reload:
        if not config.SECURITY_MASTER_FILE.exists():
            raise FileNotFoundError(f"Security master {config.SECURITY_MASTER_FILE.name} not found.")
        _SEC_MASTER_CACHE = pd.read_parquet(config.SECURITY_MASTER_FILE)
    return _SEC_MASTER_CACHE


def get_corporate_actions(reload: bool = False) -> pd.DataFrame:
    """Returns the verified applied corporate actions table (splits & bonuses)."""
    global _CA_CACHE
    if _CA_CACHE is None or reload:
        ca_file = config.METADATA_DIR / "applied_corporate_actions.parquet"
        if not ca_file.exists():
            return pd.DataFrame()
        _CA_CACHE = pd.read_parquet(ca_file)
    return _CA_CACHE


def compute_adjustment_factors(
    dates: pd.DatetimeIndex,
    tickers: List[str],
    ca_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Computes vectorized cumulative backward adjustment factors for given dates and tickers.
    
    Formula for price at date t prior to ex_date with multiplier M:
        Adj_Factor(t) = Product_{ex_date > t}(Multiplier)
        Price_adj(t) = Price_raw(t) / Adj_Factor(t)
        Volume_adj(t) = Volume_raw(t) * Adj_Factor(t)
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


def load_tensor(
    name: str,
    universe: str = "master",
    asset_class: Optional[str] = None,
    sector: Optional[str] = None,
    forward_fill: bool = False,
    adjusted: bool = False,
) -> pd.DataFrame:
    """
    Loads a single market data tensor or metadata DataFrame by name.

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
    forward_fill : bool, default False
        If True, applies bounded forward filling in-memory for backtesting engines.
        Disk parquets remain 100% pure.
    adjusted : bool, default False
        If True, dynamically applies in-memory split and bonus adjustments to price tensors
        (dividing by cumulative multiplier) and volume tensors (multiplying by cumulative multiplier).
        Disk parquets remain 100% pure raw unadjusted base data.

    Returns
    -------
    pd.DataFrame
    """
    key = name.lower().strip()

    if key in ("security_master", "sec_master"):
        return get_security_master()
    if key in ("corporate_actions", "ca"):
        return get_corporate_actions()

    if key not in config.TENSOR_FILES:
        raise ValueError(f"Unknown tensor '{name}'. Choose from: {list(config.TENSOR_FILES.keys())}")

    tensor_path = config.TENSOR_FILES[key]
    if not tensor_path.exists():
        raise FileNotFoundError(f"Tensor file '{tensor_path.name}' does not exist.")

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
        if univ_key in config.PIT_INDEX_FILES:
            mask_path = config.PIT_INDEX_FILES[univ_key]
            if mask_path.exists():
                mask = pd.read_parquet(mask_path)
                # Align dates and tickers
                common_dates = df.index.intersection(mask.index)
                common_cols = df.columns.intersection(mask.columns)
                
                # Zero out days where constituent is False (replace with NaN)
                active_mask = mask.loc[common_dates, common_cols]
                # Filter to columns that were ever active in the universe
                ever_active = common_cols[active_mask.any(axis=0)]
                
                df = df.loc[common_dates, ever_active].where(active_mask[ever_active], np.nan)
        else:
            raise ValueError(f"Unknown universe '{universe}'. Supported: {list(config.PIT_INDEX_FILES.keys())} or 'master'")

    # 4. Optional In-Memory Dynamic Corporate Action Adjustment (Splits & Bonuses)
    if adjusted:
        if key in PRICE_FIELDS:
            factors = compute_adjustment_factors(df.index, df.columns.tolist())
            df = df / factors
        elif key in VOLUME_FIELDS:
            factors = compute_adjustment_factors(df.index, df.columns.tolist())
            df = df * factors

    # 5. Optional In-Memory Forward-Fill for Backtest Engines
    if forward_fill:
        df = df.ffill()

    return df


def load_universe(
    fields: Optional[List[str]] = None,
    universe: str = "master",
    asset_class: Optional[str] = None,
    sector: Optional[str] = None,
    forward_fill: bool = False,
    adjusted: bool = False,
) -> dict:
    """
    Loads multiple tensors into a dictionary of DataFrames aligned to the same universe.
    """
    if fields is None:
        fields = ["open", "high", "low", "close", "volume", "vwap"]

    return {
        f: load_tensor(
            f,
            universe=universe,
            asset_class=asset_class,
            sector=sector,
            forward_fill=forward_fill,
            adjusted=adjusted,
        )
        for f in fields
    }
