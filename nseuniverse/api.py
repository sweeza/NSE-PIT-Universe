"""Read-only query API over data/build. Every call states what it can and cannot answer;
requests outside verified coverage raise CoverageError instead of returning empty or partial data."""
from __future__ import annotations

import functools
import warnings

import numpy as np
import pandas as pd

from . import adjust, bhavcopy, indices, membership, paths, pipeline


class CoverageError(LookupError):
    """The requested date/index is outside what has been verified."""


class DataQualityWarning(UserWarning):
    """The returned frame contains days that NSE's data cannot support (adjustment breaks, conflicting index
    values). The affected days are listed in frame.attrs['flagged']; mask_gaps / mask_conflicts blank them."""


def _flag_summary(flagged: pd.DataFrame, what: str, masked: bool) -> str:
    by = flagged.groupby("class").size().to_dict()
    action = "returns on these days were set to NaN" if masked else "returns on these days are NOT masked"
    return (f"{len(flagged)} {what} day(s) in the result ({by}); {action}. "
            f"See frame.attrs['flagged'] for the exact days.")


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


@functools.lru_cache(maxsize=None)
def _prices_year(year: int) -> pd.DataFrame:
    p = paths.BUILD / "bhavcopy" / f"bhavcopy_{year}.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


@functools.lru_cache(maxsize=None)
def _sme_secs() -> frozenset:
    """Securities that ever traded in an SME-platform series (SM, ST)."""
    out = set()
    for f in sorted((paths.BUILD / "bhavcopy").glob("bhavcopy_*.parquet")):
        d = pd.read_parquet(f, columns=["sec_id", "series"])
        out |= set(d.loc[d.series.isin(["SM", "ST"]), "sec_id"].unique())
    return frozenset(out)


def sme_securities() -> pd.DataFrame:
    """SME-platform securities (ever traded in series SM or ST). Their ADJUSTED prices are not reliable: the NSE
    corporate-action feed holds no records for SME securities, so none of their splits or bonuses is applied.
    Raw prices are exact. prices() marks them with adj_reliable=False."""
    sec, _ = _identity()
    return sec[sec.sec_id.isin(_sme_secs())].reset_index(drop=True)


def clear_cache():
    for f in (_identity, _adjustments, _prices, _prices_year, _intervals, _coverage, _sme_secs):
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
    t = pd.Timestamp(date)
    p = _prices_year(t.year)
    g = p[p.date == t] if not p.empty else p
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
    def _resolve_for_prices(sym: str) -> str:
        ref = pd.Timestamp(as_of) if as_of is not None else end_t
        try:
            return resolve(sym, ref)
        except CoverageError:
            _, sh = _identity()
            if not sh.empty:
                latest = sh["to_date"].max()
                if ref > latest:
                    try:
                        return resolve(sym, latest)
                    except CoverageError:
                        pass
                ov = sh[(sh.symbol == sym) & (sh.from_date <= end_t) & (sh.to_date >= start_t)]["sec_id"].unique()
                if len(ov) == 1:
                    return ov[0]
            raise

    sids = [_resolve_for_prices(s) for s in symbols]
    frames = [_prices_year(y) for y in range(start_t.year, end_t.year + 1)]
    frames = [f for f in frames if not f.empty]
    p = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["sec_id", "date", "series", "close"])
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
        gcls = {(s, d): c for s, d, c in zip(gaps.sec_id, gaps.date, gaps.get("class", [""] * len(gaps)))}
        p["adj_gap"] = [(s, d) in gk for s, d in zip(p.sec_id, p.date)]
        p["adj_gap_class"] = [gcls.get((s, d), "") for s, d in zip(p.sec_id, p.date)]
        if mask_gaps:
            p.loc[p["adj_gap"], "adj_return"] = float("nan")
    elif mask_gaps:
        raise ValueError("mask_gaps needs an adjust_mode")
    p = p[(p.date >= start_t) & (p.date <= end_t)]
    if adjust_mode is not None:
        p["adj_reliable"] = ~p.sec_id.isin(_sme_secs())
        if not p.adj_reliable.all():
            warnings.warn("SME-platform securities in the result (adj_reliable=False): the NSE feed has no corporate actions "
                          "for SME securities, so their adjusted prices carry unadjusted splits and bonuses. Use raw "
                          "prices or leave them out. See sme_securities().", DataQualityWarning, stacklevel=2)
        fl = p.loc[p.adj_gap, ["sec_id", "date", "adj_gap_class"]].rename(columns={"adj_gap_class": "class"})
        fl = fl.merge(p[["sec_id", "symbol"]].drop_duplicates("sec_id"), on="sec_id", how="left") if "symbol" in p else fl
        p.attrs["flagged"] = fl.reset_index(drop=True)
        if len(fl):
            warnings.warn(_flag_summary(fl, "flagged adjusted-price", mask_gaps), DataQualityWarning, stacklevel=2)
    if p.empty:
        raise CoverageError(f"no price rows for {symbols} between {start_t.date()} and {end_t.date()}: "
                            f"no trading session in the range, or the security did not trade in series {series!r}")
    p.attrs["adjust_mode"] = adjust_mode
    p.attrs["as_of"] = None if as_of is None else str(pd.Timestamp(as_of).date())
    return p.sort_values(["sec_id", "date"]).reset_index(drop=True)


