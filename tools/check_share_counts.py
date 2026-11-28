"""Step 2 of PLAN_BACKFILL_2010.md: turn downloaded filings into checked share counts.

Writes data/staging/share_counts.csv (one row per security and period end) with a flag:
  ok            agrees with its neighbours once splits and bonuses are allowed for
  unit_fixed    was off by a power of ten from its neighbours and has been rescaled
  step          a lasting change with no split or bonus to explain it (issue, merger, buy-back): kept
  spike         disagrees with both neighbours, which agree with each other: do not use
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "data" / "staging"
TOL = 0.25          # relative change treated as a jump


def load() -> pd.DataFrame:
    rows = []
    for folder in ("share_filings", "share_filings_recent"):
        with open(STAGE / folder / "filings.jsonl", encoding="utf-8") as f:
            rows += [{k: v for k, v in json.loads(line).items() if k != "body"} for line in f]
    t = pd.DataFrame(rows)
    t = t[(t.paid_up > 0) & (t.face_value > 0)].copy()
    # the JSON detail pages state paid-up capital in lakhs, XBRL files in rupees
    t["shares"] = t.paid_up / t.face_value * np.where(t.url.str.contains("/api/"), 1e5, 1.0)
    t["period_end"] = pd.to_datetime(t.period_end)
    t["filed"] = pd.to_datetime(t.filed, format="mixed", dayfirst=True, errors="coerce")
    return t.sort_values(["sec_id", "period_end", "filed"]).drop_duplicates(["sec_id", "period_end"], keep="first")


def near(a: float, b: float) -> bool:
    return abs(a / b - 1) <= TOL


def check(t: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    out = []
    by_sec = {s: g for s, g in actions.groupby("sec_id")}
    for sid, g in t.groupby("sec_id"):
        g = g.copy()
        ev = by_sec.get(sid)
        # shares on one common basis: divide out every split/bonus that had taken effect by the period end
        factor = np.ones(len(g))
        if ev is not None:
            for r in ev.itertuples():
                factor[g.period_end.values >= np.datetime64(r.eff_date)] *= r.vol_mult
        adj = g.shares.values / factor
        # a count filed around an ex-date may be on either side of it: allow the neighbouring factor
        if ev is not None:
            for i in range(len(g)):
                around = [r.vol_mult for r in ev.itertuples() if abs((g.period_end.iloc[i] - r.eff_date).days) <= 100]
                ref = np.median(adj[max(0, i - 3): i + 4])
                for m in around:
                    for alt in (adj[i] * m, adj[i] / m):
                        if not near(adj[i], ref) and near(alt, ref):
                            adj[i] = alt
        flag = np.array(["ok"] * len(g), dtype=object)
        fix = np.ones(len(g))
        mid = np.median(adj)
        for i in range(len(g)):                        # unit slips: a whole power of ten away from the typical value
            ref = np.median(adj[max(0, i - 4): i + 5])
            for base in (ref, mid):
                k = round(np.log10(adj[i] / base))
                if abs(k) >= 2 and near(adj[i] / 10.0 ** k, base):
                    fix[i], flag[i] = 10.0 ** -k, "unit_fixed"
                    break
        adj = adj * fix
        for i in range(len(g)):
            prev = adj[i - 1] if i else None
            nxt = adj[i + 1] if i + 1 < len(g) else None
            off_prev = prev is not None and not near(adj[i], prev)
            off_next = nxt is not None and not near(adj[i], nxt)
            if off_prev and off_next and near(prev, nxt):
                flag[i] = "spike"
            elif (prev is None and off_next) or (nxt is None and off_prev):
                if len(g) > 2 and not near(adj[i], np.median(adj)):
                    flag[i] = "step"
            elif off_prev and flag[i - 1] != "spike":
                flag[i] = "step"
        g["shares"] = g.shares * fix
        g["flag"] = flag
        out.append(g)
    return pd.concat(out)[["sec_id", "symbol", "period_end", "filed", "shares", "face_value", "paid_up", "flag"]]


def main():
    a = pd.read_parquet(ROOT / "data/final/_work/actions/adjustments.parquet")
    a = a[a.kind.isin(["SPLIT", "BONUS", "CONSOLIDATION", "RIGHTS"])].copy()
    a["eff_date"] = pd.to_datetime(a.eff_date)
    r = check(load(), a)
    r.to_csv(STAGE / "share_counts.csv", index=False)
    print(len(r), "rows,", r.sec_id.nunique(), "securities")
    print(r.flag.value_counts().to_string())
    # test against known splits and bonuses: does the filed count actually move by the stated factor?
    hit = tot = 0
    by_sec = {s: g[g.flag != "spike"] for s, g in r.groupby("sec_id")}
    for e in a[(a.kind != "RIGHTS") & a.eff_date.between("2009-01-01", "2021-06-30")].itertuples():
        g = by_sec.get(e.sec_id)
        if g is None:
            continue
        before = g[g.period_end < e.eff_date - pd.Timedelta(days=100)].tail(1)
        after = g[g.period_end > e.eff_date + pd.Timedelta(days=100)].head(1)
        if len(before) and len(after) and (after.period_end.iloc[0] - before.period_end.iloc[0]).days < 500:
            tot += 1
            hit += near(after.shares.iloc[0] / before.shares.iloc[0], e.vol_mult)
    print(f"splits/bonuses where the filed count moved by the stated factor (+-{TOL:.0%}): {hit} of {tot}")


if __name__ == "__main__":
    main()
