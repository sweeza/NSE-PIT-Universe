import glob, numpy as np, pandas as pd
B="data/build/"
iv=pd.read_parquet(B+"membership/intervals.parquet"); seg=pd.read_parquet(B+"identity/segments.parquet")
sym=seg.sort_values("end").groupby("sec_id").symbol.last()
tr=pd.concat([pd.read_parquet(f,columns=["date","sec_id","series"]) for f in glob.glob(B+"bhavcopy/*.parquet")])
days=pd.DatetimeIndex(sorted(tr.date.unique())); tset=tr.groupby("date").sec_id.agg(set)
def mem(k,d):
    g=iv[iv.index_key==k]; return set(g.sec_id[(g.from_date.isna()|(g.from_date<=d))&(g.to_date.isna()|(g.to_date>d))])
# untraded members NIFTY50
for k in ["NIFTY50","NIFTYMIDCAP50","NIFTYNEXT50"]:
    bad={}
    for d in days[days>="2007-01-02"]:
        u=mem(k,d)-tset[d]
        for s in u: bad.setdefault(sym.get(s,s),[]).append(d)
    print(k,{s:(min(v).date(),max(v).date(),len(v)) for s,v in bad.items()})
# NIFTY500 days with 501
g=iv[iv.index_key=="NIFTY500"]
ds=[d for d in days[days>="2013-08-26"] if len(mem("NIFTY500",d))==501]
print("N500 501-days:",len(ds),ds[0].date(),ds[-1].date())
ys=pd.Series(ds).dt.year.value_counts().sort_index().to_dict(); print(ys)
d=pd.Timestamp("2019-06-03"); print(len(mem("NIFTY500",d)))
