"""Corporate-action adjustment.

Events are attached to securities by (symbol, ex-date) and moved to the first trading day on or
after the ex-date for that security (the day the price first reflects the action).

For an event with effective trading day e:
  split / bonus / consolidation   price_mult = 1/S      vol_mult = S
  rights  A new per B held at I   price_mult = TERP/P   vol_mult = 1,
          TERP = (P*B + I*A)/(A+B),  P = raw close on the trading day before e
  dividend D (total-return only)  price_mult = (P - D)/P   vol_mult = 1
A row at date t is multiplied by the product over events with t < e (and e <= as_of).
Because only events with ex-date <= as_of enter, the result for any as_of is what an observer
holding the ex-dates up to as_of would compute. (Announcement dates are not needed: an action
has no effect on prices before its ex-date.)

Identity checks: adj_close*adj_volume == close*volume for share-structure events.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SHARE_KINDS = ("SPLIT", "BONUS", "CONSOLIDATION")
# The held NSE corporate-action feed has no share-structure events before May 2006 (2004: none,
# 2005: two) and only a thin trickle through 2006 (6-19 a month against ~80 a year from 2007).
# 2007-01-01 is the first full year; adjusted prices before it are not verified and the API
# refuses them unless explicitly allowed.
COVERAGE_START = pd.Timestamp("2007-01-01")
DIVIDEND_MAX_LAG_DAYS = 7


def attach_events(ev: pd.DataFrame, seg_map: pd.DataFrame, days_by_sec: dict[str, np.ndarray],
                  sec_hist: pd.DataFrame | None = None, sec: pd.DataFrame | None = None) -> pd.DataFrame:
    """Add sec_id and eff_date (first trading day >= ex_date for that security).

    Placement order:
      1. the security that carried the record's symbol on the ex-date;
      2. otherwise (NSE's feed carries today's ticker, not the one in use then) any security that
         ever carried that symbol or ISIN and was trading within 14 days of the ex-date,
         accepted only if exactly one qualifies.
    Rows that cannot be placed get status NO_SECURITY, AMBIGUOUS_SECURITY or NO_TRADING_AFTER."""
    ev = ev.copy()
    ev["sec_id"] = None
    ev["eff_date"] = pd.NaT
    ev["status"] = "OK"
    by_sym = {s: g.sort_values("start") for s, g in seg_map.groupby("symbol")}
    sym_any: dict[str, set] = {}
    isin_any: dict[str, set] = {}
    rng = {}
    if sec_hist is not None and sec is not None:
        for r in sec_hist.itertuples():
            sym_any.setdefault(r.symbol, set()).add(r.sec_id)
            for i in (r.isins.split(",") if r.isins else []):
                isin_any.setdefault(i, set()).add(r.sec_id)
        rng = {r.sec_id: (r.first_date, r.last_date) for r in sec.itertuples()}
    slack = pd.Timedelta(days=14)
    for i, r in ev.iterrows():
        sid = None
        g = by_sym.get(r.symbol)
        if g is not None:
            m = g[(g.start <= r.ex_date) & (g.end >= r.ex_date)]
            if m.empty:
                m = g[(g.start > r.ex_date) & (g.start <= r.ex_date + slack)]
            if not m.empty:
                sid = m.iloc[0].sec_id
        if sid is None and rng:
            cands = set(sym_any.get(r.symbol, set())) | set(isin_any.get(r.isin, set()) if r.isin else set())
            cands = {c for c in cands if rng[c][0] <= r.ex_date + slack and rng[c][1] >= r.ex_date - slack}
            if len(cands) == 1:
                sid = next(iter(cands))
            elif len(cands) > 1:
                ev.at[i, "status"] = "AMBIGUOUS_SECURITY"
                continue
        if sid is None:
            ev.at[i, "status"] = "NO_SECURITY"
            continue
        days = days_by_sec.get(sid)
        if days is None:                       # security never traded in an equity series
            ev.at[i, "sec_id"] = sid
            ev.at[i, "status"] = "NOT_EQUITY"
            continue
        k = days.searchsorted(r.ex_date.to_datetime64(), side="left")
        ev.at[i, "sec_id"] = sid
        if k >= len(days):
            ev.at[i, "status"] = "NO_TRADING_AFTER"
            continue
        ev.at[i, "eff_date"] = pd.Timestamp(days[k])
        # A cash dividend is untestable against prices, so it must land on the real ex-day. If the
        # security did not trade for more than a week after the ex-date (an InvIT that was in a
        # non-equity series then, a long suspension) the first trading day is not the ex-day: the
        # price drop cannot be where the multiplier would put it. Not applied, reported.
        if r.kind == "DIVIDEND" and (ev.at[i, "eff_date"] - r.ex_date).days > DIVIDEND_MAX_LAG_DAYS:
            ev.at[i, "status"] = "NO_TRADING_NEAR"
    return ev


def build_adjustments(ev: pd.DataFrame, close_by_sec: dict[str, pd.Series]) -> pd.DataFrame:
    """Turn attached events into price/volume multipliers. Duplicate listings of the same action
    (same security, effective day, kind, detail) are applied once."""
    ok = ev[(ev.status == "OK") & ev.kind.isin(list(SHARE_KINDS) + ["RIGHTS", "DIVIDEND"])].copy()
    ok = ok.drop_duplicates(["sec_id", "eff_date", "kind", "detail"], keep="first")
    rows = []
    for r in ok.itertuples():
        if r.kind in SHARE_KINDS:
            rows.append((r.sec_id, r.eff_date, r.kind, 1.0 / r.share_factor, r.share_factor, r.detail, r.rec_id))
            continue
        cs = close_by_sec[r.sec_id]
        k = cs.index.searchsorted(r.eff_date, side="left") - 1
        if k < 0:
            continue
        p = float(cs.iloc[k])
        if not np.isfinite(p) or p <= 0:
            continue
        if r.kind == "RIGHTS":
            a, b, i = r.rights_new, r.rights_held, r.issue_price
            terp = (p * b + i * a) / (a + b)
            rows.append((r.sec_id, r.eff_date, "RIGHTS", terp / p, 1.0, r.detail, r.rec_id))
        else:
            if r.amount < p:   # a dividend at or above the price is not a price-continuous event
                rows.append((r.sec_id, r.eff_date, "DIVIDEND", (p - r.amount) / p, 1.0, f"rs {r.amount:g}", r.rec_id))
    out = pd.DataFrame(rows, columns=["sec_id", "eff_date", "kind", "price_mult", "vol_mult", "detail", "rec_id"])
    return out.sort_values(["sec_id", "eff_date", "kind", "rec_id"], kind="mergesort").reset_index(drop=True)


def apply(prices: pd.DataFrame, adj: pd.DataFrame, mode: str = "splits", as_of=None) -> pd.DataFrame:
    """Return prices with adj_* columns. mode: 'splits' (share events + rights) or
    'total_return' (also dividends). as_of: only events with eff_date <= as_of are used."""
    kinds = {"splits": ("SPLIT", "BONUS", "CONSOLIDATION", "RIGHTS"),
             "total_return": ("SPLIT", "BONUS", "CONSOLIDATION", "RIGHTS", "DIVIDEND")}[mode]
    a = adj[adj.kind.isin(kinds)]
    if as_of is not None:
        a = a[a.eff_date <= pd.Timestamp(as_of)]
    p = prices.copy()
    pm = np.ones(len(p)); vm = np.ones(len(p))
    p = p.reset_index(drop=True)
    for sid, g in a.groupby("sec_id", sort=False):
        idx = np.flatnonzero((p["sec_id"] == sid).values)
        if idx.size == 0:
            continue
        d = p["date"].values[idx]
        for r in g.itertuples():
            before = d < np.datetime64(r.eff_date)
            pm[idx[before]] *= r.price_mult
            vm[idx[before]] *= r.vol_mult
    for c in ("open", "high", "low", "close", "last", "prev_close"):
        if c in p:
            p["adj_" + c] = p[c] * pm
    p["adj_volume"] = p["volume"] * vm
    p["price_factor"] = pm
    p["volume_factor"] = vm
    return p


def gate(adj: pd.DataFrame, pc: pd.DataFrame, tol: float = 0.25, near_tol: float = 0.12, k: int = 5,
         min_move: float = 1.5):
    """Evidence gate for share-structure actions.

    A day's combined share factor S is tested against the move NSE actually printed (previous
    close over open, or over close). Actions with |S| too close to 1 to be testable (S < min_move
    and S > 1/min_move) are kept as parsed. A testable day is
      KEPT      if observed/S is within +-tol;
      SHIFTED   if not, but exactly one trading day within +-k sessions matches within near_tol
                (the feed's ex-date was off); the action moves to that day;
      REJECTED  otherwise: the feed claims an action the prices do not show; it is not applied.
    Rights and dividends are not gated. Returns (adjustments, gate_log)."""
    pcs = {sid: g.sort_values("date").reset_index(drop=True) for sid, g in pc.groupby("sec_id")}
    share_kinds = ("SPLIT", "BONUS", "CONSOLIDATION")
    sh = adj[adj.kind.isin(share_kinds)]
    keep_rows, log = [], []
    new_dates = {}
    for (sid, d), g in sh.groupby(["sec_id", "eff_date"]):
        S = float(np.prod(g["vol_mult"]))
        gg = pcs.get(sid)
        row = None
        if gg is not None:
            i = int(gg["date"].searchsorted(d))
            if i < len(gg) and gg["date"].iloc[i] == d:
                row = i
        obs = np.nan
        if row is not None and pd.notna(gg["prev_close_obs"].iloc[row]):
            po = gg["prev_close_obs"].iloc[row]
            cand = [po / x for x in (gg["open"].iloc[row], gg["close"].iloc[row]) if x and x > 0]
            obs = cand[0] if cand else np.nan
            ok = any(S / (1 + tol) <= c <= S * (1 + tol) for c in cand)
        else:
            ok = False
        testable = (S >= min_move or S <= 1 / min_move) and np.isfinite(obs)
        if not testable:
            log.append((sid, d, d, "UNTESTABLE", S, obs)); continue
        if ok:
            log.append((sid, d, d, "KEPT", S, obs)); continue
        hits = []
        for j in range(max(1, row - k), min(len(gg), row + k + 1)):
            po, o = gg["prev_close_obs"].iloc[j], gg["open"].iloc[j]
            if o and o > 0 and pd.notna(po) and abs(po / o / S - 1) <= near_tol:
                hits.append(gg["date"].iloc[j])
        if len(hits) == 1:
            new_dates[(sid, d)] = hits[0]
            log.append((sid, d, hits[0], "SHIFTED", S, obs))
        else:
            log.append((sid, d, pd.NaT, "REJECTED", S, obs))
    gl = pd.DataFrame(log, columns=["sec_id", "eff_date", "applied_date", "decision", "share_factor", "observed_ratio"])
    rej = {(r.sec_id, r.eff_date) for r in gl[gl.decision == "REJECTED"].itertuples()}
    out = []
    for r in adj.itertuples(index=False):
        key = (r.sec_id, r.eff_date)
        if r.kind in share_kinds:
            if key in rej:
                continue
            if key in new_dates:
                r = r._replace(eff_date=new_dates[key])
        out.append(r)
    res = pd.DataFrame(out, columns=adj.columns)
    res = res.sort_values(["sec_id", "eff_date", "kind", "rec_id"], kind="mergesort").reset_index(drop=True)
    return res, gl
