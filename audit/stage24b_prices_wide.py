"""Stage 2.4b: wider third-party close check (BSE refused scripted downloads, so Yahoo only, as agreed).
150 seeded currently-listed EQ symbols outside the first 40, 2007 onward, 15 dates each, only dates after the stock's
last split/bonus/consolidation. Polite: 1 request per symbol, 3 s apart, stop on first hard error. Output stays in OUTDIR.
Usage: python -I audit/stage24b_prices_wide.py OUTDIR [fetch]"""
import sys, json, time, random, urllib.request, urllib.parse
from pathlib import Path
import pandas as pd
R = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]); (OUT/"yahoo2").mkdir(parents=True, exist_ok=True)
first40 = set(open(R/"audit/stage24_prices.py").read().split('SYMS = """')[1].split('""".split()')[0].split())
b = pd.concat([pd.read_parquet(x, columns=["date","symbol","series","close"]) for x in sorted((R/"data/build/bhavcopy").glob("*.parquet"))])
b = b[(b.series=="EQ")&(b.date>="2007-01-01")]
last = b.groupby("symbol").date.max(); cnt = b.groupby("symbol").date.nunique()
pool = sorted(s for s in last.index if last[s] >= pd.Timestamp("2026-11-01") and cnt[s] >= 1500 and s not in first40 and s.isascii())
rnd = random.Random(20261122); SYMS = sorted(rnd.sample(pool, 150))
if len(sys.argv) > 2 and sys.argv[2] == "fetch":
    for s in SYMS:
        f = OUT/"yahoo2"/f"{s}.json"
        if f.exists(): continue
        u = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(s+'.NS')}?period1=1167609600&period2=1790000000&interval=1d&events=div%2Csplit"
        try:
            d = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "price-crosscheck/1.0"}), timeout=30).read()
        except urllib.error.HTTPError as e:
            if e.code == 404: f.write_text("{}"); print("404", s); time.sleep(3); continue
            print("STOP", s, e); break
        except Exception as e:
            print("STOP", s, e); break
        f.write_bytes(d); print("fetched", s, len(d), flush=True); time.sleep(3)
ev = pd.read_parquet(R/"data/build/actions/events.parquet", columns=["symbol","ex_date","kind"])
sh = ev[ev.kind.isin(["SPLIT","BONUS","CONSOLIDATION"])]
other = ev[~ev.kind.isin(["SPLIT","BONUS","CONSOLIDATION","DIVIDEND"])]
rows=[]; nodata=[]
for s in SYMS:
    f = OUT/"yahoo2"/f"{s}.json"
    if not f.exists() or f.stat().st_size < 10: nodata.append(s); continue
    d = json.loads(f.read_text())["chart"]["result"][0]
    off = d["meta"].get("gmtoffset", 19800)
    y = pd.DataFrame({"date": pd.to_datetime([pd.Timestamp(t+off, unit="s").date() for t in d["timestamp"]]),
                      "ycl": d["indicators"]["quote"][0]["close"]}).dropna()
    g = b[b.symbol==s]; la = sh[sh.symbol==s].ex_date.max()
    days = sorted(g[g.date > (la if pd.notna(la) else pd.Timestamp("2007-01-01"))].date.unique())
    if not days: continue
    pick = sorted(rnd.sample(days, min(15, len(days))))
    m = g[g.date.isin(pick)].merge(y, on="date", how="left"); m["last_share_action"] = la
    oe = other[other.symbol==s].ex_date
    m["other_event_before"] = [bool(((oe > pd.Timestamp("2007-01-01")) & (oe > d_)).any()) for d_ in m.date]
    rows.append(m)
r = pd.concat(rows); r["diff_pct"] = (r.ycl/r.close-1)*100
r["miss"] = r.ycl.notna() & (r.diff_pct.abs() > 0.5)
r.to_csv(OUT/"stage24b_compare.csv", index=False)
print("symbols no yahoo data:", len(nodata), "| stocks compared", r.symbol.nunique(), "| comparisons", len(r),
      "| no yahoo row", int(r.ycl.isna().sum()), "| within 0.5%", int((r.ycl.notna() & ~r.miss).sum()), "| misses", int(r.miss.sum()))
mm = r[r.miss]
print("misses by stock:", mm.groupby("symbol").size().sort_values(ascending=False).head(25).to_dict())
print("misses that are constant per stock (one factor):", int(mm.groupby("symbol").diff_pct.apply(lambda x: x.round(0).nunique()==1).sum()), "of", mm.symbol.nunique())
