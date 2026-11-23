"""Read-only query API over data/build. Every call states what it can and cannot answer;
requests outside verified coverage raise CoverageError instead of returning empty or partial data."""
from __future__ import annotations

import functools
import warnings

import numpy as np
import pandas as pd

from . import actions, adjust, bhavcopy, caveats as _caveats, indices, membership, paths, pipeline


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


@functools.lru_cache(maxsize=None)
def _unreliable() -> dict:
    """sec_id -> reason, from SME status and data/curated/adjustment_unreliable.csv (known wrong adjusted history)."""
    out = {s: "SME platform: the NSE feed has no corporate actions for SME securities" for s in _sme_secs()}
    p = paths.CURATED / "adjustment_unreliable.csv"
    if p.exists():
        _, sh = _identity()
        for r in pd.read_csv(p, dtype=str).fillna("").itertuples():
            for sid in sh.loc[sh.symbol == r.symbol, "sec_id"].unique():
                out[sid] = r.reason
    return out


def unreliable_adjusted() -> pd.DataFrame:
    """Securities whose adjusted prices are known to be wrong or incomplete (SME platform, plus the curated list
    data/curated/adjustment_unreliable.csv): sec_id, symbol (last), reason. prices() marks them adj_reliable=False."""
    sec, _ = _identity()
    u = _unreliable()
    out = sec[sec.sec_id.isin(u)][["sec_id", "last_symbol"]].rename(columns={"last_symbol": "symbol"}).reset_index(drop=True)
    out["reason"] = out.sec_id.map(u)
    return out


