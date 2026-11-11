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
import json
import pandas as pd
import numpy as np
import config
from exchange_calendar import (
    get_holidays,
    get_holiday_dates,
    is_trading_holiday,
    is_special_trading_session,
    is_trading_day,
    get_trading_days,
    get_candidate_sessions,
    get_next_trading_day,
    get_prev_trading_day,
)

_SEC_MASTER_CACHE: Optional[pd.DataFrame] = None
_CA_CACHE: Optional[pd.DataFrame] = None
_DIVIDENDS_CACHE: Optional[pd.DataFrame] = None
_ALIAS_CACHE: Optional[dict] = None

PRICE_FIELDS = {"open", "high", "low", "close", "vwap", "last", "prevclose"}
VOLUME_FIELDS = {"volume", "tottrdqty"}


def get_alias_map() -> dict:
    """Returns the dictionary mapping historical/obsolete symbols to canonical symbols."""
    global _ALIAS_CACHE
    if _ALIAS_CACHE is None:
        alias_file = config.METADATA_DIR / "symbol_alias_map.json"
        _ALIAS_CACHE = json.loads(alias_file.read_text()) if alias_file.exists() else {}
    return _ALIAS_CACHE


def resolve_ticker(symbol_or_ticker: str) -> str:
    """Resolves any historical or current NSE symbol/ticker/sec_id/ISIN to its canonical .NS ticker."""
    s = str(symbol_or_ticker).upper().strip().replace(".NS", "")
    aliases = get_alias_map()
    if s in aliases:
        return f"{aliases[s]}.NS"

    # Support sec_id or ISIN lookup if sec_master is available
    if (s.startswith("NSE") and len(s) == 7) or (s.startswith("IN") and len(s) == 12):
        try:
            sm = get_security_master()
            if "sec_id" in sm.columns and (sm["sec_id"] == s).any():
                return str(sm[sm["sec_id"] == s].index[0])
            if "isin" in sm.columns and (sm["isin"] == s).any():
                return str(sm[sm["isin"] == s].index[0])
        except Exception:
            pass

    return f"{s}.NS"


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
        ca_file = config.CORPORATE_ACTIONS_FILE
        if not ca_file.exists():
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


def get_dividends(reload: bool = False) -> pd.DataFrame:
    """Returns the comprehensive Point-in-Time dividend ledger (1995-2026)."""
    global _DIVIDENDS_CACHE
    if _DIVIDENDS_CACHE is None or reload:
        div_file = config.DIVIDENDS_FILE
        if not div_file.exists():
            div_file = config.METADATA_DIR / "dividends.parquet"
        if not div_file.exists():
            return pd.DataFrame()
        _DIVIDENDS_CACHE = pd.read_parquet(div_file)
    return _DIVIDENDS_CACHE


