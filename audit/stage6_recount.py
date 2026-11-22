"""Stage 6.1/6.2: independent recount of membership from intervals.parquet (no project code)."""
import glob, sys
import numpy as np, pandas as pd
B = "data/build/"
iv = pd.read_parquet(B + "membership/intervals.parquet")
cov = pd.read_parquet(B + "membership/coverage.parquet")
print("interval cols", list(iv.columns)); print("cov cols", list(cov.columns))
days = sorted(set(pd.concat([pd.read_parquet(f, columns=["date"]) for f in glob.glob(B + "bhavcopy/*.parquet")]).date))
days = pd.DatetimeIndex(days)
traded = pd.concat([pd.read_parquet(f, columns=["date", "sec_id", "series"]) for f in glob.glob(B + "bhavcopy/*.parquet")])
traded = traded[traded.series.isin(["EQ","BE","BZ","SM","ST","BL","IL","RR","IV"])]
tset = traded.groupby("date").sec_id.agg(set)
OFFICIAL = {"NIFTY50":50,"NIFTYNEXT50":50,"NIFTY100":100,"NIFTY200":200,"NIFTY500":500,"NIFTYMIDCAP50":50,"NIFTYMIDCAP100":100,
            "NIFTYMIDCAP150":150,"NIFTYSMALLCAP50":50,"NIFTYSMALLCAP100":100,"NIFTYSMALLCAP250":250,"NIFTYLARGEMIDCAP250":250,
            "NIFTYMIDSMALLCAP400":400,"NIFTYBANK":None}
ver = cov[cov.status == "VERIFIED"]
rows = []
for k, g in ver.groupby("index_key"):
    gi = iv[iv.index_key == k]
    f = np.where(gi.from_date.isna(), np.datetime64("1900-01-01"), gi.from_date.values.astype("datetime64[ns]"))
    t = np.where(gi.to_date.isna(), np.datetime64("2262-01-01"), gi.to_date.values.astype("datetime64[ns]"))
    sizes, untraded, nd = {}, 0, 0
    for r in g.itertuples():
        for d in days[(days >= r.from_date) & (days <= r.to_date)]:
            m = (f <= np.datetime64(d)) & (t > np.datetime64(d))
            ids = set(gi.sec_id.values[m]); nd += 1
            sizes[len(ids)] = sizes.get(len(ids), 0) + 1
            untraded += len(ids - tset.get(d, set()))
    rows.append((k, nd, OFFICIAL.get(k), dict(sorted(sizes.items())), untraded))
for r in rows: print(r)
