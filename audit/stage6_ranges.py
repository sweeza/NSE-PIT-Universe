import glob, numpy as np, pandas as pd
B="data/build/"
iv=pd.read_parquet(B+"membership/intervals.parquet")
cov=pd.read_parquet(B+"membership/coverage.parquet")
days=pd.DatetimeIndex(sorted(pd.concat([pd.read_parquet(f,columns=["date"]) for f in glob.glob(B+"bhavcopy/*.parquet")]).date.unique()))
OFF={"NIFTY50":50,"NIFTY100":100,"NIFTY200":200,"NIFTYNEXT50":50,"NIFTYLARGEMIDCAP250":250,"NIFTYMIDSMALLCAP400":400,"NIFTYSMALLCAP250":250}
dc=pd.read_csv("data/curated/index_dual_class.csv",dtype=str); ex=pd.read_csv("data/curated/index_size_exceptions.csv",dtype=str)
for k,n in OFF.items():
    g=iv[iv.index_key==k]; f=g.from_date.fillna(pd.Timestamp("1900-01-01")).values; t=g.to_date.fillna(pd.Timestamp("2262-01-01")).values
    v=cov[(cov.index_key==k)&(cov.status=="VERIFIED")]
    dd=[d for d in days if any(r.from_date<=d<=r.to_date for r in v.itertuples())]
    sz=np.array([((f<=np.datetime64(d))&(t>np.datetime64(d))).sum() for d in dd])
    over=np.array(dd)[sz!=n]
    rng=[];s=None;p=None
    for d in over:
        if s is None: s=d
        elif (d-p).days>5: rng.append((s,p)); s=d
        p=d
    if s is not None: rng.append((s,p))
    print(k,"off-size ranges:",[(a.date().isoformat(),b.date().isoformat()) for a,b in rng])
    print("   dual-class rows:",[(r.from_date,r.to_date,r.symbols) for r in dc[dc.index_key==k].itertuples()])