def clear_cache():
    for f in (_identity, _adjustments, _prices, _prices_year, _intervals, _coverage, _sme_secs, _unreliable, _market):
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
        p["adj_reliable"] = ~p.sec_id.isin(_unreliable())
        if not p.adj_reliable.all():
            why = sorted({_unreliable()[s] for s in p.loc[~p.adj_reliable, "sec_id"].unique()})
            warnings.warn("securities with unreliable adjusted prices in the result (adj_reliable=False): "
                          + "; ".join(w[:90] for w in why[:4]) + ". Use raw prices or leave them out. See unreliable_adjusted().",
                          DataQualityWarning, stacklevel=2)
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
    from the chosen source. The choice is yours: check the index's boundary days first (see docs/AUDIT_REPORT.md).
    source='rule' (explicit, never the default) applies a fixed rule to each conflict day, estimating nothing:
      a close of 0 in one source is a placeholder: the other source's close is used (class SOURCE_CONFLICT_RESOLVED_ZERO);
      the two closes differ by less than 0.1%: the daily file's close is used (SOURCE_CONFLICT_RESOLVED_DAILY);
      they differ by 0.1% or more: neither is chosen, the close stays as built and the return of that day and the next
      is NaN (SOURCE_CONFLICT_UNRESOLVED). open/high/low/tri/ntr are blanked on rows whose close was switched."""
    if source not in (None, "history", "daily", "rule"):
        raise ValueError("source must be None, 'history', 'daily' or 'rule'")
    if source is not None and mask_conflicts:
        raise ValueError("use either source= or mask_conflicts=True, not both")
    v = indices.values(index)
    if v.empty:
        raise CoverageError(f"no values for index {index!r}")
    v = v.sort_values("date").reset_index(drop=True)
    conf = v["conflict"].fillna(False).astype(bool) if "conflict" in v else pd.Series(False, index=v.index)
    swapped = pd.Series(False, index=v.index)
    if source == "rule":
        return _index_values_rule(index, v, conf, start, end)
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


RULE_TOLERANCE = 0.001  # index_values(source="rule"): relative close difference below which the daily file is used


def _index_values_rule(index, v, conf, start, end):
    alt = v["alt_close"] if "alt_close" in v else pd.Series(float("nan"), index=v.index)
    zero = conf & ((v["close"] == 0) | (alt == 0))
    rel = (v["close"] - alt).abs() / pd.concat([v["close"].abs(), alt.abs()], axis=1).max(axis=1)
    small = conf & ~zero & (rel < RULE_TOLERANCE)
    unresolved = conf & ~zero & ~small
    swapped = (zero & (v["close"] == 0)) | (small & (v["src"] != "daily"))
    v.loc[swapped, "close"] = alt[swapped]
    v.loc[swapped, [c for c in ("open", "high", "low", "tri", "ntr") if c in v]] = float("nan")
    v.loc[swapped & zero, "src"] = "history"
    v.loc[swapped & small, "src"] = "daily"
    cls = pd.Series("", index=v.index)
    cls[zero] = "SOURCE_CONFLICT_RESOLVED_ZERO"
    cls[small] = "SOURCE_CONFLICT_RESOLVED_DAILY"
    cls[unresolved] = "SOURCE_CONFLICT_UNRESOLVED"
    v["ret"] = v["close"].pct_change()
    bad = unresolved | unresolved.shift(1, fill_value=False)
    v["ret_unreliable"] = bad
    v.loc[bad, "ret"] = float("nan")
    v["conflict_class"] = cls
    if start is not None:
        v = v[v.date >= pd.Timestamp(start)]
    if end is not None:
        v = v[v.date <= pd.Timestamp(end)]
    v = v.reset_index(drop=True)
    fl = v.loc[v["conflict_class"] != "", ["date", "close", "alt_close", "conflict_class"]].rename(
        columns={"conflict_class": "class"})
    v.attrs["flagged"] = fl.reset_index(drop=True)
    n_un = int((v["conflict_class"] == "SOURCE_CONFLICT_UNRESOLVED").sum())
    if len(fl):
        warnings.warn(f"{len(fl)} {index} conflict day(s) in the result were handled by source='rule': {n_un} remain "
                      f"unresolved (return NaN); see frame.attrs['flagged'] and the 'class' column.",
                      DataQualityWarning, stacklevel=3)
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
            raise CoverageError(f"membership of {index!r} on {t.date()} is not verified; see coverage() and index_availability()"
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


@functools.lru_cache(maxsize=None)
def _market(name: str) -> pd.DataFrame:
    p = paths.BUILD / "market" / f"{name}.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def _sid_for(symbol: str, at) -> str:
    return resolve(symbol, pd.Timestamp(at))


def delivery(symbols, start, end) -> pd.DataFrame:
    """NSE's security-wise delivery position (2004-): traded_qty, deliv_qty, deliv_pct per date, series and
    security. deliv_qty is the deliverable quantity NSE publishes (gross across client level)."""
    if isinstance(symbols, str):
        symbols = [symbols]
    d = _market("delivery")
    if d.empty:
        raise CoverageError("no delivery data in this build (python -m nseuniverse.cli fetch market, then build)")
    sids = set()
    for s in symbols:
        try:
            sids.add(_sid_for(s, end))
        except CoverageError:            # delisted before `end`: the security that carried the symbol at the start
            sids.add(_sid_for(s, start))
    out = d[d.sec_id.isin(sids) & (d.date >= pd.Timestamp(start)) & (d.date <= pd.Timestamp(end))]
    if out.empty:
        raise CoverageError(f"no delivery rows for {symbols} between {start} and {end}")
    return out.reset_index(drop=True)


def price_band(symbol: str, as_of) -> dict:
    """Circuit limit (percent; 'No Band' stays text) of a security on a date, with its source. From 2020 the daily
    security list gives it for every security; before that only the recorded changes since 2010 do: the band is the
    last 'To' value on or before the date, and a security with no recorded change yet is refused (the starting band
    was not published)."""
    t = pd.Timestamp(as_of)
    sid = _sid_for(symbol, t)
    sl = _market("sec_list")
    if len(sl):
        x = sl[(sl.sec_id == sid) & (sl.date == t)]
        if len(x):
            r = x.iloc[0]
            return {"band": r.band, "series": r.series, "source": "sec_list", "remarks": r.remarks}
    bc = _market("band_changes")
    if len(bc):
        y = bc[(bc.sec_id == sid) & (bc.date <= t)].sort_values("date")
        if len(y):
            r = y.iloc[-1]
            return {"band": r.band_to, "series": r.series, "source": f"band_changes {r.date.date()}", "remarks": ""}
    raise CoverageError(f"price band of {symbol!r} on {t.date()} is not known: no security list for that day and no recorded band change since 2010")


def asm_gsm(as_of) -> pd.DataFrame:
    """Securities with a surveillance remark (ASM/GSM stage etc.) in NSE's security list for the day (2020-)."""
    t = pd.Timestamp(as_of)
    sl = _market("sec_list")
    x = sl[(sl.date == t) & (sl.remarks != "")] if len(sl) else sl
    if sl.empty or not (sl.date == t).any():
        raise CoverageError(f"no security list for {t.date()} (available from 2020)")
    return x.reset_index(drop=True)


