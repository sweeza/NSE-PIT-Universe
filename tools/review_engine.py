"""Steps 3 and 4 of PLAN_BACKFILL_2010.md: ESTIMATED Microcap 250 by NSE's selection rules, scored where truth is known.

Uses prices, verified Nifty 500 membership and the checked share counts. Verified Microcap 250 membership is read only
by score(). Not modelled: impact cost, free float, domicile, ad-hoc replacements between reviews (a stock that enters
Nifty 500 is dropped; the gap is refilled at the next review), the buffer rule (see select()).

    python tools/check_share_counts.py && python tools/review_engine.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nseuniverse import membership  # noqa: E402

STAGE = ROOT / "data" / "staging"
SIZE, TOP_MCAP_OUT, UNIVERSE = 250, 350, 1000
STALE = pd.DateOffset(months=18)


def load():
    px = pd.concat([pd.read_parquet(ROOT / f"data/final/prices/prices_{y}.parquet",
                                    columns=["date", "sec_id", "series", "close", "turnover", "price_factor"])
                    for y in range(2009, 2027)])
    stocks = set()
    for d in ("share_filings", "share_filings_recent"):
        stocks |= {s for s, _ in json.loads((STAGE / d / "securities.json").read_text(encoding="utf-8"))}
    px = px[px.series.isin(["EQ", "BE", "BZ"]) & px.sec_id.isin(stocks)]
    px = px.sort_values(["date", "sec_id", "turnover"]).drop_duplicates(["date", "sec_id"], keep="last")
    sh = pd.read_csv(STAGE / "share_counts.csv", parse_dates=["period_end", "filed"])
    sh = sh[sh.flag != "spike"].copy()
    sh["known"] = sh.filed.where(sh.filed >= sh.period_end, sh.period_end + pd.Timedelta(days=60))
    a = pd.read_parquet(ROOT / "data/final/_work/actions/adjustments.parquet")
    a = a[a.kind.isin(["SPLIT", "BONUS", "CONSOLIDATION", "RIGHTS"])]
    acts = {s: (pd.to_datetime(g.eff_date).values, g.vol_mult.values) for s, g in a.groupby("sec_id")}
    iv = pd.read_parquet(ROOT / "data/final/_work/membership/intervals.parquet")
    return px, sh, acts, iv


def factor(acts, sid, dates) -> np.ndarray:
    out = np.ones(len(dates))
    if sid in acts:
        for d, m in zip(*acts[sid]):
            out[dates >= d] *= m
    return out


def table(cutoff, px, sh, acts, first_seen) -> tuple[pd.DataFrame, float]:
    """Six-month averages per stock and eligibility, using only what was published by the cut-off."""
    w = px[(px.date > cutoff - pd.DateOffset(months=6)) & (px.date <= cutoff)]
    days = w.date.nunique()
    month_days = w.date[w.date > cutoff - pd.DateOffset(months=1)].nunique()
    known = sh[(sh.known <= cutoff) & (sh.period_end > cutoff - STALE)]
    last = known.sort_values(["period_end", "known"]).drop_duplicates("sec_id", keep="last").set_index("sec_id")
    rows = []
    for sid, g in w.groupby("sec_id"):
        new = first_seen[sid] > cutoff - pd.DateOffset(months=6)
        recent = g[g.date > cutoff - pd.DateOffset(months=1)]
        used, need = (recent, month_days) if new else (g, days)
        if not len(used):
            continue
        mcap = np.nan
        if sid in last.index:
            r = last.loc[sid]
            f = factor(acts, sid, used.date.values) / factor(acts, sid, np.array([r.period_end], dtype="datetime64[ns]"))[0]
            mcap = float(np.mean(used.close.values * r.shares * f))
        traded = len(used) >= 0.9 * need and g.series.iloc[-1] != "BZ" and g.date.iloc[-1] >= cutoff - pd.Timedelta(days=10)
        rows.append((sid, mcap, float(used.turnover.mean()), traded))
    t = pd.DataFrame(rows, columns=["sec_id", "mcap", "turnover", "traded"]).set_index("sec_id")
    return t, float(t.mcap.notna().mean())


def select(t: pd.DataFrame, in500: set) -> set:
    """Top 250 of the eligible, afresh at every review.

    NSE's buffer (include anything ranked within the top 675) is left out: read literally it replaced about 200 names a
    review, against 40-73 in the verified lists. This was decided after seeing 2021-2026, so score() is not an
    independent test of it.
    """
    t = t.dropna(subset=["mcap"]).copy()
    t["rank"] = t.mcap.rank(ascending=False, method="first")
    t["trank"] = t.turnover.rank(ascending=False, method="first")
    limit = UNIVERSE
    while True:
        e = t[t.traded & (t["rank"] <= limit) & (t.trank <= limit) & (t["rank"] > TOP_MCAP_OUT) & ~t.index.isin(in500)]
        if len(e) >= SIZE or limit > len(t):
            break
        limit += 100
    return set(e.sort_values("rank").index[:SIZE])


def run(px, sh, acts, iv) -> pd.DataFrame:
    days = pd.DatetimeIndex(sorted(px.date.unique()))
    first_seen = px.groupby("sec_id").date.min().to_dict()
    rows = []
    for year in range(2010, 2027):
        for cut_month, eff_month in ((1, 3), (7, 9)):
            cutoff = pd.Timestamp(year, cut_month, 31)
            end = pd.Timestamp(year, eff_month, 1) + pd.offsets.MonthEnd(0)
            if end > days[-1]:
                continue
            effective = days[days <= end][-1]
            t, counted = table(cutoff, px, sh, acts, first_seen)
            in500 = membership.members(iv, "NIFTY500", effective)
            current = select(t, in500)
            rows += [(effective, s, counted) for s in sorted(current)]
            print(effective.date(), "members", len(current), f"share counts for {counted:.1%} of traded", flush=True)
    return pd.DataFrame(rows, columns=["effective", "sec_id", "share_count_coverage"])


def score(est: pd.DataFrame, px, iv) -> pd.DataFrame:
    adj = px.assign(p=px.close * px.price_factor).pivot_table(index="date", columns="sec_id", values="p")
    dates = sorted(est.effective.unique())
    rows = []
    for i, d in enumerate(dates):
        d = pd.Timestamp(d)
        if d < pd.Timestamp("2021-05-10"):
            continue
        mine = set(est[est.effective == d].sec_id)
        true = membership.members(iv, "NIFTYMICROCAP250", d)
        end = pd.Timestamp(dates[i + 1]) if i + 1 < len(dates) else adj.index[-1]
        def ret(names):     # equal-weighted, bought at the review and held; a stock that stops keeps its last price
            w = adj.loc[d:end, [s for s in names if s in adj.columns]].ffill()
            return float((w.iloc[-1] / w.iloc[0]).dropna().mean() - 1)
        rows.append((d.date(), len(mine & true) / len(true), ret(mine), ret(true), (end - d).days))
    return pd.DataFrame(rows, columns=["review", "in_common", "est_return", "true_return", "days"])


def main():
    px, sh, acts, iv = load()
    est = run(px, sh, acts, iv)
    est.assign(status="ESTIMATED").to_csv(STAGE / "microcap_estimate.csv", index=False)
    s = score(est, px, iv)
    s.to_csv(STAGE / "microcap_score.csv", index=False)
    print(s.round(3).to_string(index=False))
    years = s.days.sum() / 365.25
    a, b = ((1 + s.est_return).prod() ** (1 / years) - 1), ((1 + s.true_return).prod() ** (1 / years) - 1)
    print(f"names in common: mean {s.in_common.mean():.1%}, min {s.in_common.min():.1%}")
    print(f"annualised equal-weighted price return: estimate {a:.1%}, verified {b:.1%}, difference {100 * (a - b):+.1f} points")


if __name__ == "__main__":
    main()