def index_values(index: str, start=None, end=None, mask_conflicts: bool = False, source: str | None = None) -> pd.DataFrame:
    """Official index values. Adds ret (daily change of close). Days where NSE's two sources disagree carry
    conflict=True. A return is unreliable if either its day or the previous day conflicts; with
    mask_conflicts=True ret is NaN on those days. frame.attrs['flagged'] lists them either way.
    source='history' or 'daily' (explicit, never the default): on conflict days use that source's close instead of the
    other's; open/high/low/tri/ntr are blanked on those days (they would come from the other source) and ret is computed
    from the chosen source. The choice is yours: check the index's boundary days first (see docs/AUDIT_REPORT.md)."""
    if source not in (None, "history", "daily"):
        raise ValueError("source must be None, 'history' or 'daily'")
    if source is not None and mask_conflicts:
        raise ValueError("use either source= or mask_conflicts=True, not both")
    v = indices.values(index)
    if v.empty:
        raise CoverageError(f"no values for index {index!r}")
    v = v.sort_values("date").reset_index(drop=True)
    conf = v["conflict"].fillna(False).astype(bool) if "conflict" in v else pd.Series(False, index=v.index)
    swapped = pd.Series(False, index=v.index)
    if source is not None:
        swapped = conf & (v["src"] != source)
        v.loc[swapped, "close"] = v.loc[swapped, "alt_close"]
        v.loc[swapped, [c for c in ("open", "high", "low", "tri", "ntr") if c in v]] = float("nan")
        v.loc[swapped, "src"] = source
    v["ret"] = v["close"].pct_change()
    bad = pd.Series(False, index=v.index) if source is not None else conf | conf.shift(1, fill_value=False)
    v["ret_unreliable"] = bad
    if mask_conflicts:
        v.loc[bad, "ret"] = float("nan")
    if start is not None:
        v = v[v.date >= pd.Timestamp(start)]
    if end is not None:
        v = v[v.date <= pd.Timestamp(end)]
    v = v.reset_index(drop=True)
    if source is not None:
        fl = v.loc[v["conflict"].fillna(False).astype(bool), ["date", "close", "alt_close"]].assign(
            **{"class": f"SOURCE_CONFLICT_USED_{source.upper()}"})
        v.attrs["flagged"] = fl.reset_index(drop=True)
        if len(fl):
            warnings.warn(f"{len(fl)} {index} conflict day(s) in the result use the {source!r} source by your choice; "
                          f"open/high/low/tri/ntr are blank on the {int(swapped.sum())} rows that were switched.",
                          DataQualityWarning, stacklevel=2)
        return v
    fl = v.loc[v.ret_unreliable, ["date", "close", "alt_close"]].assign(**{"class": "SOURCE_CONFLICT"})         if "alt_close" in v else v.loc[v.ret_unreliable, ["date"]].assign(**{"class": "SOURCE_CONFLICT"})
    v.attrs["flagged"] = fl.reset_index(drop=True)
    if len(fl):
        warnings.warn(_flag_summary(fl, f"{index} source-conflict", mask_conflicts), DataQualityWarning, stacklevel=2)
    return v


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


def index_members(index: str, as_of, backfill: bool = False) -> pd.DataFrame:
    """Members of an index on a date, with the symbol each security carried then.

    Refuses a date that is not verified (see coverage()). backfill=True is an opt-in for dates BEFORE the
    index's first verified day (from 2007-01-01): it returns the members of the first verified day that were
    already trading on `as_of`, marked membership_status='BACKFILLED_UNVERIFIED'. That list is NOT what the
    index held then (it was not published or was not checked): it carries survivorship and look-ahead bias and
    is meant for out-of-sample tests only. A date inside or between verified windows is never backfilled."""
    k = indices.name_map().get(indices.key(index), indices.key(index))
    t = pd.Timestamp(as_of)
    c = _coverage()
    ok = c[(c.index_key == k) & (c.status == "VERIFIED") & (c.from_date <= t) & (c.to_date >= t)]
    sec, sh = _identity()
    if ok.empty:
        first = c[(c.index_key == k) & (c.status == "VERIFIED")].from_date.min()
        if not (backfill and pd.notna(first) and adjust.COVERAGE_START <= t < first):
            raise CoverageError(f"membership of {index!r} on {t.date()} is not verified; see coverage()"
                                + ("" if not backfill else " (backfill only covers 2007-01-01 up to the first verified day)"))
        sids = membership.members(_intervals(), k, first)
        started = sec.set_index("sec_id").first_date
        sids = [s for s in sids if s in started.index and started[s] <= t]
        out = _with_symbols(sec, sh, sids, t)
        out["membership_status"] = "BACKFILLED_UNVERIFIED"
        out["backfilled_from"] = first
        warnings.warn(f"{index}: {t.date()} is before the first verified day {first.date()}; the member list is the "
                      f"{first.date()} list restricted to securities already trading, not the published membership",
                      DataQualityWarning, stacklevel=2)
        return out
    out = _with_symbols(sec, sh, membership.members(_intervals(), k, t), t)
    out["membership_status"] = "VERIFIED"
    return out


def _with_symbols(sec: pd.DataFrame, sh: pd.DataFrame, sids, t: pd.Timestamp) -> pd.DataFrame:
    out = sec[sec.sec_id.isin(sids)].reset_index(drop=True)
    sub = sh[sh.sec_id.isin(sids)]
    sym_map = {}
    for sid, g in sub.groupby("sec_id"):
        exact = g[(g.from_date <= t) & (g.to_date >= t)]
        if not exact.empty:
            sym_map[sid] = exact.sort_values("to_date").iloc[-1].symbol
        else:
            prior = g[g.from_date <= t]
            if not prior.empty:
                sym_map[sid] = prior.sort_values("to_date").iloc[-1].symbol
            else:
                sym_map[sid] = g.sort_values("from_date").iloc[0].symbol
    out["symbol"] = out["sec_id"].map(sym_map)
    return out
