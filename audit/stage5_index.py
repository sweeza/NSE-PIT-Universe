"""Stage 5.1: independent comparison of daily-file and history-API index closes. Own code.
Usage: python -I audit/stage5_index.py outdir"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
R = Path(__file__).resolve().parents[1]; OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 200)
d = pd.read_parquet(R / "data/build/indices/index_daily.parquet"); h = pd.read_parquet(R / "data/build/indices/index_history.parquet")
print("daily dup keys", d.duplicated(["index_key","date"]).sum(), "history dup keys", h.duplicated(["index_key","date"]).sum())
m = d[["index_key","date","close"]].merge(h[["index_key","date","close"]], on=["index_key","date"], suffixes=("_d","_h"))
m["rel"] = (m.close_d/m.close_h - 1)
print("overlap rows", len(m), "indices", m.index_key.nunique())
for t in (1e-6, 1e-4, 1e-3, 1e-2):
    print(f"|rel|>{t:g}:", int((m.rel.abs()>t).sum()))
c = m[m.rel.abs()>1e-3]
print("conflicts >0.1%:", len(c), "indices", c.index_key.nunique())
print(c.groupby("index_key").size().sort_values(ascending=False).head(30))
print("rel quantiles of conflicts:", c.rel.abs().quantile([.5,.9,.99,1]).to_dict())
# sources: is one side a shifted day? test whether daily close equals history close of neighbouring day
h2 = h.sort_values(["index_key","date"]).copy(); h2["prev_h"]=h2.groupby("index_key").close.shift(1); h2["next_h"]=h2.groupby("index_key").close.shift(-1)
c = c.merge(h2[["index_key","date","prev_h","next_h"]], on=["index_key","date"], how="left")
c["matches_prev"] = (c.close_d/c.prev_h-1).abs()<1e-4; c["matches_next"] = (c.close_d/c.next_h-1).abs()<1e-4
print("conflicts where daily == history of previous day:", int(c.matches_prev.sum()), "next day:", int(c.matches_next.sum()))
# by year
print(c.groupby(c.date.dt.year).size().to_dict())
c.to_csv(OUT/"stage5_conflicts.csv", index=False)
# which source does market logic favour? Daily-return vs neighbours: a conflict is "history-off" if history's day-to-day jump is larger than daily's
d2 = d.sort_values(["index_key","date"]).copy(); d2["ret_d"]=d2.groupby("index_key").close.pct_change()
h2["ret_h"]=h2.groupby("index_key").close.pct_change()
x = c.merge(d2[["index_key","date","ret_d"]],on=["index_key","date"]).merge(h2[["index_key","date","ret_h"]],on=["index_key","date"])
print("conflict days: median |ret| daily", x.ret_d.abs().median(), "history", x.ret_h.abs().median())
print(x.groupby("index_key").size().sort_values(ascending=False).head(3))
# Nifty 100 Low Vol 30 detail
lv = c[c.index_key.str.contains("LOWVOL")]
print(lv.groupby("index_key").agg(n=("rel","size"), first=("date","min"), last=("date","max"), mean_rel=("rel","mean")))
# missing days: dates in one source not the other, within the span both cover
sp = pd.concat([d.groupby("index_key").date.agg(["min","max"]).add_prefix("d_"), h.groupby("index_key").date.agg(["min","max"]).add_prefix("h_")],axis=1).dropna()
miss=[]
for k,r in sp.iterrows():
    lo,hi=max(r.d_min,r.h_min),min(r.d_max,r.h_max)
    dd=set(d[(d.index_key==k)&d.date.between(lo,hi)].date); hh=set(h[(h.index_key==k)&h.date.between(lo,hi)].date)
    miss.append((k,len(dd-hh),len(hh-dd)))
mm=pd.DataFrame(miss,columns=["index_key","only_daily","only_history"]); print("days in one source only (overlap span):", int(mm.only_daily.sum()), int(mm.only_history.sum()))
print(mm[(mm.only_daily>0)|(mm.only_history>0)].sort_values("only_history",ascending=False).head(10))
