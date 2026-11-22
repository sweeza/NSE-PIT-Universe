"""Stage 8.2: API refuses every date not VERIFIED, never returns an empty frame silently, and the message names the reason."""
import sys, random, warnings
from pathlib import Path
import pandas as pd
warnings.filterwarnings("ignore")
R = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(R))
from nseuniverse import api
cov = api.coverage(); rng = random.Random(20261122)
print(cov.status.value_counts().to_dict(), cov.index_key.nunique(), "indices")
bad = []; n_ok = n_ref = 0
for k, g in cov.groupby("index_key"):
    for d in rng.sample(list(pd.bdate_range("2005-01-03", "2026-11-19")), 40):
        v = g[(g.from_date <= d) & (g.to_date >= d)]
        verified = (v.status == "VERIFIED").any()
        try:
            m = api.index_members(k, d)
            if not verified: bad.append((k, d.date(), "returned members outside VERIFIED"))
            elif len(m) == 0: bad.append((k, d.date(), "VERIFIED but empty"))
            else: n_ok += 1
        except api.CoverageError as e:
            n_ref += 1
            if verified: bad.append((k, d.date(), "refused inside VERIFIED: " + str(e)[:60]))
            if not str(e).strip() or "not verified" not in str(e): bad.append((k, d.date(), "message lacks reason: " + str(e)[:80]))
print("served", n_ok, "refused", n_ref, "violations", len(bad)); print(bad[:10])
# prices: non-trading and unknown inputs must raise, not return empty
for args in [("RELIANCE", "2007-01-06", "2007-01-07"), ("NOSUCHSYM", "2020-01-01", "2020-02-01")]:
    try:
        p = api.prices(*args, adjust_mode=None); print(args, "->", len(p), "rows")
    except Exception as e: print(args, "->", type(e).__name__, str(e)[:90])
try: api.prices("RELIANCE", "2005-01-03", "2006-01-01", "splits"); print("pre-2007 adjusted served!")
except api.CoverageError as e: print("pre-2007 adjusted refused:", str(e)[:60])
try: print(len(api.prices("RELIANCE", "2007-01-03", "2007-02-01", "splits")), "rows ok")
except Exception as e: print(type(e).__name__, e)
try: api.prices("RELIANCE", "2007-01-03", "2007-02-01", "total_return", as_of="2006-12-01"); print("as_of before start served")
except Exception as e: print("as_of before start:", type(e).__name__, str(e)[:80])
