"""Stage 2.4: third-party close check. Source: Yahoo Finance public chart endpoint (NSE .NS tickers), fetched
politely (one request per symbol, 3 s apart, stop on any 4xx/5xx) into OUTDIR, never into data/raw.
Yahoo's close is split-adjusted, so for each stock only dates AFTER its last split/bonus/consolidation event
(project events table, any status) are compared with the raw NSE close (series EQ). Tolerance 0.5%.
Usage: python -I audit/stage24_prices.py OUTDIR [fetch]"""
import sys, json, time, random, urllib.request, urllib.parse
from pathlib import Path
import pandas as pd
R = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]); (OUT/"yahoo").mkdir(exist_ok=True)
SYMS = """RELIANCE TCS INFY HDFCBANK ICICIBANK SBIN ITC HINDUNILVR LT AXISBANK KOTAKBANK BHARTIARTL MARUTI SUNPHARMA TITAN
ASIANPAINT BAJFINANCE NESTLEIND ULTRACEMCO WIPRO ONGC NTPC POWERGRID COALINDIA TATASTEEL M&M HCLTECH TECHM DRREDDY CIPLA
BAJAJ-AUTO HEROMOTOCO EICHERMOT GRASIM JSWSTEEL ADANIPORTS BPCL HINDALCO DIVISLAB BRITANNIA""".split()
SEED = 20261122
if len(sys.argv) > 2 and sys.argv[2] == "fetch":
    for s in SYMS:
        f = OUT/"yahoo"/f"{s}.json"
        if f.exists(): continue
        u = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(s+'.NS')}?period1=1420070400&period2=1790000000&interval=1d&events=div%2Csplit"
        try:
            d = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "price-crosscheck/1.0"}), timeout=30).read()
        except Exception as e:
            print("STOP", s, e); break
        f.write_bytes(d); print("fetched", s, len(d)); time.sleep(3)
b = pd.concat([pd.read_parquet(x, columns=["date","symbol","series","close","sec_id"]) for x in sorted((R/"data/build/bhavcopy").glob("*.parquet"))])
b = b[(b.series=="EQ")&(b.date>="2015-01-01")]
ev = pd.read_parquet(R/"data/build/actions/events.parquet", columns=["sec_id","symbol","ex_date","kind","status"])
sh = ev[ev.kind.isin(["SPLIT","BONUS","CONSOLIDATION"])]
rnd = random.Random(SEED); rows=[]; missing=[]
for s in SYMS:
    f = OUT/"yahoo"/f"{s}.json"
    if not f.exists(): missing.append(s); continue
    d = json.loads(f.read_text())["chart"]["result"][0]
    off = d["meta"].get("gmtoffset", 19800)
    y = pd.DataFrame({"date": pd.to_datetime([pd.Timestamp(t+off, unit="s").date() for t in d["timestamp"]]),
                      "ycl": d["indicators"]["quote"][0]["close"]}).dropna()
    g = b[b.symbol==s]
    last_act = sh[sh.symbol==s].ex_date.max()
    cand = g[g.date >= (last_act if pd.notna(last_act) else pd.Timestamp("2015-01-01"))]
    cand = cand[cand.date > (last_act if pd.notna(last_act) else pd.Timestamp("1900-01-01"))]
    days = sorted(cand.date.unique())
    pick = sorted(rnd.sample(days, min(20, len(days))))
    m = g[g.date.isin(pick)].merge(y, on="date", how="left")
    m["last_share_action"] = last_act; m["n_days_available"] = len(days)
    rows.append(m)
r = pd.concat(rows); r["diff_pct"] = (r.ycl/r.close-1)*100
r["miss"] = r.ycl.isna() | (r.diff_pct.abs() > 0.5)
r.to_csv(OUT/"stage24_compare.csv", index=False)
print("symbols not fetched:", missing)
print("stocks", r.symbol.nunique(), "comparisons", len(r), "no yahoo row", int(r.ycl.isna().sum()), "misses >0.5%", int((r.miss & r.ycl.notna()).sum()))
print("per-stock days available <20:", r.groupby("symbol").n_days_available.first().loc[lambda x: x<20].to_dict())
print(r[r.miss].sort_values("diff_pct").to_string(index=False))
print(r.diff_pct.describe())
