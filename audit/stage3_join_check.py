"""S2-6: verify candidates for 'same symbol + same full equity ISIN across a gap > GAP_DAYS' join.
For every adjacent pair of segments of one symbol that share an equity ISIN, check:
 (a) exact same symbol, shared full ISIN with security-type digits '01' (equity share, not debt)
 (b) no overlapping days (trivially true for one symbol, checked on observed dates)
 (c) nothing between: no segment of the same symbol in the gap, and the ISIN is not observed under ANY other symbol
     (any series) in the gap, and no other ISIN issuer observed under this symbol in the gap
Reads data/build only. Usage: python -I audit/stage3_join_check.py OUTDIR"""
import sys, glob
from pathlib import Path
import pandas as pd
R = Path(__file__).resolve().parents[1]
seg = pd.read_parquet(R/"data/build/identity/segments.parquet")
sh = pd.read_parquet(R/"data/build/identity/symbol_history.parquet")
sec = pd.read_parquet(R/"data/build/identity/securities.parquet").set_index("sec_id")
b = pd.concat([pd.read_parquet(f, columns=["date","symbol","series","isin"]) for f in sorted((R/"data/build/bhavcopy").glob("*.parquet"))])
b = b[b["isin"].notna()]
by_isin = {k: g[["date","symbol"]] for k, g in b.groupby("isin")}
by_sym = {k: g[["date","isin"]] for k, g in b.groupby("symbol")}
eqisin = lambda s: isinstance(s,str) and s[:3]=="INE" and s[7:9]=="01"
rows=[]
for sym, g in sh.sort_values("from_date").groupby("symbol"):
    g = g.reset_index(drop=True)
    for i in range(len(g)-1):
        a, c = g.loc[i], g.loc[i+1]
        ia = {x for x in a.isins.split(",") if eqisin(x)}; ic = {x for x in c.isins.split(",") if eqisin(x)}
        shared = ia & ic
        if not shared: continue
        gap_lo, gap_hi = a.to_date, c.from_date
        notes=[]
        # (c1) ISIN under another symbol inside (or touching) the gap
        for isin in shared:
            o = by_isin[isin]; o = o[(o.symbol!=sym)&(o.date>gap_lo)&(o.date<gap_hi)]
            if len(o): notes.append(f"ISIN {isin} seen under {sorted(o.symbol.unique())} in gap")
        # (c2) other issuers under this symbol in the gap
        s = by_sym[sym]; s = s[(s.date>gap_lo)&(s.date<gap_hi)]
        if len(s): notes.append(f"symbol seen {len(s)} rows in gap, issuers {sorted(set(x[:8] for x in s["isin"]))}")
        # (c3) issuer differs between the two segments' ISIN sets?
        iss = {x[:8] for x in (a.isins+","+c.isins).split(",") if x[:3]=="INE"}
        if len(iss)>1: notes.append(f"several issuers {sorted(iss)}")
        # (d) same security already?
        same_sec = a.sec_id==c.sec_id
        eq = bool(sec.loc[a.sec_id,"is_equity"] and sec.loc[c.sec_id,"is_equity"])
        rows.append(dict(symbol=sym, sec_a=a.sec_id, sec_b=c.sec_id, gap_from=str(gap_lo)[:10], gap_to=str(gap_hi)[:10],
                         gap_days=(c.from_date-a.to_date).days, shared=";".join(sorted(shared)), both_equity=eq,
                         already_same=same_sec, problems=" | ".join(notes)))
d = pd.DataFrame(rows)
out = Path(sys.argv[1]) if len(sys.argv)>1 else Path(".")
d.to_csv(out/"stage3_join_candidates.csv", index=False)
print("candidate pairs (same symbol, shared equity ISIN):", len(d), " already one sec_id:", int(d.already_same.sum()))
c = d[~d.already_same]
print("to join:", len(c), " both is_equity:", int(c.both_equity.sum()), " with problems:", int((c.problems!="").sum()))
print(c[c.problems!=""].to_string(index=False))
print(c[~c.both_equity].to_string(index=False))
print("gap_days min/median/max:", c.gap_days.min(), c.gap_days.median(), c.gap_days.max())
