"""Stage 8.1: look-ahead test of the action/adjustment layer. For seeded dates D, rebuild events, attachment, multipliers and
the evidence gate from ONLY data dated <= D (prices truncated, feed records with ex-date <= D) and compare with the full
build's adjustments whose effective day is <= D. Identity (sec_id, segments) comes from the full build: not truncated (limit).
Usage: python -I audit/stage81_lookahead.py outdir"""
import sys, random, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
R = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(R))
from nseuniverse import actions, adjust, pipeline, bhavcopy
OUT = Path(sys.argv[1])
B = R / "data/build"
t = bhavcopy.load()
seg = pd.read_parquet(B/"identity/segments.parquet"); sh = pd.read_parquet(B/"identity/symbol_history.parquet"); sec = pd.read_parquet(B/"identity/securities.parquet")
full = pd.read_parquet(B/"actions/adjustments.parquet")
rng = random.Random(20261122)
dates = sorted(pd.Timestamp(x) for x in rng.sample(list(pd.bdate_range("2009-01-01", "2026-06-30")), 10))
raw_ev = actions.build_events()
rows = []
for D in dates:
    tt = t[t.date <= D]
    ev = raw_ev[raw_ev.ex_date <= D]
    pc = pipeline.primary_close(tt)
    dbs = {s: g.date.values for s, g in pc.groupby("sec_id")}
    cbs = {s: g.set_index("date").close for s, g in pc.groupby("sec_id")}
    e2 = adjust.attach_events(ev, seg, dbs, sh, sec)
    a2 = adjust.build_adjustments(e2, cbs)
    pcg = pc.sort_values(["sec_id", "date"]).copy(); pcg["prev_close_obs"] = pcg.groupby("sec_id").close.shift(1)
    a2, _ = adjust.gate(a2, pcg)
    a2 = a2[a2.eff_date <= D]; f = full[full.eff_date <= D]
    k = ["sec_id", "eff_date", "kind", "rec_id"]
    m = f.merge(a2, on=k, how="outer", indicator=True, suffixes=("_full", "_trunc"))
    both = m[m._merge == "both"]
    bad_mult = both[(both.price_mult_full / both.price_mult_trunc - 1).abs() > 1e-12]
    only_full = m[m._merge == "left_only"]; only_trunc = m[m._merge == "right_only"]
    recent = lambda df: int((df.eff_date > D - pd.Timedelta(days=10)).sum())
    rows.append((D.date(), len(f), len(a2), len(bad_mult), len(only_full), recent(only_full), len(only_trunc), recent(only_trunc)))
    if len(bad_mult) or len(only_full) or len(only_trunc):
        x = pd.concat([bad_mult.assign(why="mult"), only_full.assign(why="only_full"), only_trunc.assign(why="only_trunc")])
        x.to_csv(OUT / f"stage81_diff_{D.date()}.csv", index=False)
r = pd.DataFrame(rows, columns=["D", "full_rows", "trunc_rows", "mult_diff", "only_full", "of_which_within_10d_of_D", "only_trunc", "of_which_within_10d_of_D_2"])
print(r.to_string())