def fo_ban(as_of) -> pd.DataFrame:
    """Securities in the F&O ban period on a date. An empty frame means NSE's file for that day says NIL; a day
    without a file raises."""
    t = pd.Timestamp(as_of)
    b = _market("fo_ban")
    days = paths.MARKET_RAW / "fosecban" / f"{t.year}" / f"fo_secban_{t:%d%m%Y}.csv"
    if not days.exists():
        raise CoverageError(f"no F&O ban file for {t.date()}")
    return b[b.date == t].reset_index(drop=True) if len(b) else b


def _events() -> pd.DataFrame:
    p = paths.BUILD / "actions" / "events.parquet"
    return pd.read_parquet(p, columns=["symbol", "sec_id", "ex_date", "kind", "subject", "status"]) if p.exists() else pd.DataFrame()


def caveats(category: str | None = None) -> pd.DataFrame:
    """Every known limit of the data with its backtest impact and how to handle it, plus `affected`: how much of this
    build it touches (None where a count does not apply). category: PRICES, ACTIONS, MEMBERSHIP, INDEX, MARKET, GENERAL."""
    c = _caveats.catalogue()
    if category:
        c = c[c.category == category.upper()]

    def n(fn):
        try:
            return fn()
        except Exception:
            return None
    ev = n(_events)
    unq = n(lambda: int(ev[ev.kind.isin(["UNPARSED", "UNKNOWN", "SCHEME"]) & (ev.status == "OK") & (ev.ex_date >= "2007-01-01")].shape[0]))
    div = n(lambda: int(ev[((ev.kind == "UNPARSED") & ev.subject.str.contains("(?i)div")) | (ev.status == "NO_TRADING_NEAR")].shape[0]))
    sme = n(lambda: len(_sme_secs()))
    cur = n(lambda: len([s for s, r in _unreliable().items() if not r.startswith("SME")]))
    gaps = n(lambda: adjustment_gaps().query("date >= '2007-01-01'").sec_id.nunique())
    feed = n(lambda: str(ev.ex_date.max().date()))
    lag = n(lambda: (lambda r: None if r[0] is None else f"feed ends {r[1].date()}, last bhavcopy {r[2].date()} ({r[0]} days)")(actions.feed_lag()))
    cov = n(lambda: int(_coverage()[_coverage().status == "VERIFIED"].index_key.nunique()))
    conf = n(lambda: int(len(pd.read_csv(paths.BUILD / "index_conflicts.csv"))))
    counts = {"SME_ADJUSTED_PRICES": f"{sme} securities", "CURATED_UNRELIABLE_ADJUSTED": f"{cur} securities",
              "DOCUMENTED_ADJUSTMENT_BREAK": f"{gaps} securities", "UNQUANTIFIED_CORPORATE_ACTIONS": f"{unq} events",
              "DIVIDENDS_FROM_FEED_TEXT": f"{div} records", "FEED_ENDS": f"last ex-date {feed}", "FEED_LAGS_BHAVCOPY": lag,
              "MEMBERSHIP_NOT_VERIFIED": f"{cov} indices have a verified window", "MEMBERSHIP_BACKFILLED": f"{cov} indices can be backfilled",
              "INDEX_VALUE_CONFLICTS": f"{conf} index-days"}
    c = c.copy()
    c["affected"] = c["id"].map(counts)
    return c.reset_index(drop=True)


