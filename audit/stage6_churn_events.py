import pandas as pd
B="data/build/"
iv=pd.read_parquet(B+"membership/intervals.parquet"); seg=pd.read_parquet(B+"identity/segments.parquet")
sym=seg.sort_values("end").groupby("sec_id").symbol.last().to_dict()
def sids(s): return set(seg.sec_id[seg.symbol==s])
def inn(k,s,d):
    g=iv[(iv.index_key==k)&iv.sec_id.isin(sids(s))]; d=pd.Timestamp(d)
    return bool(((g.from_date.isna()|(g.from_date<=d))&(g.to_date.isna()|(g.to_date>d))).any())
# churn: entries per year
for k in ["NIFTY50","NIFTYNEXT50","NIFTY100","NIFTY500"]:
    g=iv[iv.index_key==k]; e=g[g.from_date.notna()&(g.from_date>"2007-01-03")].from_date.dt.year.value_counts().sort_index()
    print(k,"entries/yr",e.to_dict())
# known facts (index, symbol, date, expected_in). Dates: first day IN / first day OUT as publicly known.
F=[("NIFTY50","SATYAMCOMP","2009-01-02",True),("NIFTY50","SATYAMCOMP","2009-01-13",True),("NIFTY50","SATYAMCOMP","2009-02-01",False),
   ("NIFTY50","TATAMTRDVR","2016-06-01",True),("NIFTY50","TATAMTRDVR","2017-10-03",False),
   ("NIFTY50","HDFC","2023-06-30",True),("NIFTY50","HDFC","2023-07-20",False),("NIFTY50","LTIM","2023-07-20",True),
   ("NIFTY50","JIOFIN","2023-09-01",False),("NIFTY50","JIOFIN","2023-07-21",False),("NIFTY100","JIOFIN","2023-07-21",True),
   ("NIFTY50","ETERNAL","2025-04-01",False),("NIFTY50","ZOMATO","2025-03-31",False),("NIFTY50","ZOMATO","2025-04-01",False),
   ("NIFTY50","ZOMATO","2025-01-01",False),("NIFTYNEXT50","ZOMATO","2024-08-01",True),
   ("NIFTY50","TRENT","2024-10-01",True),("NIFTY50","BEL","2024-04-01",True),("NIFTY50","SHRIRAMFIN","2024-04-01",True),
   ("NIFTY50","INFY","2010-01-04",True),("NIFTY50","RELIANCE","2007-02-01",True),("NIFTY50","RANBAXY","2008-06-02",True),
   ("NIFTY50","ADANIENT","2022-04-01",True),("NIFTY50","ADANIPORTS","2015-06-01",False),("NIFTY50","ADANIPORTS","2016-06-01",False),("NIFTY50","ADANIPORTS","2019-01-01",True),
   ("NIFTY50","YESBANK","2019-06-03",True),("NIFTY50","YESBANK","2020-04-01",False),("NIFTY50","VEDL","2016-06-01",False),
   ("NIFTYBANK","KOTAKBANK","2010-01-04",True),("NIFTYBANK","YESBANK","2019-01-01",True),("NIFTYBANK","IDFCFIRSTB","2019-01-01",False)]
bad=0
for k,s,d,exp in F:
    if not sids(s): print("  no sec for",s); continue
    got=inn(k,s,d); ok=got==exp; bad+=not ok
    print(("OK  " if ok else "DIFF"),k,s,d,"expected",exp,"got",got)
print("diffs",bad)
