"""Read-only query API over data/build. Every call states what it can and cannot answer;
requests outside verified coverage raise CoverageError instead of returning empty or partial data."""
from __future__ import annotations

import functools

import numpy as np
import pandas as pd

from . import adjust, bhavcopy, indices, membership, paths, pipeline


class CoverageError(LookupError):
    """The requested date/index is outside what has been verified."""


@functools.lru_cache(maxsize=None)
def _identity():
    d = paths.BUILD / "identity"
    return (pd.read_parquet(d / "securities.parquet"), pd.read_parquet(d / "symbol_history.parquet"))


@functools.lru_cache(maxsize=None)
def _adjustments():
    return pd.read_parquet(paths.BUILD / "actions" / "adjustments.parquet")


@functools.lru_cache(maxsize=None)
def _prices():
    return bhavcopy.load()


def clear_cache():
    for f in (_identity, _adjustments, _prices, _intervals, _coverage):
        f.cache_clear()


def securities(as_of=None, equity_only: bool = True) -> pd.DataFrame:
    """Securities that had traded on or before `as_of` and had not stopped trading before it.
    equity_only keeps securities that traded in an equity or SME-equity series."""
    sec, _ = _identity()
    if equity_only and "is_equity" in sec:
        sec = sec[sec.is_equity]
    if as_of is None:
        return sec.copy()
    t = pd.Timestamp(as_of)
    return sec[(sec.first_date <= t) & (sec.last_date >= t)].reset_index(drop=True)


def resolve(symbol: str, as_of) -> str:
    """The sec_id that carried `symbol` on `as_of`."""
    _, sh = _identity()
    t = pd.Timestamp(as_of)
    m = sh[(sh.symbol == symbol) & (sh.from_date <= t) & (sh.to_date >= t)]
    if len(m) != 1:
        raise CoverageError(f"{symbol!r} did not map to exactly one security on {t.date()} ({len(m)} matches)")
    return m.iloc[0].sec_id


def bhavcopy_day(date) -> pd.DataFrame:
    """Every row NSE published for the date, unaltered."""
    p = _prices()
    t = pd.Timestamp(date)
    g = p[p.date == t]
    if g.empty:
        raise CoverageError(f"no bhavcopy for {t.date()} (not a trading day, or not fetched)")
    return g.reset_index(drop=True)


def adjustment_gaps(symbol: str | None = None) -> pd.DataFrame:
    """Overnight moves in the adjusted series that nothing in the corporate-action feed explains
    (or that sit on a documented, unquantifiable event such as a demerger). Written by verify."""
    p = paths.BUILD / "adjustment_gaps.csv"
    if not p.exists():
        raise CoverageError("run `nseuniverse verify` first: adjustment_gaps.csv is produced by the continuity check")
    g = pd.read_csv(p, parse_dates=["date"])
    return g if symbol is None else g[g.symbol == symbol].reset_index(drop=True)


def prices(symbols, start, end, adjust_mode: str | None = "splits", as_of=None, series: str = "primary",
           allow_unverified: bool = False, mask_gaps: bool = False) -> pd.DataFrame:
    """Daily prices for the securities that carried `symbols` on `end` (names are resolved at the
    end date, so a renamed company is followed back through its old tickers).
    adjust_mode: None (as published), 'splits' (splits, bonuses, consolidations, rights),
    'total_return' (also cash dividends). as_of: use only corporate actions with ex-date <= as_of.
    With an adjust_mode the frame also has adj_return (daily change of adj_close per security) and
    adj_gap (True on a day where the adjusted series has a documented or unexplained break, see
    adjustment_gaps()). mask_gaps=True sets adj_return to NaN on those days so a fake demerger
    drop never enters a return calculation."""
    if isinstance(symbols, str):
        symbols = [symbols]
    end_t, start_t = pd.Timestamp(end), pd.Timestamp(start)
    if adjust_mode is not None and start_t < adjust.COVERAGE_START and not allow_unverified:
        raise CoverageError(
            f"adjusted prices before {adjust.COVERAGE_START.date()} are not verified: the corporate-action feed has almost no "
            f"splits/bonuses before then. Use adjust_mode=None, start later, or allow_unverified=True.")
    sids = [resolve(s, end_t) for s in symbols]
    p = _prices()
    p = p[p.sec_id.isin(sids)]
    if series == "primary":
        p = pipeline.primary_close(p).merge(p, on=["sec_id", "date", "series"], suffixes=("_x", ""))
        p = p[[c for c in p.columns if not c.endswith("_x")]]
    elif series != "all":
        p = p[p.series == series]
    if adjust_mode is not None:
        p = adjust.apply(p, _adjustments(), adjust_mode, as_of).sort_values(["sec_id", "date"])
        p["adj_return"] = p.groupby("sec_id")["adj_close"].pct_change()
        try:
            gaps = adjustment_gaps()
        except CoverageError:
            if mask_gaps:
                raise
            gaps = pd.DataFrame({"sec_id": [], "date": []})
        gk = set(zip(gaps.sec_id, gaps.date))
        p["adj_gap"] = [(s, d) in gk for s, d in zip(p.sec_id, p.date)]
        if mask_gaps:
            p.loc[p["adj_gap"], "adj_return"] = float("nan")
    elif mask_gaps:
        raise ValueError("mask_gaps needs an adjust_mode")
    p = p[(p.date >= start_t) & (p.date <= end_t)]
    p.attrs["adjust_mode"] = adjust_mode
    p.attrs["as_of"] = None if as_of is None else str(pd.Timestamp(as_of).date())
    return p.sort_values(["sec_id", "date"]).reset_index(drop=True)


def index_values(index: str, start=None, end=None) -> pd.DataFrame:
    v = indices.values(index)
    if v.empty:
        raise CoverageError(f"no values for index {index!r}")
    if start is not None:
        v = v[v.date >= pd.Timestamp(start)]
    if end is not None:
        v = v[v.date <= pd.Timestamp(end)]
    return v.reset_index(drop=True)


@functools.lru_cache(maxsize=None)
def _intervals():
    return pd.read_parquet(paths.BUILD / "membership" / "intervals.parquet")


@functools.lru_cache(maxsize=None)
def _coverage():
    p = paths.BUILD / "membership" / "coverage.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=["index_key", "from_date", "to_date", "status", "reason"])


def coverage() -> pd.DataFrame:
    """Per index: the date ranges over which membership is verified."""
    return _coverage().copy()


def index_members(index: str, as_of) -> pd.DataFrame:
    k = indices.name_map().get(indices.key(index), indices.key(index))
    t = pd.Timestamp(as_of)
    c = _coverage()
    ok = c[(c.index_key == k) & (c.status == "VERIFIED") & (c.from_date <= t) & (c.to_date >= t)]
    if ok.empty:
        raise CoverageError(f"membership of {index!r} on {t.date()} is not verified; see coverage()")
    sids = membership.members(_intervals(), k, t)
    sec, _ = _identity()
    return sec[sec.sec_id.isin(sids)].reset_index(drop=True)
