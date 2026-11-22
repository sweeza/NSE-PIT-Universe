"""Stage 5.2: Nifty 50 / Nifty 100 daily return vs equal-weight return of the members held on that day (NSE prev_close->close, no adjustment needed)."""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
R = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(R))
from nseuniverse import api
OUT = Path(sys.argv[1])
h = pd.read_parquet(R/"data/build/indices/index_history.parquet")
for key, step in (("NIFTY50", 3), ("NIFTY100", 7)):
    s = h[h.index_key == key].set_index("date").close.sort_index(); r = s.pct_change()
    cov = api.coverage(); cov = cov[(cov.index_key == key) & (cov.status == "VERIFIED")]
    days = [d for d in s.index if ((cov.from_date <= d) & (cov.to_date >= d)).any() and d >= pd.Timestamp("2007-01-01")][::step]
    rows = []
    for d in days:
        try:
            m = api.index_members(key, d)
            px = api.bhavcopy_day(d)
        except Exception as e:
            continue
        px = px[px.series == "EQ"]; px = px[px.sec_id.isin(m.sec_id)].drop_duplicates("sec_id")
        ret = (px.close / px.prev_close - 1)
        rows.append((d, ret.mean(), len(px), len(m), r.get(d, np.nan)))
    t = pd.DataFrame(rows, columns=["date", "ew", "n_priced", "n_members", "idx"]).dropna()
    t["diff"] = t.idx - t.ew
    print(key, "days", len(t), "corr", round(t.ew.corr(t.idx), 4), "mean |diff|", round(t["diff"].abs().mean(), 5),
          "days with <90% of members priced:", int((t.n_priced < 0.9 * t.n_members).sum()))
    low = t[(t["diff"].abs() > 0.01) | (t.n_priced < 0.9 * t.n_members)]
    print(" worst |diff| days:", len(low)); t.to_csv(OUT/f"stage52_{key}.csv", index=False)
    print(t.assign(a=t["diff"].abs()).sort_values("a", ascending=False).head(8)[["date","ew","idx","n_priced","n_members"]].to_string())
    # corr by year
    print(t.groupby(t.date.dt.year).apply(lambda g: g.ew.corr(g.idx)).round(3).to_dict())
