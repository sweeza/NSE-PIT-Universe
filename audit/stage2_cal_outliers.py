"""Stage 2.2 / 2.3: calendar anomalies and raw-table outlier scan (read-only on data/build)."""
import sys
from pathlib import Path
import pandas as pd, numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
b = pd.concat([pd.read_parquet(f) for f in sorted((ROOT / "data/build/bhavcopy").glob("*.parquet"))], ignore_index=True)
days = pd.DatetimeIndex(sorted(b["date"].unique()))
print("days", len(days), days.min().date(), days.max().date())

# --- calendar
wk = days[days.dayofweek >= 5]
print("weekend sessions", len(wk))
rows_per = b.groupby("date").size()
for d in wk: print("  ", d.date(), d.day_name(), "rows", rows_per[d])
allw = pd.bdate_range(days.min(), days.max())
non = allw.difference(days)
print("weekday non-sessions", len(non))
non_s = pd.Series(non)
print(non_s.dt.year.value_counts().sort_index().to_dict())
# fixed national holidays that must never be sessions
bad_sessions = [d.date() for d in days if (d.month, d.day) in {(1, 26), (8, 15), (10, 2)} and d.dayofweek < 5]
print("sessions on Jan26/Aug15/Oct2:", bad_sessions)
# long gaps (>= 5 weekdays missing in a row)
gaps = []
run = []
for d in allw:
    if d in non: run.append(d)
    else:
        if len(run) >= 4: gaps.append((run[0].date(), run[-1].date(), len(run)))
        run = []
print("runs of >=4 consecutive missing weekdays:", gaps)
# thin days
thin = rows_per[rows_per < 0.5 * rows_per.rolling(21, min_periods=5).median()]
print("thin days (<50% of 21d median rows):", [(d.date(), int(n)) for d, n in thin.items()])
pd.Series(non).dt.date.to_csv(OUT / "weekday_nonsessions.csv", index=False, header=["date"])

# --- outliers
eq = b[b["series"].isin(["EQ", "BE", "BZ", "SM", "ST"])]
def rep(name, m, show=["date", "symbol", "series", "open", "high", "low", "close", "volume", "trades"]):
    print(f"{name}: {int(m.sum())}")
    if m.sum(): print(b.loc[m.index[m], show].head(8).to_string(index=False)) if False else print(m[m].index[:0])
checks = {}
t = b
checks["high<low"] = t["high"] < t["low"]
checks["close>high"] = t["close"] > t["high"]
checks["close<low"] = t["close"] < t["low"]
checks["open>high"] = t["open"] > t["high"]
checks["open<low"] = t["open"] < t["low"]
checks["neg price"] = (t[["open", "high", "low", "close"]] < 0).any(axis=1)
checks["zero close"] = t["close"] == 0
checks["neg volume"] = t["volume"] < 0
checks["vol0 w/ trades>0"] = (t["volume"] == 0) & (t["trades"] > 0)
checks["vol>0 w/ trades==0"] = (t["volume"] > 0) & (t["trades"] == 0)
checks["vol>0 close==0"] = (t["volume"] > 0) & (t["close"] == 0)
for k, m in checks.items():
    print(f"{k}: {int(m.sum())}")
    if m.sum():
        print("   by year", t.loc[m, "date"].dt.year.value_counts().sort_index().to_dict())
        print(t.loc[m, ["date", "symbol", "series", "open", "high", "low", "close", "volume", "trades"]].head(5).to_string(index=False))
dup = b.duplicated(["date", "symbol", "series"]).sum()
print("duplicate (date,symbol,series):", dup)
# jumps in EQ series >50% day over day (same symbol), flag with prev_close consistency
e = b[b["series"] == "EQ"].sort_values(["symbol", "date"]).copy()
e["pc"] = e.groupby("symbol")["close"].shift()
e["ret"] = e["close"] / e["pc"] - 1
big = e[(e["ret"].abs() > 0.5) & e["pc"].notna()]
print("EQ |close/prev close-1|>50%:", len(big))
# those where file's own prev_close agrees with prior close (i.e. NOT adjusted by NSE on the day -> real jump)
big = big.assign(pc_match=(big["prev_close"].round(2) == big["pc"].round(2)))
print("  of which prev_close in file equals previous close (unadjusted jump):", int(big["pc_match"].sum()))
big.to_csv(OUT / "stage2_jumps.csv", index=False)
print(big.groupby(big["date"].dt.year).size().to_dict())
