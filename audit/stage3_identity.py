"""Stage 3: identity tests from data/build/identity (read-only), expectations written by the auditor.
SAME = rename of one company (expect one sec_id). DIFF = merger/demerger/other company (expect different sec_id).
The expected outcomes come from the auditor's knowledge of public corporate history, NOT from the project's
data; each pair is listed so the owner can veto any entry."""
import pandas as pd, sys
from pathlib import Path
R = Path(__file__).resolve().parents[1]
sh = pd.read_parquet(R/"data/build/identity/symbol_history.parquet")
sec = pd.read_parquet(R/"data/build/identity/securities.parquet")
seg = pd.read_parquet(R/"data/build/identity/segments.parquet")
SAME = [("INFOSYSTCH","INFY"),("ZEETELE","ZEEL"),("VSNL","TATACOMM"),("HEROHONDA","HEROMOTOCO"),("UTIBANK","AXISBANK"),
 ("HINDLEVER","HINDUNILVR"),("MUNDRAPORT","ADANIPORTS"),("ADANIENTER","ADANIENT"),("IDFCBANK","IDFCFIRSTB"),
 ("PIRAMALHEA","PEL"),("TATAGLOBAL","TATACONSUM"),("SRTRANSFIN","SHRIRAMFIN"),("CADILAHC","ZYDUSLIFE"),
 ("IBULHSGFIN","SAMMAANCAP"),("ZOMATO","ETERNAL"),("PVR","PVRINOX"),("SESAGOA","VEDL"),("SESASTERLITE","VEDL"),
 ("PUNJABNATL","PNB"),("MCDOWELL-N","UNITDSPR"),("ORIENTBANK","PNB"),("LTI","LTIM"),("GESHIPPING","GESHIP"),
 ("CASTROL","CASTROLIND"),("BAJAUTOFIN","BAJFINANCE"),("TATAPOWER","TATAPOWER"),("MAHSCOOTER","MAHSCOOTER"),
 ("RELINFRA","RELINFRA"),("KOTAKMAH","KOTAKBANK"),("JETAIRWAYS","JETAIRWAYS")]
DIFF = [("HDFC","HDFCBANK"),("RANBAXY","SUNPHARMA"),("SATYAMCOMP","TECHM"),("ABIRLANUVO","GRASIM"),
        ("INFRATEL","INDUSTOWER"),("CENTURYTEX","ADITYABIRLA"),("LTI","MINDTREE"),("BANKOFRAJ","ICICIBANK"),
        ("ANDHRABANK","UNIONBANK"),("SYNDIBANK","CANBK"),("ALLAHABAD","INDIANB"),("VIJAYABANK","BANKBARODA")]
def secs(sym):
    return sorted(set(sh.loc[sh.symbol==sym,"sec_id"]))
def isins(s):
    x=set()
    for v in sh.loc[sh.sec_id==s,"isins"]:
        if isinstance(v,str) and v: x|=set(v.replace(";",",").split(","))
    return x
print("== SAME expected"); ok=bad=absent=0
for a,b in SAME:
    sa,sb=secs(a),secs(b)
    if not sa or not sb: print(f" ABSENT {a}->{b}: {a}={sa} {b}={sb}"); absent+=1; continue
    same=bool(set(sa)&set(sb))
    ok+=same; bad+=not same
    iss={s:sorted(isins(s)) for s in set(sa)|set(sb)}
    print(f" {'OK ' if same else 'SPLIT'} {a}->{b} secs {sa}/{sb} isins {iss}")
print("== DIFF expected"); okd=badd=absd=0
for a,b in DIFF:
    sa,sb=secs(a),secs(b)
    if not sa or not sb: print(f" ABSENT {a}/{b}: {sa} {sb}"); absd+=1; continue
    d=not (set(sa)&set(sb)); okd+=d; badd+=not d
    print(f" {'OK ' if d else 'JOINED'} {a}/{b} secs {sa}/{sb}")
print(f"SAME ok {ok} split {bad} absent {absent}; DIFF ok {okd} joined {badd} absent {absd}")
# global invariants (independent of the project's own verify)
m=seg.merge(sec[["sec_id"]],on="sec_id")
# a. no sec_id has two symbols on one day: segments of one sec_id must not overlap
ov=0; ovl=[]
for s,g in seg.sort_values(["sec_id","start"]).groupby("sec_id"):
    if len(g)<2: continue
    ends=g["end"].shift(); o=g[g["start"]<=ends]
    ov+=len(o); ovl+=[(s,*r) for r in o[["symbol","start"]].itertuples(index=False)]
print("overlapping segments inside one sec_id:",ov,ovl[:5])
# b. a sec_id whose segments carry different ISIN issuers
mix=[]
for s,g in sh.groupby("sec_id"):
    iss={i[:8] for v in g["isins"] if isinstance(v,str) and v for i in v.replace(";",",").split(",") if i[:3] in("INE","INF")}
    if len(iss)>1: mix.append((s,sorted(iss),list(g.symbol)))
print("sec_ids with >1 ISIN issuer:",len(mix))
for x in mix[:40]: print("  ",x)
# c. symbols reused by different securities (same symbol, different sec_id) = dangerous direction
reuse=sh.groupby("symbol").sec_id.nunique(); reuse=reuse[reuse>1]
print("symbols used by >1 sec_id:",len(reuse))
rows=[]
for sym in reuse.index:
    g=sh[sh.symbol==sym].sort_values("from_date")
    rows.append((sym,[(r.sec_id,str(r.from_date)[:10],str(r.to_date)[:10],r.isins) for r in g.itertuples()]))
import json; Path(sys.argv[1] if len(sys.argv)>1 else ".").joinpath("stage3_reuse.json").write_text(json.dumps(rows,default=str,indent=0))
