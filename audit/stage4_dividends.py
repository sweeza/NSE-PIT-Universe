"""Stage 4.2: audit of the dividend entries used by total_return mode.
(a) Record level: own parse of every raw feed record vs the project's DIVIDEND events (amount per rec_id).
(b) Adjustment level: project DIVIDEND multipliers vs own (P-D)/P using NSE's printed close of the previous session.
(c) Duplicate and overlap handling, and economic plausibility against the price move on the ex-date.
Usage: python -I audit/stage4_dividends.py outdir"""
import sys, importlib.util
from pathlib import Path
import numpy as np, pandas as pd
spec = importlib.util.spec_from_file_location("s4", Path(__file__).with_name("stage4_factors.py")); s4 = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0], sys.argv[1] if len(sys.argv) > 1 else "audit/out"]; spec.loader.exec_module(s4)
R, OUT = s4.ROOT, s4.OUT
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 80)
mine = s4.load(); md = mine[mine.kind.isin(["DIV", "DIV?"])].copy()
ev = pd.read_parquet(R / "data/build/actions/events.parquet")
pe = ev[ev.kind == "DIVIDEND"][["rec_id", "comp", "amount", "detail", "sec_id", "eff_date", "status", "ex_date", "symbol", "subject"]]
# (a)
j = md.merge(pe, left_on="rec", right_on="rec_id", how="outer", indicator=True)
a = {"mine_dividend_records": int(md.rec.nunique()), "project_dividend_records": int(pe.rec_id.nunique())}
both = j[j._merge == "both"]
both = both.assign(diff=(both.amt - both.amount).abs())
a["amount_mismatch_gt_1e-9"] = int((both["diff"] > 1e-9).sum())
a["only_mine"] = int((j._merge == "left_only").sum()); a["only_project"] = int((j._merge == "right_only").sum())
print(a)
j[(j._merge != "both")].to_csv(OUT / "stage4_div_only_one_side.csv", index=False)
both[both["diff"] > 1e-9][["rec", "symbol_x", "ex", "subject_x", "amt", "amount", "txt", "detail"]].to_csv(OUT / "stage4_div_amount_mismatch.csv", index=False)
# (b) adjustments
adj = pd.read_parquet(R / "data/build/actions/adjustments.parquet"); dv = adj[adj.kind == "DIVIDEND"]
px = s4.load_prices(2004)
px = px[px.sec_id.isin(dv.sec_id.unique())].sort_values(["sec_id", "date"])
cl = {s: g.set_index("date").close for s, g in px.groupby("sec_id")}
pc = {s: g.set_index("date").prev_close for s, g in px.groupby("sec_id")}
rows = []
for r in dv.itertuples():
    c = cl[r.sec_id]; k = c.index.searchsorted(r.eff_date) - 1
    P = c.iloc[k] if k >= 0 else np.nan
    D = float(r.detail.split()[1].split("+")[0]) if False else np.nan
    mult_mine = np.nan
    rows.append((r.sec_id, r.eff_date, r.rec_id, r.price_mult, P))
d = pd.DataFrame(rows, columns=["sec_id", "eff_date", "rec_id", "mult", "P"])
d = d.merge(md[["rec", "amt"]].drop_duplicates("rec"), left_on="rec_id", right_on="rec", how="left")
d["mult_mine"] = (d.P - d.amt) / d.P
d["dev"] = (d.mult / d.mult_mine - 1).abs()
b = {"adjust_rows": len(d), "no_own_amount": int(d.amt.isna().sum()), "mult_dev_gt_1e-9": int((d.dev > 1e-9).sum())}
print(b)
d[d.dev > 1e-9].to_csv(OUT / "stage4_div_mult_mismatch.csv", index=False)
# (c1) rows dropped: events OK-placed DIVIDEND not in adjustments
ok = pe[pe.status == "OK"]
key = set(zip(dv.sec_id, dv.eff_date, dv.detail))
ok = ok.assign(k=list(zip(ok.sec_id, ok.eff_date, "rs " + ok.amount.map(lambda x: f"{x:g}"))))
dvkeys = set(zip(dv.sec_id, dv.eff_date))
ok["in_adj"] = [(s, e) in dvkeys for s, e in zip(ok.sec_id, ok.eff_date)]
dropped = ok[~ok.in_adj]
print("OK dividend events with no adjustment row on that sec/day:", len(dropped), "(amount >= price:", int((dropped.amount > 0).sum()), "listed)")
dropped.to_csv(OUT / "stage4_div_dropped.csv", index=False)
# same sec/day multiple distinct dividend rows kept
multi = dv.groupby(["sec_id", "eff_date"]).size(); print("sec/day with 2+ dividend rows:", int((multi > 1).sum()))
# duplicates removed: same sec/day/amount from different records
dd = ok.groupby(["sec_id", "eff_date"]).agg(n=("rec_id", "nunique"), na=("amount", "nunique")).reset_index()
print("sec/day with 2+ records:", int((dd.n > 1).sum()), " of which the amounts differ:", int(((dd.n > 1) & (dd.na > 1)).sum()))
dd[(dd.n > 1) & (dd.na > 1)].to_csv(OUT / "stage4_div_multi_amount.csv", index=False)
# (c2) plausibility: yield and observed ex-day drop
d["yield"] = d.amt / d.P
big = d[d["yield"] > 0.10]
print("dividend yields > 10% of previous close:", len(big), " > 25%:", int((d["yield"] > 0.25).sum()), " max:", float(d["yield"].max()))
big.sort_values("yield", ascending=False).head(60).to_csv(OUT / "stage4_div_high_yield.csv", index=False)
# observed ex-day move vs dividend, for yields > 3%, no share action same day
sh = set(zip(adj[adj.kind != "DIVIDEND"].sec_id, adj[adj.kind != "DIVIDEND"].eff_date))
t = d[(d["yield"] > 0.03)].copy()
obs = []
for r in t.itertuples():
    c = cl[r.sec_id]; k = c.index.searchsorted(r.eff_date)
    if k < len(c) and c.index[k] == r.eff_date and (r.sec_id, r.eff_date) not in sh and k > 0:
        obs.append((r.sec_id, r.eff_date, r.amt, r.P, c.iloc[k], (c.iloc[k] - r.P) / r.P, -r.amt / r.P))
o = pd.DataFrame(obs, columns=["sec_id", "eff_date", "amt", "P", "close", "ret", "expected_div_effect"])
o["excess"] = o.ret - o.expected_div_effect
print("ex-day moves tested (yield>3%, no share action same day):", len(o), " median excess return:", float(o.excess.median()), " share with |excess|<5%:", float((o.excess.abs() < .05).mean()))
o.to_csv(OUT / "stage4_div_exday_test.csv", index=False)