def explain(symbols=None, start=None, end=None, index: str | None = None) -> pd.DataFrame:
    """The flags that apply to a selection: securities (symbols) over a date range and/or an index over a range.
    One row per flag with the securities and dates concerned. Always-on flags (no announcement dates, unstable
    sec_id) are included. Use before trusting a backtest on the selection."""
    cat = _caveats.catalogue().set_index("id")
    s0 = pd.Timestamp(start) if start is not None else pd.Timestamp("2007-01-01")
    e0 = pd.Timestamp(end) if end is not None else pd.Timestamp.today().normalize()
    rows = []

    def add(fid, detail):
        r = cat.loc[fid]
        rows.append((fid, r.category, r.severity, detail, r.backtest_impact, r.handling))
    if isinstance(symbols, str):
        symbols = [symbols]
    if symbols:
        sids = {}
        for s in symbols:
            try:
                sids[_sid_for(s, e0)] = s
            except CoverageError:
                sids[_sid_for(s, s0)] = s
        un = _unreliable()
        for sid, sym in sids.items():
            if sid in un:
                add("SME_ADJUSTED_PRICES" if un[sid].startswith("SME") else "CURATED_UNRELIABLE_ADJUSTED", f"{sym}: {un[sid]}")
        try:
            g = adjustment_gaps()
            g = g[g.sec_id.isin(sids) & (g.date >= s0) & (g.date <= e0)]
            for sid, x in g.groupby("sec_id"):
                add("DOCUMENTED_ADJUSTMENT_BREAK", f"{sids[sid]}: " + ", ".join(f"{d.date()} ({c})" for d, c in zip(x.date, x["class"]))[:300])
        except CoverageError:
            pass
        ev = _events()
        if len(ev):
            x = ev[ev.sec_id.isin(sids) & ev.kind.isin(["UNPARSED", "UNKNOWN", "SCHEME"]) & (ev.status == "OK") & (ev.ex_date >= s0) & (ev.ex_date <= e0)]
            for sid, y in x.groupby("sec_id"):
                add("UNQUANTIFIED_CORPORATE_ACTIONS", f"{sids[sid]}: " + "; ".join(f"{d.date()} {k} {sub[:40]}" for d, k, sub in zip(y.ex_date, y.kind, y.subject))[:300])
            feed = ev.ex_date.max()
            if e0 > feed - pd.Timedelta(days=30):
                add("FEED_ENDS", f"corporate-action feed ends {feed.date()}; the selection reaches {e0.date()}")
        if s0 < adjust.COVERAGE_START:
            add("ADJUSTED_BEFORE_2007", f"range starts {s0.date()}")
    if index is not None:
        k = indices.name_map().get(indices.key(index), indices.key(index))
        c = _coverage()
        v = c[(c.index_key == k) & (c.status == "VERIFIED")]
        if v.empty:
            add("MEMBERSHIP_NOT_VERIFIED", f"{index}: no verified window")
        else:
            first = v.from_date.min()
            if s0 < first:
                add("MEMBERSHIP_BACKFILLED", f"{index}: verified from {first.date()}; {s0.date()} to {min(e0, first).date()} would be backfilled")
            gaps_ = []
            lo = max(s0, first)
            for r in v.sort_values("from_date").itertuples():
                if r.from_date > lo and lo <= e0:
                    gaps_.append(f"{lo.date()}..{(r.from_date - pd.Timedelta(days=1)).date()}")
                lo = max(lo, r.to_date + pd.Timedelta(days=1))
            if lo <= e0:
                gaps_.append(f"{lo.date()}..{e0.date()}")
            if gaps_:
                add("MEMBERSHIP_NOT_VERIFIED", f"{index}: unverified inside the range: " + ", ".join(gaps_))
            if s0 < pd.Timestamp("2010-01-01"):
                add("MEMBERSHIP_2007_2009_THIN_EVIDENCE", f"{index}: range starts {s0.date()}")
        try:
            iv = index_values(index, s0, e0)
            nconf = int(iv.conflict.sum()) if "conflict" in iv else 0
            if nconf:
                add("INDEX_VALUE_CONFLICTS", f"{index}: {nconf} conflicting index-days in the range")
        except Exception:
            pass
    add("EX_DATE_NOT_ANNOUNCEMENT_DATE", "applies to every adjusted series")
    add("SEC_ID_NOT_STABLE", "applies to every saved sec_id")
    out = pd.DataFrame(rows, columns=["id", "category", "severity", "applies_to", "backtest_impact", "handling"])
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return out.sort_values(["severity", "category", "id"], key=lambda s: s.map(order) if s.name == "severity" else s, kind="mergesort").reset_index(drop=True)


