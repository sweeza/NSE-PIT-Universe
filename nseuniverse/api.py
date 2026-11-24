"""Read-only query API over data/build. Every call states what it can and cannot answer;
requests outside verified coverage raise CoverageError instead of returning empty or partial data."""
from __future__ import annotations

import functools
import warnings

import numpy as np
import pandas as pd

from . import actions, adjust, bhavcopy, caveats as _caveats, indices, membership, paths, pipeline, reconstruct as _recon


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
    Raw prices are exact; prices() refuses an adjust_mode for them."""
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
    data/curated/adjustment_unreliable.csv): sec_id, symbol (last), reason. prices() refuses an adjust_mode for them."""
    sec, _ = _identity()
    u = _unreliable()
    out = sec[sec.sec_id.isin(u)][["sec_id", "last_symbol"]].rename(columns={"last_symbol": "symbol"}).reset_index(drop=True)
    out["reason"] = out.sec_id.map(u)
    return out


def clear_cache():
    for f in (_identity, _adjustments, _prices, _prices_year, _intervals, _coverage, _sme_secs, _unreliable, _market, _recon_ranks, _recon_accuracy):
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
           mask_gaps: bool | str = "events") -> pd.DataFrame:
    """Daily prices for the securities that carried `symbols` on `end` (names are resolved at the
    end date, so a renamed company is followed back through its old tickers).
    adjust_mode: None (as published) or 'splits' (splits, bonuses, consolidations, rights; no dividends). as_of: use
    only corporate actions with ex-date <= as_of. With an adjust_mode the frame also has adj_return (daily change of
    adj_close per security) and adj_gap (True on a day where the adjusted series has a documented or unexplained
    break, see adjustment_gaps()). mask_gaps="events" (the default) sets adj_return to NaN on days of a documented
    corporate event the feed cannot quantify (class ON_ACTION_DAY: demerger, scheme; class DEMERGER_ESTIMATED: a
    demerger whose factor is a curated estimate), where the drop is not a real return. UNEXPLAINED moves are NOT masked by default because they can be real crashes (Yes Bank 2020, Satyam
    2009); they are flagged. mask_gaps="all" (or True) masks both, "none" (or False) masks nothing. The days are in
    frame.attrs['flagged']. SME securities and the securities in unreliable_adjusted() are refused with an
    adjust_mode (use adjust_mode=None for their as-published prices)."""
    mask_gaps = {True: "all", False: "none"}.get(mask_gaps, mask_gaps)
    if mask_gaps not in ("events", "all", "none"):
        raise ValueError("mask_gaps must be 'events', 'all' or 'none'")
    if adjust_mode not in (None, "splits"):
        raise ValueError("adjust_mode must be None or 'splits'; dividend (total-return) adjustment is not offered")
    if isinstance(symbols, str):
        symbols = [symbols]
    end_t, start_t = pd.Timestamp(end), pd.Timestamp(start)
    if adjust_mode is not None and start_t < adjust.COVERAGE_START:
        raise CoverageError(
            f"adjusted prices before {adjust.COVERAGE_START.date()} are not verified: the corporate-action feed has almost no "
            f"splits/bonuses before then. The data bank starts on that date: use adjust_mode=None or start later.")
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
    if adjust_mode is not None:
        bad = {sym: _unreliable()[sid] for sym, sid in zip(symbols, sids) if sid in _unreliable()}
        if bad:
            raise CoverageError("adjusted prices are not offered for: " + "; ".join(f"{k} ({v[:80]})" for k, v in bad.items())
                                + ". Use adjust_mode=None for as-published prices.")
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
            if mask_gaps != "none":
                raise
            gaps = pd.DataFrame({"sec_id": [], "date": []})
        est = _adjustments()
        est = est[est.kind == adjust.DEMERGER_EST]
        if len(est):       # an estimated demerger factor fixes the price level, but the day's return is not clean: flag it
            e = est[["sec_id", "eff_date"]].rename(columns={"eff_date": "date"}).assign(**{"class": "DEMERGER_ESTIMATED"})
            keep = gaps[~gaps.set_index(["sec_id", "date"]).index.isin(e.set_index(["sec_id", "date"]).index)] if len(gaps) else gaps
            gaps = pd.concat([x for x in (keep, e) if len(x)], ignore_index=True)
        gk = set(zip(gaps.sec_id, gaps.date))
        gcls = {(s, d): c for s, d, c in zip(gaps.sec_id, gaps.date, gaps.get("class", [""] * len(gaps)))}
        p["adj_gap"] = [(s, d) in gk for s, d in zip(p.sec_id, p.date)]
        p["adj_gap_class"] = [gcls.get((s, d), "") for s, d in zip(p.sec_id, p.date)]
        if mask_gaps == "all":
            p.loc[p["adj_gap"], "adj_return"] = float("nan")
        elif mask_gaps == "events":
            p.loc[p["adj_gap"] & p["adj_gap_class"].isin(["ON_ACTION_DAY", "DEMERGER_ESTIMATED"]), "adj_return"] = float("nan")
    p = p[(p.date >= start_t) & (p.date <= end_t)]
    if adjust_mode is not None:
        fl = p.loc[p.adj_gap, ["sec_id", "date", "adj_gap_class"]].rename(columns={"adj_gap_class": "class"})
        fl = fl.merge(p[["sec_id", "symbol"]].drop_duplicates("sec_id"), on="sec_id", how="left") if "symbol" in p else fl
        p.attrs["flagged"] = fl.reset_index(drop=True)
        if len(fl):
            by = fl.groupby("class").size().to_dict()
            nm = int(len(fl) if mask_gaps == "all" else fl["class"].isin(["ON_ACTION_DAY", "DEMERGER_ESTIMATED"]).sum() if mask_gaps == "events" else 0)
            warnings.warn(f"{len(fl)} flagged adjusted-price day(s) in the result ({by}); returns on {nm} of them were set to NaN "
                          f"(mask_gaps={mask_gaps!r}), the rest are NOT masked. See frame.attrs['flagged'] for the exact days.",
                          DataQualityWarning, stacklevel=2)
    if p.empty:
        raise CoverageError(f"no price rows for {symbols} between {start_t.date()} and {end_t.date()}: "
                            f"no trading session in the range, or the security did not trade in series {series!r}")
    p.attrs["adjust_mode"] = adjust_mode
    p.attrs["as_of"] = None if as_of is None else str(pd.Timestamp(as_of).date())
    return p.sort_values(["sec_id", "date"]).reset_index(drop=True)


