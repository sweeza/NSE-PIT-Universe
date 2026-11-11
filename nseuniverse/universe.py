"""
Core universe and tensor loading functionality for nseuniverse.
"""

from typing import Union, Iterable, List, Optional, Dict
import datetime
import pandas as pd
import numpy as np
from .data_source import (
    get_security_master_path,
    get_corporate_actions_path,
    get_dividends_path,
    get_tensor_path,
    get_index_path,
    INDEX_NAMES,
    TENSOR_NAMES
)
from exchange_calendar import (
    get_holidays,
    is_trading_day,
    is_trading_holiday,
    get_trading_days,
    get_next_trading_day,
    get_prev_trading_day,
)

_SEC_MASTER_CACHE: Optional[pd.DataFrame] = None
_CA_CACHE: Optional[pd.DataFrame] = None
_DIV_CACHE: Optional[pd.DataFrame] = None
_CANONICAL_INDEX_CACHE: Optional[pd.DatetimeIndex] = None
_INDEX_MASK_CACHE: Dict[str, pd.DataFrame] = {}

PRICE_FIELDS = {"open", "high", "low", "close", "vwap", "last", "prevclose"}
VOLUME_FIELDS = {"volume", "tottrdqty"}


def normalize_universe_key(universe: str) -> str:
    """Normalizes universe string by removing whitespace, hyphens, and underscores."""
    k = universe.lower().strip().replace(" ", "").replace("-", "").replace("_", "")
    if k in ("master", "all"):
        return "master"
    if k in INDEX_NAMES:
        return k
    raise ValueError(f"Unknown universe '{universe}'. Supported: {INDEX_NAMES} or 'master'")


def invalidate_universe_cache() -> None:
    """Clears all cached in-memory index masks, canonical date indices, and metadata caches."""
    global _CANONICAL_INDEX_CACHE, _INDEX_MASK_CACHE, _SEC_MASTER_CACHE, _CA_CACHE, _DIV_CACHE
    _CANONICAL_INDEX_CACHE = None
    _INDEX_MASK_CACHE.clear()
    _SEC_MASTER_CACHE = None
    _CA_CACHE = None
    _DIV_CACHE = None


def get_index_mask(universe: str, reload: bool = False) -> pd.DataFrame:
    """Returns the cached (or reloaded) Point-in-Time boolean mask DataFrame for an index."""
    univ_key = normalize_universe_key(universe)
    if univ_key == "master":
        raise ValueError("Cannot load index mask for universe 'master'.")
    if univ_key not in _INDEX_MASK_CACHE or reload:
        mask_path = get_index_path(univ_key)
        _INDEX_MASK_CACHE[univ_key] = pd.read_parquet(mask_path)
    return _INDEX_MASK_CACHE[univ_key]


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


def get_dividends(reload: bool = False) -> pd.DataFrame:
    """Returns the comprehensive Point-in-Time dividend ledger (1995-2026)."""
    global _DIV_CACHE
    if _DIV_CACHE is None or reload:
        _DIV_CACHE = pd.read_parquet(get_dividends_path())
    return _DIV_CACHE


