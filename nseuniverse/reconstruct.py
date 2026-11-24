"""Opt-in, UNVERIFIED rule-based reconstruction of index membership for dates before (or between) the verified windows.

This is a model, not NSE's published membership. It applies the size-rank rules of NSE's broad-market methodology
(Method_NIFTY_Equity_Indices.pdf) to the bank's own prices, twice a year, and it is kept apart from the verified
membership: nothing here is read by `verify`, and `api.index_members` returns it only when asked with reconstruct=True.

Inputs and what they cost in accuracy (all measured by accuracy.csv against the verified lists, 2010 onward):
  * Size = 6-month average of close x shares outstanding. The bank holds no shares outstanding before 2024: the issued
    capital of the 2024-2026 security-master snapshots (archive/raw/market/mii) is carried back with the split/bonus/
    consolidation/rights factors of the corporate-action feed. Issues, buy-backs, ESOPs and mergers are not modelled.
  * Securities with no 2024-26 share count (mostly delisted since) get a size imputed from their traded value by a
    cross-sectional log-log fit on the securities that have one (column mcap_imputed).
  * No free float: NSE ranks Nifty 50/Next 50/100/200 by free-float market capitalisation, this uses full market
    capitalisation (NSE itself uses full market capitalisation for Nifty 500 and the Midcap/Smallcap 250/150 family).
  * No F&O eligibility, impact cost or turnover screens, no buffers, no sector classification (sectoral indices are not
    reconstructed).
  * Current methodology bands are applied to every year.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from . import membership, paths

EQUITY_SERIES = ("EQ", "BE", "BZ", "BL", "BT", "IL")
SHARE_KINDS = ("BONUS", "SPLIT", "CONSOLIDATION", "RIGHTS")
WINDOW_DAYS = 126          # about six months of trading days
MIN_SHARE_OF_WINDOW = 0.8  # must trade on 80% of the window's days (stands in for the 6-month seasoning rule)
KEEP_RANKS = 600
SHORT_WINDOW = 100         # fewer window days than this -> short_window flag
FIRST_REVIEW = pd.Timestamp("2007-04-01")   # the first review whose window (from 2007-01-02) holds any data

MII_DIR = paths.ROOT / "archive" / "raw" / "market" / "mii"
OUT = paths.BUILD / "reconstruction"

# index_key -> (first rank, last rank, rule). Ranks are by 6-month average full market capitalisation.
RULES: dict[str, tuple[int, int, str]] = {
    "NIFTY50": (1, 50, "top 50"),
    "NIFTYNEXT50": (51, 100, "ranks 51-100"),
    "NIFTY100": (1, 100, "top 100"),
    "NIFTY200": (1, 200, "top 200"),
    "NIFTY500": (1, 500, "top 500"),
    "NIFTYLARGEMIDCAP250": (1, 250, "top 250"),
    "NIFTYMIDCAP150": (101, 250, "ranks 101-250"),
    "NIFTYSMALLCAP250": (251, 500, "ranks 251-500"),
    "NIFTYMIDSMALLCAP400": (101, 500, "ranks 101-500"),
    "NIFTYMIDSMALLCAP4005050": (101, 500, "ranks 101-500 (50:50 weights are not modelled)"),
    "NIFTYMIDCAP100": (101, 200, "ranks 101-200"),
    "NIFTYMIDCAP50": (101, 150, "ranks 101-150"),
    "NIFTYSMALLCAP100": (251, 350, "ranks 251-350"),
    "NIFTYSMALLCAP50": (251, 300, "ranks 251-300"),
    "NIFTY500MULTICAP502525": (1, 500, "top 500 (25:25:50 weights are not modelled)"),
    "NIFTY500LARGEMIDSMALLEQUALCAPWEIGHTED": (1, 500, "top 500 (equal-cap weights are not modelled)"),
}
NOT_RECONSTRUCTED = "no sector classification in the data bank (sectoral indices need an industry for every stock)"


# ---------------------------------------------------------------- inputs
def load_panel() -> pd.DataFrame:
    """One row per (date, sec_id): close, traded value, ISIN. Equity series only."""
    parts = []
    for f in sorted((paths.BUILD / "bhavcopy").glob("bhavcopy_*.parquet")):
        d = pd.read_parquet(f, columns=["date", "sec_id", "series", "close", "turnover", "isin"])
        parts.append(d[d.series.isin(EQUITY_SERIES) & (d.close > 0)])
    p = pd.concat(parts, ignore_index=True)
    p = p.sort_values(["date", "turnover"], ascending=[True, False]).drop_duplicates(["date", "sec_id"])
    return p.sort_values(["date", "sec_id"]).reset_index(drop=True)


def _mii_files() -> list[tuple[pd.Timestamp, object]]:
    out = []
    for f in MII_DIR.glob("*/NSE_CM_security_*.csv.gz"):
        m = re.search(r"security_(\d{2})(\d{2})(\d{4})", f.name)
        if m:
            out.append((pd.Timestamp(int(m.group(3)), int(m.group(2)), int(m.group(1))), f))
    return sorted(out, key=lambda x: x[0])


def load_shares(sec: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """sec_id, shares_ref, ref_date from the earliest and latest security-master snapshot (issued capital = shares)."""
    files = _mii_files()
    if not files:
        raise FileNotFoundError(f"no security-master snapshots under {MII_DIR}; restore archive/raw/market/mii first")
    pairs = pd.concat([panel[["sec_id", "isin"]].dropna().drop_duplicates().rename(columns={"isin": "ISIN"}),
                       sec[["sec_id", "isin_last"]].dropna().rename(columns={"isin_last": "ISIN"})]).drop_duplicates()
    pairs = pairs.merge(sec[["sec_id", "last_date"]], on="sec_id").sort_values("last_date")
    isin_sec = pairs.drop_duplicates("ISIN", keep="last").set_index("ISIN").sec_id
    got = []
    for dt, f in (files[0], files[-1]):
        d = pd.read_csv(f, compression="gzip", usecols=["SctySrs", "ISIN", "IssdCptl"], low_memory=False)
        d = d[d.SctySrs.isin(EQUITY_SERIES) & d.ISIN.notna() & (d.IssdCptl > 0)].drop_duplicates("ISIN")
        d["sec_id"] = d.ISIN.map(isin_sec)
        d = d.dropna(subset=["sec_id"]).drop_duplicates("sec_id")
        got.append(pd.DataFrame({"sec_id": d.sec_id, "shares_ref": d.IssdCptl.astype(float), "ref_date": dt}))
    return pd.concat(got).drop_duplicates("sec_id", keep="first").reset_index(drop=True)   # earliest snapshot wins


def share_events() -> pd.DataFrame:
    a = pd.read_parquet(paths.BUILD / "actions" / "adjustments.parquet")
    a = a[a.kind.isin(SHARE_KINDS) & a.vol_mult.notna() & (a.vol_mult != 1)].sort_values(["sec_id", "eff_date"])
    a["cum"] = a.groupby("sec_id").vol_mult.cumprod()
    return a.groupby(["sec_id", "eff_date"], as_index=False).cum.last()


def _shares_on(rows: pd.DataFrame, ref: pd.DataFrame, ev: pd.DataFrame) -> pd.Series:
    """Shares outstanding on each row's date: the snapshot count divided by the share factors after that date."""
    r = rows[["sec_id", "date"]].reset_index().merge(ref, on="sec_id", how="left")
    e = ev.sort_values("eff_date")
    r = r.sort_values("date")
    r = pd.merge_asof(r, e.rename(columns={"eff_date": "date", "cum": "cum_d"}), on="date", by="sec_id")
    # cumulative factor at the snapshot date, per security
    er = ev.merge(ref[["sec_id", "ref_date"]], on="sec_id")
    er = er[er.eff_date <= er.ref_date].sort_values("eff_date").groupby("sec_id").cum.last().rename("cum_ref")
    r = r.merge(er, left_on="sec_id", right_index=True, how="left")
    after = r.cum_ref.fillna(1.0) / r.cum_d.fillna(1.0)
    r["shares"] = r.shares_ref / after
    return r.set_index("index").shares.reindex(rows.index)


