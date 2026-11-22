"""S2-6 effect check, in memory only (writes nothing to data/build): run identity.build with the new rule on the
current bhavcopy table, map old sec_id -> new sec_id, and compare to intervals.parquet / events / actions."""
import sys
from pathlib import Path
import pandas as pd
R = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(R))
from nseuniverse import identity
t = pd.concat([pd.read_parquet(f) for f in sorted((R/"data/build/bhavcopy").glob("*.parquet"))], ignore_index=True)
old = t[["symbol","date","sec_id"]].drop_duplicates(["symbol","date"])
sec, sh, links, segmap = identity.build(t)
t2 = identity.attach(t[["date","symbol","series","isin"]], segmap)[["symbol","date","sec_id"]].drop_duplicates(["symbol","date"])
m = old.merge(t2, on=["symbol","date"], suffixes=("_old","_new"))
mp = m[["sec_id_old","sec_id_new"]].drop_duplicates()
print("old securities", old.sec_id.nunique(), "new securities", len(sec), "joins:", (links.source=="symbol_isin").sum(), links[links.source=="symbol_isin"].status.value_counts().to_dict())
print("old ids mapping to >1 new id:", int((mp.groupby("sec_id_old").size()>1).sum()))
g = mp.groupby("sec_id_new").sec_id_old.apply(list); g = g[g.str.len()>1]
print("new ids that merge several old ids:", len(g), "old ids absorbed:", int(g.str.len().sum()))
# membership
iv = pd.read_parquet(R/"data/build/membership/intervals.parquet")
mpd = dict(zip(mp.sec_id_old, mp.sec_id_new))
iv["new"] = iv.sec_id.map(mpd)
print("interval rows:", len(iv), "unmapped:", int(iv.new.isna().sum()))
# any index in which two merged old ids are both members (overlap risk)
merged_old = {o for l in g for o in l}
x = iv[iv.sec_id.isin(merged_old)]
print("interval rows touching merged ids:", len(x), "ids:", sorted(x.sec_id.unique()))
grp = x.groupby(["index_key","new"]).sec_id.nunique()
print("(index, new id) pairs where >1 old id is a member:", int((grp>1).sum()))
# interval dates unchanged by construction; check membership-relevant: bhavcopy rows per (symbol,date) get one id each
print("rows with changed id mapping count:", int((m.sec_id_old!=m.sec_id_new).sum()), "of", len(m))
# id renumbering: how many old ids keep their label
print("old ids whose label changes under renumbering:", int((mp.sec_id_old!=mp.sec_id_new).sum()), "of", len(mp))
# whether merged ids carry events/adjustments
ev = pd.read_parquet(R/"data/build/actions/events.parquet", columns=["sec_id","ex_date","kind","status"])
e = ev[ev.sec_id.isin(merged_old)]
print("action events on merged ids:", len(e), "kinds:", e.kind.value_counts().to_dict())