def index_values(index: str, start=None, end=None, mask_conflicts: bool = False) -> pd.DataFrame:
    """Official index values (only the verified equity indices are in the build). Adds ret (daily change of close).
    conflict=True marks a day where NSE's two sources disagree; none exists for the indices in this build, and
    mask_conflicts=True would set ret to NaN around one. frame.attrs['flagged'] lists such days."""
    v = indices.values(index)
    if v.empty:
        raise CoverageError(f"no values for index {index!r}: only the verified equity indices (api.coverage()) are in this build")
    v = v.sort_values("date").reset_index(drop=True)
    conf = v["conflict"].fillna(False).astype(bool) if "conflict" in v else pd.Series(False, index=v.index)
    v["ret"] = v["close"].pct_change()
    bad = conf | conf.shift(1, fill_value=False)
    v["ret_unreliable"] = bad
    if mask_conflicts:
        v.loc[bad, "ret"] = float("nan")
    if start is not None:
        v = v[v.date >= pd.Timestamp(start)]
    if end is not None:
        v = v[v.date <= pd.Timestamp(end)]
    v = v.reset_index(drop=True)
    fl = v.loc[v.ret_unreliable, ["date", "close", "alt_close"]].assign(**{"class": "SOURCE_CONFLICT"}) if "alt_close" in v else v.loc[v.ret_unreliable, ["date"]].assign(**{"class": "SOURCE_CONFLICT"})
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


@functools.lru_cache(maxsize=None)
def _recon_ranks() -> pd.DataFrame:
    p = paths.BUILD / "reconstruction" / "ranks.parquet"
    if not p.exists():
        raise CoverageError("no reconstruction in this build: run `nseuniverse reconstruct` (needs archive/raw/market/mii)")
    return pd.read_parquet(p)


@functools.lru_cache(maxsize=None)
def _recon_accuracy() -> pd.DataFrame:
    p = paths.BUILD / "reconstruction" / "accuracy.csv"
    return pd.read_csv(p, parse_dates=["effective"]) if p.exists() else pd.DataFrame()


def reconstruction_accuracy(index: str | None = None) -> pd.DataFrame:
    """How close the rule-based rebuild came to NSE's verified list, at every April/October review that falls inside a
    verified window: one row per index and review (jaccard, precision, recall, how many rebuilt members had an imputed
    size, how many verified members could not be ranked at all). This is the only evidence of how good the unverified
    rebuild is; the same indices are scored only where the truth is known (2010 onward)."""
    a = _recon_accuracy()
    if index is not None:
        k = indices.name_map().get(indices.key(index), indices.key(index))
        a = a[a.index_key == k]
    return a.copy()


def index_start_dates() -> pd.DataFrame:
    """Per index in scope, the dates that matter when choosing how far back to go:
      values_from        first index level NSE publishes (back-calculated before the index existed)
      official_first_list first day of a verified NSE constituent list held (membership_from)
      reliable_from      start of the unbroken verified span
      reconstruct_from   first date index_members(..., reconstruct=True) can return (None when not reconstructable)
      reconstruct_rule   the rank rule used
      rebuild_jaccard    mean overlap of the rebuild with the verified lists where both exist (1.0 = identical)
    The index's public launch date is not in the data bank and is not asserted here."""
    av = index_availability()[["index_key", "index_name", "category", "values_from", "membership_from", "reliable_from"]]
    av = av.rename(columns={"membership_from": "official_first_list"})
    try:
        first = _recon_ranks().effective.min()
    except CoverageError:
        first = pd.NaT
    acc = _recon_accuracy()
    jac = acc.groupby("index_key").jaccard.mean() if len(acc) else pd.Series(dtype=float)
    av["reconstruct_from"] = [first if k in _recon.RULES else pd.NaT for k in av.index_key]
    av["reconstruct_rule"] = [_recon.RULES[k][2] if k in _recon.RULES else "not reconstructed: " + _recon.NOT_RECONSTRUCTED
                              for k in av.index_key]
    av["rebuild_jaccard"] = av.index_key.map(jac)
    return av