def get_dividend_matrix(
    dates: pd.DatetimeIndex,
    tickers: List[str],
    adjusted: bool = True,
    div_df: Optional[pd.DataFrame] = None,
    ca_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Constructs a synchronous (Dates x Tickers) matrix of cash dividends paid."""
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
    """Vectorized computation of Total Return Index (TRI) matrix across (Dates x Tickers)."""
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


def compute_dividend_yield_matrix(
    close_df: pd.DataFrame,
    window: int = 252,
    dividends_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Computes trailing 12-month dividend yield matrix (Dates x Tickers)."""
    dates = close_df.index
    tickers = close_df.columns.tolist()

    div_raw = get_dividend_matrix(dates, tickers, adjusted=False, div_df=dividends_df)
    trail_div = div_raw.rolling(window=window, min_periods=1).sum()
    div_yield = trail_div.where(close_df > 0, np.nan) / close_df
    return div_yield


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
    adjusted: Union[bool, str] = True,
    forward_fill: bool = False,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """
    Loads a market data tensor (matrix of Date x Tickers) with Point-in-Time universe filtering,
    optional split/bonus backward adjustment, Total Return Index (TRI), and forward-fill.

    Parameters
    ----------
    name : str
        Tensor name: 'open', 'high', 'low', 'close', 'volume', 'turnover',
        'trades', 'vwap', 'last', 'prevclose', 'series', 'isin'.
        Metadata shortcuts: 'security_master', 'ca', 'corporate_actions', 'dividends'.
        Synthetic series: 'tri' (Total Return Index), 'dividend_yield'.
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
    adjusted : bool or str, default True
        If True, dynamically applies in-memory split and bonus adjustments to prices
        (dividing by cumulative multiplier) and volumes (multiplying by cumulative multiplier).
        If 'tri' or 'total_return', computes the continuous Total Return Index (compounding dividends).
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
    if key in ("dividends_ledger", "dividend_ledger", "div_ledger"):
        return get_dividends()
    if key in ("dividends", "dividend", "div"):
        base_close = load("close", universe=universe, asset_class=asset_class, sector=sector, adjusted=False, start=start, end=end)
        return get_dividend_matrix(base_close.index, base_close.columns.tolist(), adjusted=bool(adjusted))
    if key in ("tri", "total_return"):
        adj_close = load("close", universe=universe, asset_class=asset_class, sector=sector, adjusted=True, forward_fill=forward_fill, start=start, end=end)
        return compute_total_return_matrix(adj_close)
    if key in ("dividend_yield", "div_yield"):
        raw_close = load("close", universe=universe, asset_class=asset_class, sector=sector, adjusted=False, forward_fill=forward_fill, start=start, end=end)
        return compute_dividend_yield_matrix(raw_close)

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
    univ_key = normalize_universe_key(universe)
    if univ_key != "master":
        mask = get_index_mask(univ_key)
        common_dates = df.index.intersection(mask.index)
        common_cols = df.columns.intersection(mask.columns)
        active_mask = mask.loc[common_dates, common_cols]
        ever_active = common_cols[active_mask.any(axis=0)]
        df = df.loc[common_dates, ever_active].where(active_mask[ever_active], np.nan)

    # 4. In-Memory Corporate Action Adjustment (Splits, Bonuses, TRI)
    is_tri = isinstance(adjusted, str) and adjusted.lower().strip() in ("tri", "total_return")
    if is_tri:
        if key in PRICE_FIELDS:
            factors = compute_adjustment_factors(df.index, df.columns.tolist())
            adj_p = df / factors
            if forward_fill:
                adj_p = adj_p.ffill()
            if start:
                adj_p = adj_p.loc[adj_p.index >= pd.to_datetime(start)]
            if end:
                adj_p = adj_p.loc[adj_p.index <= pd.to_datetime(end)]
            return compute_total_return_matrix(adj_p)
    elif adjusted:
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
    adjusted: Union[bool, str] = True,
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
    close_master = load(
        "close",
        universe="master",
        asset_class=asset_class,
        sector=sector,
        adjusted=False,
    )
    turnover_master = load(
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
    univ_key = normalize_universe_key(universe)
    if univ_key != "master":
        index_mask = get_index_mask(univ_key)
        common_dates = mask.index.intersection(index_mask.index)
        common_cols = mask.columns.intersection(index_mask.columns)
        active_idx = index_mask.loc[common_dates, common_cols]
        ever_active = common_cols[active_idx.any(axis=0)]
        mask = mask.loc[common_dates, ever_active] & active_idx[ever_active]

    # 6. Slice date range after rolling computation
    if start:
        mask = mask.loc[mask.index >= pd.to_datetime(start)]
    if end:
        mask = mask.loc[mask.index <= pd.to_datetime(end)]

    return mask.astype(bool)


# Canonical alias for institutional quantitative research
get_tradable_universe_mask = get_tradable_mask

_CANONICAL_INDEX_CACHE: Optional[pd.DatetimeIndex] = None


def get_canonical_dates(reload: bool = False) -> pd.DatetimeIndex:
    """Returns the ordered DatetimeIndex of all historical trading sessions in tensors."""
    global _CANONICAL_INDEX_CACHE
    if _CANONICAL_INDEX_CACHE is None or reload:
        close_path = get_tensor_path("close")
        _CANONICAL_INDEX_CACHE = pd.read_parquet(close_path, columns=[]).index
    return _CANONICAL_INDEX_CACHE


VALID_METADATA_FIELDS = {
    "sec_id", "symbol", "company_name", "asset_class", "sector", "series", "isin",
    "listing_date", "first_traded_date", "last_traded_date"
}
VALID_METRIC_FIELDS = {
    "close", "adjusted_close", "open", "high", "low", "volume",
    "turnover", "vwap", "trades", "prevclose", "return_1d", "adtv"
}
ALL_VALID_FIELDS = VALID_METADATA_FIELDS | VALID_METRIC_FIELDS


def get_universe(
    as_of_date: Union[str, pd.Timestamp, datetime.date],
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

    If as_of_date falls on a non-trading session (weekend or exchange holiday), it automatically
    and cleanly resolves to the most recent preceding trading session, preserving zero look-ahead.

    Parameters
    ----------
    as_of_date : str, pd.Timestamp, or datetime.date
        Historical point-in-time date (e.g. '2020-03-23' or '2024-01-06').
    universe : str, default 'nifty500'
        Index or universe selector ('nifty50', 'niftynext50', 'nifty100', 'nifty200',
        'largemid250', 'midcap150', 'smallcap250', 'midsmall400', 'nifty500', 'totalmarket',
        'niftybank', 'niftyit', 'niftyauto', 'niftypharma', 'niftyfmcg', 'niftymetal',
        'niftyenergy', 'niftyfinance', 'niftyrealty', 'niftymedia', etc., or 'master').
    min_adtv : float, optional
        Minimum trailing Average Daily Traded Value (Turnover) floor computed using strictly past
        trading sessions up to as_of_date.
    adtv_window : int, default 20
        Trailing lookback window in trading days for ADTV calculation.
    min_price : float, optional
        Minimum share price floor (e.g. ₹20 to eliminate penny stocks / insolvency traps).
    max_price : float, optional
        Maximum share price cap.
    asset_class : str, optional
        Filter by asset class ('EQUITY', 'SME', 'ETF', 'MUTUAL_FUND', 'DEBT_INVIT_REIT').
    sector : str, optional
        Filter by official NSE sector/industry name.
    require_traded : bool, default False
        If True, excludes constituents that did not trade on the effective session date (Close is NaN).
    include_metrics : bool, default True
        If True, loads OHLCV, VWAP, Trades, PrevClose, 1D Return, Trailing ADTV, and split-adjusted Close.
        If False, returns only metadata fields.
    fields : List[str], optional
        Custom subset of metric and/or metadata columns to include in the output DataFrame.
    as_list : bool, default False
        If True, returns a Python List of ticker strings instead of a DataFrame.

    Returns
    -------
    pd.DataFrame or List[str]
        If as_list=True, a list of canonical ticker strings.
        Otherwise, a Point-in-Time DataFrame indexed by ticker with metadata and trading metrics.
    """
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValueError(f"min_price ({min_price}) cannot be greater than max_price ({max_price}).")

    window = int(max(int(adtv_window), 1))

    # Field validation & selection
    if fields is not None:
        user_fields = [f.lower().strip() for f in fields]
        unknown = [f for f in user_fields if f not in ALL_VALID_FIELDS]
        if unknown:
            raise ValueError(f"Unknown field(s) requested: {unknown}. Supported fields: {sorted(ALL_VALID_FIELDS)}")
        req_meta = [f for f in user_fields if f in VALID_METADATA_FIELDS]
        req_metrics = [f for f in user_fields if f in VALID_METRIC_FIELDS]
    else:
        user_fields = None
        req_meta = ["sec_id", "symbol", "company_name", "asset_class", "sector", "series", "isin", "listing_date"]
        req_metrics = [
            "close", "adjusted_close", "open", "high", "low", "volume",
            "turnover", "vwap", "trades", "prevclose", "return_1d", "adtv"
        ] if include_metrics else []

    # Timestamp & timezone normalization
    dt = pd.to_datetime(as_of_date)
    if dt.tz is not None:
        dt = dt.tz_convert("Asia/Kolkata").tz_localize(None)
    dt = dt.normalize()

    dates = get_canonical_dates()

    if dt < dates[0]:
        raise ValueError(
            f"Requested as_of_date '{as_of_date}' ({dt.strftime('%Y-%m-%d')}) "
            f"is before earliest available trading session {dates[0].strftime('%Y-%m-%d')}."
        )

    if dt > dates[-1]:
        # Handle weekends/holidays immediately following the latest available trading session
        next_session = pd.to_datetime(get_next_trading_day(dates[-1]))
        if dt < next_session:
            session_date = dates[-1]
        else:
            raise ValueError(
                f"Requested as_of_date '{as_of_date}' ({dt.strftime('%Y-%m-%d')}) "
                f"is beyond latest available trading session {dates[-1].strftime('%Y-%m-%d')}."
            )
    else:
        valid_sessions = dates[dates <= dt]
        session_date = valid_sessions[-1]

    univ_key = normalize_universe_key(universe)
    sec_master = get_security_master()

    # 1. Candidate Constituents Resolution
    if univ_key == "master":
        s_date_str = session_date.strftime("%Y-%m-%d")
        has_started = sec_master["first_traded_date"].notna() & (sec_master["first_traded_date"] <= s_date_str)
        has_not_ended = sec_master["last_traded_date"].isna() | (sec_master["last_traded_date"] >= s_date_str)
        candidate_tickers = sec_master[has_started & has_not_ended].index.tolist()
    else:
        mask = get_index_mask(univ_key)
        if session_date not in mask.index:
            raise ValueError(f"Session {session_date.strftime('%Y-%m-%d')} not in index mask for '{universe}'.")
        row_mask = mask.loc[session_date]
        candidate_tickers = row_mask.index[row_mask.values].tolist()

    # 2. Asset Class & Sector Filtering
    if asset_class:
        ac_key = asset_class.upper().strip()
        matching = set(sec_master[sec_master["asset_class"] == ac_key].index)
        candidate_tickers = [t for t in candidate_tickers if t in matching]

    if sector:
        sec_key = sector.strip()
        matching = set(sec_master[sec_master["sector"].str.contains(sec_key, case=False, na=False)].index)
        candidate_tickers = [t for t in candidate_tickers if t in matching]

    # Pre-allocate cache for loaded series so we never load the same parquet file twice
    loaded_series: Dict[str, pd.Series] = {}

    # 3. Trailing Liquidity & Price Corridors (Zero Lookahead)
    trailing_dates = dates[dates <= session_date][-window:]

    # Evaluate Close price corridors first if needed (reduces candidate_tickers early)
    need_close_for_filter = (min_price is not None and min_price > 0) or (max_price is not None and max_price > 0) or require_traded
    need_close_for_metrics = (not as_list) and include_metrics and any(m in req_metrics for m in ("close", "adjusted_close", "return_1d"))

    if candidate_tickers and (need_close_for_filter or need_close_for_metrics):
        c_df = pd.read_parquet(get_tensor_path("close"), columns=candidate_tickers)
        c_today = c_df.loc[session_date]
        loaded_series["close"] = c_today

        if require_traded:
            valid_c = set(c_today[c_today.notna() & (c_today > 0)].index)
            candidate_tickers = [t for t in candidate_tickers if t in valid_c]
        if min_price is not None and min_price > 0:
            valid_c = set(c_today[c_today >= min_price].index)
            candidate_tickers = [t for t in candidate_tickers if t in valid_c]
        if max_price is not None and max_price > 0:
            valid_c = set(c_today[c_today <= max_price].index)
            candidate_tickers = [t for t in candidate_tickers if t in valid_c]

    # Evaluate Turnover / ADTV corridor
    need_adtv_for_filter = min_adtv is not None and min_adtv > 0
    need_tn_for_metrics = (not as_list) and include_metrics and any(m in req_metrics for m in ("turnover", "adtv"))

    if candidate_tickers and (need_adtv_for_filter or need_tn_for_metrics):
        tn_df = pd.read_parquet(get_tensor_path("turnover"), columns=candidate_tickers)
        adtv_series = tn_df.loc[trailing_dates].mean()
        loaded_series["adtv"] = adtv_series
        if "turnover" in req_metrics:
            loaded_series["turnover"] = tn_df.loc[session_date]

        if need_adtv_for_filter:
            valid_adtv = set(adtv_series[adtv_series >= min_adtv].index)
            candidate_tickers = [t for t in candidate_tickers if t in valid_adtv]

    # 4. Return as List if requested
    if as_list:
        return candidate_tickers

    # Filter loaded_series to final surviving candidate_tickers
    for k in list(loaded_series.keys()):
        loaded_series[k] = loaded_series[k].reindex(candidate_tickers)

    # 5. Build Result DataFrame
    present_meta = [c for c in req_meta if c in sec_master.columns]

    if not candidate_tickers:
        final_cols = user_fields if user_fields is not None else (present_meta + (req_metrics if include_metrics else []))
        empty_df = pd.DataFrame(columns=final_cols, index=pd.Index([], name="ticker"))
        empty_df.attrs["as_of_date"] = str(as_of_date)
        empty_df.attrs["effective_date"] = session_date.strftime("%Y-%m-%d")
        empty_df.attrs["universe"] = universe
        return empty_df

    res_df = sec_master.loc[candidate_tickers, present_meta].copy()
    res_df.index.name = "ticker"

    if not include_metrics:
        if user_fields is not None:
            res_df = res_df.reindex(columns=user_fields)
        res_df.attrs["as_of_date"] = str(as_of_date)
        res_df.attrs["effective_date"] = session_date.strftime("%Y-%m-%d")
        res_df.attrs["universe"] = universe
        return res_df

    # Load any remaining requested metrics (close and turnover/adtv may already be loaded!)
    if "adjusted_close" in req_metrics:
        if "close" not in loaded_series:
            c_df = pd.read_parquet(get_tensor_path("close"), columns=candidate_tickers)
            loaded_series["close"] = c_df.loc[session_date]
        ca_factors = compute_adjustment_factors(pd.DatetimeIndex([session_date]), candidate_tickers)
        if not ca_factors.empty:
            factors = ca_factors.iloc[0]
            loaded_series["adjusted_close"] = loaded_series["close"] / factors
        else:
            loaded_series["adjusted_close"] = loaded_series["close"]

    if any(m in req_metrics for m in ("prevclose", "return_1d")):
        pc_df = pd.read_parquet(get_tensor_path("prevclose"), columns=candidate_tickers)
        loaded_series["prevclose"] = pc_df.loc[session_date]

    if "return_1d" in req_metrics:
        c = loaded_series["close"]
        pc = loaded_series["prevclose"]
        loaded_series["return_1d"] = (c - pc).where((pc > 0) & pc.notna(), np.nan) / pc

    for f in ["open", "high", "low", "volume", "vwap", "trades"]:
        if f in req_metrics:
            f_df = pd.read_parquet(get_tensor_path(f), columns=candidate_tickers)
            loaded_series[f] = f_df.loc[session_date]

    for m in req_metrics:
        if m in loaded_series:
            res_df[m] = loaded_series[m]

    if user_fields is not None:
        res_df = res_df.reindex(columns=user_fields)

    res_df.attrs["as_of_date"] = str(as_of_date)
    res_df.attrs["effective_date"] = session_date.strftime("%Y-%m-%d")
    res_df.attrs["universe"] = universe
    return res_df