def fo_eligible(as_of) -> pd.DataFrame:
    """Stocks with futures and/or options contracts in NSE's derivatives bhavcopy on a date (2004-): the F&O segment
    for that day. `fut` and `opt` say which. A date with no derivatives file raises."""
    t = pd.Timestamp(as_of)
    f = _market("fo_stocks")
    if f.empty or not (f.date == t).any():
        raise CoverageError(f"no derivatives bhavcopy for {t.date()} in this build")
    return f[f.date == t].reset_index(drop=True)


def deals(symbols, start, end, kind: str | None = None) -> pd.DataFrame:
    """Bulk deals (2004-), block deals (2005-), and short selling (2008-) from NSE's report archive and daily
    snapshots. Raises CoverageError outside the covered date range for the requested kind."""
    if kind not in (None, "bulk", "block", "short"):
        raise ValueError(f"kind must be None, 'bulk', 'block', or 'short', got {kind!r}")
    d = _market("deals")
    if d.empty:
        raise CoverageError("no deals data in this build (build market tables first)")
    sub = d[d.kind == kind] if kind is not None else d
    if sub.empty:
        raise CoverageError(f"no {kind} deals data in this build")
    s0, e0 = pd.Timestamp(start), pd.Timestamp(end)
    lo, hi = sub.date.min(), d.date.max()
    if s0 > e0 or s0 < lo or e0 > hi:
        raise CoverageError(f"deals ({kind or 'all'}) cover {lo.date()}..{hi.date()}; requested {s0.date()}..{e0.date()}")
    out = sub[(sub.date >= s0) & (sub.date <= e0)]
    if symbols is not None:
        if isinstance(symbols, str):
            symbols = [symbols]
        sids = set()
        for s in symbols:
            try:
                sids.add(_sid_for(s, e0))
            except CoverageError:
                sids.add(_sid_for(s, s0))
        out = out[out.sec_id.isin(sids)]
    return out.reset_index(drop=True)


def shares_outstanding(symbols, start, end) -> pd.DataFrame:
    """Issued share count per security and trading day from NSE's MII security master (2024-02-05 onward), with the
    face value. A count is NSE's figure for that day, never filled or carried across days that have no file.
    Free float is not published in that file (it is empty), so no free-float or float-adjusted market cap exists.
    A market cap would be the raw (unadjusted) `close * shares_outstanding`, computed by the caller. Raises
    CoverageError outside the covered dates or if the build holds no MII data."""
    d = _market("shares")
    if d.empty:
        raise CoverageError("no shares data in this build (python -m nseuniverse.cli fetch market, then build)")
    s0, e0 = pd.Timestamp(start), pd.Timestamp(end)
    lo, hi = d.date.min(), d.date.max()
    if s0 > e0 or s0 < lo or e0 > hi:
        raise CoverageError(f"shares outstanding cover {lo.date()}..{hi.date()}; requested {s0.date()}..{e0.date()}")
    out = d[(d.date >= s0) & (d.date <= e0)]
    if symbols is not None:
        if isinstance(symbols, str):
            symbols = [symbols]
        sids = set()
        for s in symbols:
            try:
                sids.add(_sid_for(s, e0))
            except CoverageError:
                sids.add(_sid_for(s, s0))
        out = out[out.sec_id.isin(sids)]
    return out.reset_index(drop=True)