def get_dividend_matrix(
    dates: pd.DatetimeIndex,
    tickers: List[str],
    adjusted: bool = True,
    div_df: Optional[pd.DataFrame] = None,
    ca_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Constructs a synchronous (Dates x Tickers) matrix of cash dividends paid per share.

    Parameters
    ----------
    dates : pd.DatetimeIndex
        Aligned trading session dates.
    tickers : List[str]
        List of canonical .NS tickers.
    adjusted : bool, default True
        If True, cash dividends are backwards split-adjusted (divided by the cumulative split
        multiplier) so that D_adj(t) / Price_adj(t) accurately reflects the authentic yield.
    div_df : pd.DataFrame, optional
        Preloaded dividends table; defaults to get_dividends().
    ca_df : pd.DataFrame, optional
        Preloaded corporate actions table; defaults to get_corporate_actions().

    Returns
    -------
    pd.DataFrame
        Dates x Tickers matrix of cash dividends (0.0 on sessions without dividends).
    """
    if div_df is None:
        div_df = get_dividends()

    div_mat = pd.DataFrame(0.0, index=dates, columns=tickers, dtype=np.float64)
    if div_df.empty:
        return div_mat

    sub_div = div_df[div_df["ticker"].isin(tickers)]
    if sub_div.empty:
        return div_mat

    date_indexer = pd.Series(np.arange(len(dates)), index=dates)
    col_map = {col: i for i, col in enumerate(tickers)}

    for t, grp in sub_div.groupby("ticker"):
        if t in col_map:
            col_idx = col_map[t]
            for _, row in grp.iterrows():
                dt = row["ex_date_dt"]
                amt = float(row["amount"])
                if dt in date_indexer:
                    div_mat.iat[date_indexer[dt], col_idx] += amt
                elif len(dates) > 0 and dates[0] <= dt <= dates[-1]:
                    idx = dates.searchsorted(dt)
                    if idx < len(dates):
                        div_mat.iat[idx, col_idx] += amt

    if adjusted:
        factors = compute_adjustment_factors(dates, tickers, ca_df=ca_df)
        div_mat = div_mat / factors

    return div_mat


def compute_total_return_matrix(
    close_df: pd.DataFrame,
    dividends_df: Optional[pd.DataFrame] = None,
    ca_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Vectorized computation of Total Return Index (TRI) matrix across (Dates x Tickers).

    Compounds split/bonus-adjusted prices alongside reinvested cash dividends:
        R_tri(t) = (Price_adj(t) + Div_adj(t)) / Price_adj(t-1) - 1
        TRI(t) = Price_adj(0) * Product_{tau=1..t} (1 + R_tri(tau))

    Preserves dimensional parity, listing gatekeeper, and natural sparsity.
    """
    dates = close_df.index
    tickers = close_df.columns.tolist()

    div_adj = get_dividend_matrix(dates, tickers, adjusted=True, div_df=dividends_df, ca_df=ca_df)
    tri_mat = pd.DataFrame(np.nan, index=dates, columns=close_df.columns, dtype=np.float64)

    for t in close_df.columns:
        s_p = close_df[t].dropna()
        if s_p.empty or len(s_p) < 2:
            if not s_p.empty:
                tri_mat.loc[s_p.index, t] = s_p.values
            continue
        s_d = div_adj[t].reindex(s_p.index, fill_value=0.0)
        s_prev = s_p.shift(1)
        s_r = (s_p + s_d) / s_prev - 1.0
        s_r.iloc[0] = 0.0
        tri_mat.loc[s_p.index, t] = s_p.iloc[0] * (1.0 + s_r).cumprod()

    return tri_mat


def compute_total_return_series(
    close_series: pd.Series,
    ticker: str,
    dividends_df: Optional[pd.DataFrame] = None,
    ca_df: Optional[pd.DataFrame] = None,
) -> pd.Series:
    """
    Computes Total Return Index (TRI) series for a single ticker.
    """
    s_p = close_series.dropna()
    if s_p.empty:
        return pd.Series(dtype=np.float64, index=close_series.index)

    dates = s_p.index
    canonical = resolve_ticker(ticker)
    div_mat = get_dividend_matrix(dates, [canonical], adjusted=True, div_df=dividends_df, ca_df=ca_df)
    s_d = div_mat[canonical]
    s_prev = s_p.shift(1)
    s_r = (s_p + s_d) / s_prev - 1.0
    s_r.iloc[0] = 0.0
    tri = s_p.iloc[0] * (1.0 + s_r).cumprod()
    return tri.reindex(close_series.index)


def compute_dividend_yield_matrix(
    close_df: pd.DataFrame,
    window: int = 252,
    dividends_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Computes trailing 12-month (window sessions) dividend yield matrix (Dates x Tickers):
        Div_Yield(t) = Sum_{tau in [t-window, t]} Div_raw(tau) / Close_raw(t)
    """
    dates = close_df.index
    tickers = close_df.columns.tolist()

    div_raw = get_dividend_matrix(dates, tickers, adjusted=False, div_df=dividends_df)
    trail_div = div_raw.rolling(window=window, min_periods=1).sum()

    # Avoid zero division
    div_yield = trail_div.where(close_df > 0, np.nan) / close_df
    return div_yield


def load_tensor(
    name: str,
    universe: str = "master",
    asset_class: Optional[str] = None,
    sector: Optional[str] = None,
    forward_fill: bool = False,
    adjusted: Union[bool, str] = False,
) -> pd.DataFrame:
    """
    Loads a single market data tensor or metadata DataFrame by name.

    Parameters
    ----------
    name : str
        Tensor name: 'open', 'high', 'low', 'close', 'volume', 'turnover',
        'trades', 'vwap', 'last', 'prevclose', 'series', 'isin'.
        Metadata shortcuts: 'security_master', 'ca', 'corporate_actions', 'dividends'.
        Synthetic / Analytical series: 'tri' (Total Return Index), 'dividend_yield'.
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
    adjusted : bool or str, default False
        If True, dynamically applies in-memory split and bonus adjustments to price tensors
        (dividing by cumulative multiplier) and volume tensors (multiplying by cumulative multiplier).
        If 'tri' or 'total_return', computes the continuous Total Return Index (compounding reinvested dividends).
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
    if key in ("dividends_ledger", "dividend_ledger", "div_ledger"):
        return get_dividends()
    if key in ("dividends", "dividend", "div"):
        base_close = load_tensor("close", universe=universe, asset_class=asset_class, sector=sector)
        return get_dividend_matrix(base_close.index, base_close.columns.tolist(), adjusted=bool(adjusted))
    if key in ("tri", "total_return"):
        adj_close = load_tensor("close", universe=universe, asset_class=asset_class, sector=sector, adjusted=True, forward_fill=forward_fill)
        return compute_total_return_matrix(adj_close)
    if key in ("dividend_yield", "div_yield"):
        raw_close = load_tensor("close", universe=universe, asset_class=asset_class, sector=sector, adjusted=False, forward_fill=forward_fill)
        return compute_dividend_yield_matrix(raw_close)

    if key not in config.TENSOR_FILES:
        raise ValueError(f"Unknown tensor '{name}'. Choose from: {list(config.TENSOR_FILES.keys())} or shortcuts ['tri', 'dividends', 'dividend_yield']")

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

    # 4. Optional In-Memory Dynamic Corporate Action Adjustment (Splits, Bonuses, TRI)
    is_tri = isinstance(adjusted, str) and adjusted.lower().strip() in ("tri", "total_return")
    if is_tri:
        if key in PRICE_FIELDS:
            factors = compute_adjustment_factors(df.index, df.columns.tolist())
            adj_p = df / factors
            df = compute_total_return_matrix(adj_p)
    elif adjusted:
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
    adjusted: Union[bool, str] = False,
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


def get_tradable_mask(
    universe: str = "nifty500",
    min_adtv: float = 20_000_000.0,
    adtv_window: int = 20,
    min_price: float = 20.0,
    max_price: Optional[float] = 50_000.0,
    asset_class: str = "EQUITY",
    sector: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """
    Constructs a dynamic Point-in-Time tradable universe boolean mask (Dates x Tickers).
    Enforces investability, minimum liquidity corridors (ADTV), price corridors,
    and asset class filtering.

    Parameters
    ----------
    universe : str, default 'nifty500'
        Index or universe selector ('nifty500', 'midsmall400', 'nifty200', 'nifty100',
        'nifty50', 'largemid250', 'midcap150', 'smallcap250', 'totalmarket', 'master',
        or sectoral indices like 'niftybank', 'niftyit', etc.).
    min_adtv : float, default 20_000_000.0 (₹2.0 Crore)
        Minimum rolling Average Daily Traded Value (Turnover) floor. Set to 0 to disable.
    adtv_window : int, default 20
        Rolling window in trading days for ADTV calculation.
    min_price : float, default 20.0 (₹20)
        Minimum share price floor (eliminates penny stocks, CIRP/insolvency traps).
    max_price : float, optional, default 50_000.0 (₹50,000)
        Maximum share price cap (avoids lot-size distortion / tick anomalies).
    asset_class : str, default 'EQUITY'
        Filter by asset class ('EQUITY', 'SME', 'ETF', 'MUTUAL_FUND', 'DEBT_INVIT_REIT').
    sector : str, optional
        Filter by official NSE sector/industry name.
    start : str, optional
        Start date filter (e.g. '2015-01-01').
    end : str, optional
        End date filter (e.g. '2025-12-31').

    Returns
    -------
    pd.DataFrame
        Boolean DataFrame of shape (Dates x Tickers) where True indicates
        an eligible, tradable instrument on that session.
    """
    # 1. Load unadjusted nominal Close price and Turnover across master panel (full history for rolling lookback)
    close_master = load_tensor(
        "close",
        universe="master",
        asset_class=asset_class,
        sector=sector,
        adjusted=False,
    )
    turnover_master = load_tensor(
        "turnover",
        universe="master",
        asset_class=asset_class,
        sector=sector,
        adjusted=False,
    )

    # 2. Base active eligibility (valid trading session)
    mask = close_master.notna() & (close_master > 0)

    # 3. Apply price corridors
    if min_price is not None and min_price > 0:
        mask = mask & (close_master >= min_price)
    if max_price is not None and max_price > 0:
        mask = mask & (close_master <= max_price)

    # 4. Apply rolling liquidity / ADTV corridor on full exchange trading history
    if min_adtv is not None and min_adtv > 0:
        adtv = turnover_master.rolling(window=adtv_window, min_periods=max(1, adtv_window // 2)).mean()
        mask = mask & (adtv >= min_adtv)

    # 5. Apply Point-in-Time Index Universe Mask if not master
    univ_key = universe.lower().strip()
    if univ_key not in ("master", "all"):
        if univ_key in config.PIT_INDEX_FILES:
            mask_path = config.PIT_INDEX_FILES[univ_key]
            index_mask = pd.read_parquet(mask_path)
            common_dates = mask.index.intersection(index_mask.index)
            common_cols = mask.columns.intersection(index_mask.columns)
            active_idx = index_mask.loc[common_dates, common_cols]
            ever_active = common_cols[active_idx.any(axis=0)]
            mask = mask.loc[common_dates, ever_active] & active_idx[ever_active]
        else:
            raise ValueError(f"Unknown universe '{universe}'. Supported: {list(config.PIT_INDEX_FILES.keys())} or 'master'")

    # 6. Slice date range after rolling computation
    if start:
        mask = mask.loc[mask.index >= pd.to_datetime(start)]
    if end:
        mask = mask.loc[mask.index <= pd.to_datetime(end)]

    return mask.astype(bool)


get_tradable_universe_mask = get_tradable_mask


def get_canonical_dates(reload: bool = False) -> pd.DatetimeIndex:
    """Returns the ordered DatetimeIndex of all historical trading sessions in tensors."""
    from nseuniverse.universe import get_canonical_dates as _core_get_canonical_dates
    return _core_get_canonical_dates(reload=reload)


def invalidate_universe_cache() -> None:
    """Clears all cached in-memory index masks, canonical date indices, and metadata caches."""
    from nseuniverse.universe import invalidate_universe_cache as _core_invalidate
    _core_invalidate()


def get_universe(
    as_of_date: Union[str, pd.Timestamp],
    universe: str = "nifty500",
    min_adtv: Optional[float] = None,
    adtv_window: int = 20,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    asset_class: Optional[str] = None,
    sector: Optional[str] = None,
    require_traded: bool = False,
    include_metrics: bool = True,
    fields: Optional[List[str]] = None,
    as_list: bool = False,
) -> Union[pd.DataFrame, List[str]]:
    """
    Constructs an authentic Point-in-Time constituent universe snapshot and trading metrics
    as of any historical date with zero look-ahead bias and zero survivorship bias.
    """
    from nseuniverse.universe import get_universe as _core_get_universe
    return _core_get_universe(
        as_of_date=as_of_date,
        universe=universe,
        min_adtv=min_adtv,
        adtv_window=adtv_window,
        min_price=min_price,
        max_price=max_price,
        asset_class=asset_class,
        sector=sector,
        require_traded=require_traded,
        include_metrics=include_metrics,
        fields=fields,
        as_list=as_list,
    )