def _reconstructed(index: str, k: str, t: pd.Timestamp, first_verified) -> pd.DataFrame:
    if k not in _recon.RULES:
        raise CoverageError(f"{index!r} cannot be reconstructed: {_recon.NOT_RECONSTRUCTED}")
    ranks = _recon_ranks()
    if t < ranks.effective.min():
        raise CoverageError(f"{index!r} cannot be reconstructed on {t.date()}: the first six-month ranking window "
                            f"needs prices from 2007-01-02, so the first review is {ranks.effective.min().date()}")
    g = _recon.members_at(ranks, k, t)
    sec, sh = _identity()
    out = _with_symbols(sec, sh, g.sec_id, t).merge(
        g[["sec_id", "rank", "mcap_avg_cr", "imputed", "effective", "short_window"]], on="sec_id")
    out = out.rename(columns={"imputed": "mcap_imputed", "effective": "rebuilt_review_date"}).sort_values("rank").reset_index(drop=True)
    out["membership_status"] = "RECONSTRUCTED_UNVERIFIED"
    out.attrs["index_first_verified_list"] = first_verified
    jac = reconstruction_accuracy(index).jaccard
    out.attrs["rebuild_jaccard_vs_verified"] = float(jac.mean()) if len(jac) else float("nan")
    warnings.warn(f"{index}: {t.date()} is reconstructed from market-cap ranks (full cap, estimated shares, no free float), not NSE's "
                  f"published membership; first verified list {first_verified.date() if pd.notna(first_verified) else 'none'}; "
                  f"mean overlap with the verified lists {out.attrs['rebuild_jaccard_vs_verified']:.2f}", DataQualityWarning, stacklevel=3)
    return out


def index_members(index: str, as_of, backfill: bool = False, reconstruct: bool = False) -> pd.DataFrame:
    """Members of an index on a date, with the symbol each security carried then.

    reconstruct=True is a second opt-in (not combinable with backfill) for dates that are not verified: it returns the
    rule-based rebuild of reconstruct.py (rank by 6-month average market capitalisation, current methodology bands),
    marked membership_status='RECONSTRUCTED_UNVERIFIED' with rank, mcap_avg_cr and mcap_imputed columns. It is a
    model: shares are estimated, free float is ignored, sectoral indices are refused. Verified dates are never replaced.

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
        if reconstruct:
            if backfill:
                raise ValueError("backfill and reconstruct are different opt-ins; pass one")
            return _reconstructed(index, k, t, first)
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
    sme = n(lambda: len(_sme_secs()))
    cur = n(lambda: len([s for s, r in _unreliable().items() if not r.startswith("SME")]))
    gaps = n(lambda: adjustment_gaps().query("date >= '2007-01-01'").sec_id.nunique())
    feed = n(lambda: str(ev.ex_date.max().date()))
    lag = n(lambda: (lambda r: None if r[0] is None else f"feed ends {r[1].date()}, last bhavcopy {r[2].date()} ({r[0]} days)")(actions.feed_lag()))
    cov = n(lambda: int(_coverage()[_coverage().status == "VERIFIED"].index_key.nunique()))
    counts = {"NOT_SERVED_ADJUSTED": f"{sme + cur} securities",
              "DOCUMENTED_ADJUSTMENT_BREAK": f"{gaps} securities", "UNQUANTIFIED_CORPORATE_ACTIONS": f"{unq} events",
              "FEED_ENDS": f"last ex-date {feed}", "FEED_LAGS_BHAVCOPY": lag,
              "MEMBERSHIP_NOT_VERIFIED": f"{cov} indices have a verified window", "MEMBERSHIP_BACKFILLED": f"{cov} indices can be backfilled",
              "MEMBERSHIP_RECONSTRUCTED": f"{len(_recon.RULES)} indices can be reconstructed"}
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
                add("NOT_SERVED_ADJUSTED", f"{sym}: {un[sid]}")
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
    add("EX_DATE_NOT_ANNOUNCEMENT_DATE", "applies to every adjusted series")
    add("SEC_ID_NOT_STABLE", "applies to every saved sec_id")
    out = pd.DataFrame(rows, columns=["id", "category", "severity", "applies_to", "backtest_impact", "handling"])
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return out.sort_values(["severity", "category", "id"], key=lambda s: s.map(order) if s.name == "severity" else s, kind="mergesort").reset_index(drop=True)


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