def impact_cost(symbols, start, end) -> pd.DataFrame:
    """Monthly NSE Clearing security category (1/2/3) and 6-month rolling mean impact cost (%) for a standard
    Rs 1 lakh order (continuous from 2023-10; sporadic earlier months from 2019-03). Raises CoverageError if no
    monthly file exists in the requested range. Missing values for a security stay NaN and are never filled."""
    d = _market("impact_cost")
    if d.empty:
        raise CoverageError("no impact_cost data in this build (python -m nseuniverse.cli fetch market, then build)")
    s0 = pd.Timestamp(start).to_period("M").to_timestamp()
    e0 = pd.Timestamp(end).to_period("M").to_timestamp()
    if s0 > e0:
        raise CoverageError(f"invalid range: {start}..{end}")
    out = d[(d.date >= s0) & (d.date <= e0)]
    if out.empty:
        raise CoverageError(f"no impact_cost monthly file between {pd.Timestamp(start).date()} and {pd.Timestamp(end).date()}")
    if symbols is not None:
        if isinstance(symbols, str):
            symbols = [symbols]
        sids = set()
        s_t, e_t = pd.Timestamp(start), pd.Timestamp(end)
        for s in symbols:
            try:
                sids.add(_sid_for(s, e_t))
            except CoverageError:
                try:
                    sids.add(_sid_for(s, s_t))
                except CoverageError:
                    _, sh = _identity()
                    ov = sh[(sh.symbol == s) & (sh.from_date <= e_t) & (sh.to_date >= s_t)]["sec_id"].unique()
                    if len(ov) == 1:
                        sids.add(ov[0])
                    else:
                        raise
        out = out[out.sec_id.isin(sids)]
    return out.reset_index(drop=True)


def index_availability(category: str | None = None) -> pd.DataFrame:
    """For each equity index in scope (data/curated/index_universe.csv: broad market and sectoral), from when the data
    can be relied on. One row per index:
      values_from / values_to   first and last date of NSE's published index levels held (levels before the index's
                                launch are NSE's own back-calculation, see caveat INDEX_HISTORY_IS_BACKCAST)
      membership_from / _to     first and last day of verified membership; membership_status is FULL (one unbroken
                                verified span to the last data day), GAPS (verified, but with unverified stretches
                                listed in membership_gaps) or UNVERIFIED (no verified day: index_members refuses it)
      reliable_from             start of the unbroken verified span that reaches the last day: use dates on or after it
      thin_evidence             True when reliable_from is before 2010-01-01 (2007-2009 rests on less evidence)
    Backfill (index_members(..., backfill=True)) may cover the dates before membership_from, flagged as unverified."""
    uni = pd.read_csv(paths.CURATED / "index_universe.csv")
    if category:
        uni = uni[uni.category == category]
    cov = _coverage()
    rows = []
    for r in uni.itertuples():
        k = r.index_key
        try:
            v = indices.values(r.index_name)
            vf, vt = (v.date.min(), v.date.max()) if len(v) else (pd.NaT, pd.NaT)
        except Exception:
            vf = vt = pd.NaT
        w = cov[(cov.index_key == k) & (cov.status == "VERIFIED")].sort_values("from_date")
        if w.empty:
            rows.append((k, r.index_name, r.category, vf, vt, pd.NaT, pd.NaT, "UNVERIFIED", "", "", pd.NaT, False))
            continue
        gaps, start, prev_end = [], w.iloc[0].from_date, w.iloc[0].to_date
        for x in w.iloc[1:].itertuples():
            if (x.from_date - prev_end).days > 1:
                gaps.append(f"{(prev_end + pd.Timedelta(days=1)).date()}..{(x.from_date - pd.Timedelta(days=1)).date()}")
                start = x.from_date
            prev_end = max(prev_end, x.to_date)
        last_day = cov.to_date.max()
        status = "FULL" if not gaps and prev_end >= last_day - pd.Timedelta(days=7) else "GAPS"
        spans = "; ".join(f"{a.date()}..{b.date()}" for a, b in zip(w.from_date, w.to_date))
        rows.append((k, r.index_name, r.category, vf, vt, w.from_date.min(), prev_end, status, "; ".join(gaps), spans, start,
                     bool(start < pd.Timestamp("2010-01-01"))))
    return pd.DataFrame(rows, columns=["index_key", "index_name", "category", "values_from", "values_to", "membership_from",
                                       "membership_to", "membership_status", "membership_gaps", "verified_spans", "reliable_from", "thin_evidence"])