# ---------------------------------------------------------------- ranking
def review_dates(days: pd.DatetimeIndex) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """(effective day, last window day) for each April and October review: the window ends 31 January / 31 July."""
    out = []
    for y in range(FIRST_REVIEW.year, days.max().year + 1):
        for m in (4, 10):
            nominal = pd.Timestamp(y, m, 1)
            if nominal < FIRST_REVIEW or nominal > days.max():
                continue
            eff = days[days >= nominal][0]
            wend = days[days <= pd.Timestamp(y, m - 3, 1) + pd.offsets.MonthEnd(0)][-1]
            out.append((eff, wend))
    return out


def rank_all(panel: pd.DataFrame, sec: pd.DataFrame, ref: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    days = pd.DatetimeIndex(np.sort(panel.date.unique()))
    sec_info = sec.set_index("sec_id")
    # INF ISINs are funds and ETFs; stocks carry INE (or older IN0/IN1/IN2/IN9 forms)
    stock_like = sec_info.is_equity & ~sec_info.isin_last.str.startswith("INF", na=False)
    dates = panel.date.to_numpy()
    out = []
    for eff, wend in review_dates(days):
        wdays = days[days <= wend][-WINDOW_DAYS:]
        if len(wdays) == 0:
            continue
        lo, hi = np.searchsorted(dates, wdays[0].to_datetime64(), "left"), np.searchsorted(dates, wdays[-1].to_datetime64(), "right")
        w = panel.iloc[lo:hi].copy()
        w["shares"] = _shares_on(w, ref, ev)
        w["mcap"] = w.close * w.shares
        g = w.groupby("sec_id").agg(n_obs=("close", "size"), turn=("turnover", "mean"), mcap=("mcap", "mean"))
        g = g[(g.n_obs >= MIN_SHARE_OF_WINDOW * len(wdays)) & (g.turn > 0)]
        g = g[g.index.map(lambda s: bool(stock_like.get(s, False)) and sec_info.last_date[s] >= eff)]
        have = g.mcap.notna() & (g.mcap > 0)
        g["imputed"] = ~have
        if have.sum() >= 30 and (~have).any():
            b, a = np.polyfit(np.log(g.turn[have]), np.log(g.mcap[have]), 1)
            g.loc[~have, "mcap"] = np.exp(a + b * np.log(g.turn[~have]))
        g = g[g.mcap.notna()].sort_values("mcap", ascending=False).head(KEEP_RANKS)
        g["rank"] = np.arange(1, len(g) + 1)
        g["effective"], g["window_end"], g["window_days"] = eff, wend, len(wdays)
        g["short_window"] = len(wdays) < SHORT_WINDOW
        out.append(g.reset_index())
    r = pd.concat(out, ignore_index=True)
    r["mcap_avg_cr"] = r.mcap / 1e7
    return r[["effective", "window_end", "sec_id", "rank", "mcap_avg_cr", "imputed", "n_obs", "window_days", "short_window"]]


# ---------------------------------------------------------------- accuracy against the verified lists
def accuracy(ranks: pd.DataFrame, intervals: pd.DataFrame, coverage: pd.DataFrame) -> pd.DataFrame:
    rows = []
    ver = coverage[coverage.status == "VERIFIED"]
    for k, (lo, hi, _) in RULES.items():
        w = ver[ver.index_key == k]
        for eff, g in ranks.groupby("effective"):
            if not ((w.from_date <= eff) & (w.to_date >= eff)).any():
                continue
            truth = membership.members(intervals, k, eff)
            band = g[(g["rank"] >= lo) & (g["rank"] <= hi)]
            mine = set(band.sec_id)
            inter = len(truth & mine)
            rows.append((k, eff, len(truth), len(mine), inter, inter / max(len(truth | mine), 1),
                         inter / max(len(mine), 1), inter / max(len(truth), 1), int(band.imputed.sum()),
                         len(truth - set(g.sec_id))))
    return pd.DataFrame(rows, columns=["index_key", "effective", "n_verified", "n_rebuilt", "overlap", "jaccard", "precision",
                                       "recall", "imputed_in_rebuilt", "verified_not_rankable"])


def build(root=None) -> dict:
    out = (root or paths.BUILD) / "reconstruction"
    out.mkdir(parents=True, exist_ok=True)
    sec = pd.read_parquet(paths.BUILD / "identity" / "securities.parquet")
    panel = load_panel()
    ref = load_shares(sec, panel)
    ranks = rank_all(panel, sec, ref, share_events())
    ranks.to_parquet(out / "ranks.parquet", index=False)
    acc = accuracy(ranks, pd.read_parquet(paths.BUILD / "membership" / "intervals.parquet"),
                   pd.read_parquet(paths.BUILD / "membership" / "coverage.parquet"))
    acc.to_csv(out / "accuracy.csv", index=False)
    return {"reviews": int(ranks.effective.nunique()), "securities_with_shares": int(len(ref)),
            "accuracy_rows": int(len(acc)), "mean_jaccard": float(acc.jaccard.mean()) if len(acc) else float("nan")}


# ---------------------------------------------------------------- serving
def members_at(ranks: pd.DataFrame, index_key: str, as_of) -> pd.DataFrame:
    """Rebuilt members from the latest review on or before as_of (empty frame if none)."""
    lo, hi, _ = RULES[index_key]
    t = pd.Timestamp(as_of)
    eff = ranks.effective[ranks.effective <= t]
    if eff.empty:
        return ranks.iloc[0:0]
    g = ranks[ranks.effective == eff.max()]
    return g[(g["rank"] >= lo) & (g["rank"] <= hi)].reset_index(drop=True)
