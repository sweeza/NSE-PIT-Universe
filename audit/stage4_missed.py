"""Stage 4.1b: events neither parser caught. For the same 60 securities, list overnight breaks in NSE's own
prev_close vs close (ratio outside [0.7, 1.43]) with no share/rights event within 3 sessions in mine or the project's table,
and say whether the feed has any corporate-action record for that symbol within 10 days."""
import sys, importlib.util
from pathlib import Path
import pandas as pd, numpy as np
spec = importlib.util.spec_from_file_location("s4", Path(__file__).with_name("stage4_factors.py")); s4 = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0], sys.argv[1] if len(sys.argv) > 1 else "audit/out"]; spec.loader.exec_module(s4)
R = s4.ROOT
cmpf = pd.read_csv(Path(s4.OUT) / "stage4_series_compare.csv")
ids = set(cmpf.sec_id)
px = s4.load_prices(2007); px = px[px.sec_id.isin(ids)].sort_values(["sec_id", "date"])
adj = pd.read_parquet(R / "data/build/actions/adjustments.parquet"); adj = adj[adj.sec_id.isin(ids) & (adj.kind != "DIVIDEND")]
ev = pd.read_parquet(R / "data/build/actions/events.parquet"); ev = ev[ev.sec_id.isin(ids)]
rows = []
for sid, g in px.groupby("sec_id"):
    g = g.reset_index(drop=True)
    r = (g.prev_close / g.close)
    # NSE's own prev_close vs previous row's close: base-price resets show here; day move shows prev/close
    for i in np.flatnonzero(((r > 1.43) | (r < 0.7)).values):
        d = g.date[i]
        near = adj[(adj.sec_id == sid) & ((adj.eff_date - d).abs() <= pd.Timedelta(days=5))]
        evn = ev[(ev.sec_id == sid) & ((ev.ex_date - d).abs() <= pd.Timedelta(days=10)) & ~ev.kind.isin(["NOEFFECT", "DIVIDEND"])]
        rows.append(dict(sec_id=sid, date=d, prev_close=g.prev_close[i], close=g.close[i], ratio=r[i],
                         adj_nearby=len(near), feed_events=";".join(evn.kind + ":" + evn.subject.str[:40])))
o = pd.DataFrame(rows)
o.to_csv(Path(s4.OUT) / "stage4_unexplained_breaks.csv", index=False)
print(len(o), "breaks;", int((o.adj_nearby == 0).sum()), "with no adjustment nearby;", int(((o.adj_nearby == 0) & (o.feed_events == "")).sum()), "with no feed record either")
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 70)
print(o[o.adj_nearby == 0].to_string())
