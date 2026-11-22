"""Stage 7: inject one curated-data error, rebuild membership, run the gate checks. Usage: mutate.py NAME"""
import os, sys, shutil, subprocess, time
from pathlib import Path
import pandas as pd
S = Path(__file__).resolve().parents[1]
FRESH = S / "fresh"
name = sys.argv[1]
M = S / "mut" / name
if M.exists(): subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(M)], check=False)
(M / "data" / "build").mkdir(parents=True)
shutil.copytree(FRESH / "data" / "curated", M / "data" / "curated")
def junc(link, target): subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
junc(M / "data" / "raw", FRESH / "data" / "raw")
for d in ("bhavcopy", "identity"): junc(M / "data" / "build" / d, FRESH / "data" / "build" / d)
C = M / "data" / "curated"
ev = pd.read_csv(C / "index_events_press.csv", dtype=str).fillna("")
info = ""
def save_ev(df): df.to_csv(C / "index_events_press.csv", index=False)
if name == "baseline": pass
elif name == "m1_drop_event":      # remove one mid-history Nifty 50 inclusion
    r = ev[(ev.index_key == "NIFTY50") & (ev.action == "IN") & (ev.date > "2021") & (ev.date < "2025")].iloc[3]
    info = f"dropped {r.date} {r.symbol} IN"; save_ev(ev.drop(r.name))
elif name == "m2_shift_date":      # move one event one calendar week later
    r = ev[(ev.index_key == "NIFTY50") & (ev.date > "2021") & (ev.date < "2025")].iloc[3]
    ev.loc[r.name, "date"] = (pd.Timestamp(r.date) + pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    info = f"moved {r.date} {r.symbol} {r.action} +7d"; save_ev(ev)
elif name == "m2b_shift_1d":       # move one event one day
    r = ev[(ev.index_key == "NIFTY50") & (ev.date > "2021") & (ev.date < "2025")].iloc[3]
    ev.loc[r.name, "date"] = (pd.Timestamp(r.date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    info = f"moved {r.date} {r.symbol} {r.action} +1d"; save_ev(ev)
elif name == "m3_swap_symbol":     # swap an inclusion to a different real company
    r = ev[(ev.index_key == "NIFTY50") & (ev.action == "IN") & (ev.date > "2021") & (ev.date < "2025")].iloc[3]
    ev.loc[r.name, "symbol"] = "ASIANPAINT" if r.symbol != "ASIANPAINT" else "TITAN"
    info = f"{r.date} {r.symbol} -> {ev.loc[r.name,'symbol']}"; save_ev(ev)
elif name == "m3b_swap_symbol_n500":   # same, in Nifty 500
    r = ev[(ev.index_key == "NIFTY500") & (ev.action == "IN") & (ev.date > "2015") & (ev.date < "2020")].iloc[10]
    ev.loc[r.name, "symbol"] = "ASIANPAINT" if r.symbol != "ASIANPAINT" else "TITAN"
    info = f"{r.date} {r.symbol} -> {ev.loc[r.name,'symbol']}"; save_ev(ev)
elif name == "m4_bad_alias":       # point a historic alias at a different company
    al = pd.read_csv(C / "name_aliases.csv", dtype=str).fillna("")
    er = pd.read_parquet(FRESH / "data" / "build" / "membership" / "events_resolved.parquet")
    used = set(er[(er.index_key.isin(["NIFTY50","NIFTY100"])) & er.relevant & (er.resolution == "OK")].company)
    cand = al[al.company.isin(used)]
    r = cand.iloc[0]; wrong = "WIPRO" if r.symbol != "WIPRO" else "TCS"
    al.loc[r.name, "symbol"] = wrong; info = f"{r.company}: {r.symbol} -> {wrong} (alias used by a relevant Nifty50/100 event)"
    al.to_csv(C / "name_aliases.csv", index=False)
elif name == "m5_missing_source":  # cite a file that does not exist
    r = ev[ev.index_key == "NIFTY50"].iloc[10]
    ev.loc[r.name, "source"] = "data/raw/pressreleases/pdf/ind_prs99999999.pdf"; info = "bogus source"; save_ev(ev)
elif name == "m6_drop_size_exception":
    x = pd.read_csv(C / "index_size_exceptions.csv", dtype=str).fillna("")
    r = x[x.index_key == "NIFTY100"].iloc[1]; info = f"dropped exception {r.from_date}..{r.to_date}"; x.drop(r.name).to_csv(C / "index_size_exceptions.csv", index=False)
elif name == "m7_drop_dual_class":
    x = pd.read_csv(C / "index_dual_class.csv", dtype=str).fillna("")
    info = "dropped first dual-class row"; x.drop(x.index[0]).to_csv(C / "index_dual_class.csv", index=False)
elif name == "m8_flip_action":     # turn one exclusion into an inclusion
    r = ev[(ev.index_key == "NIFTY50") & (ev.action == "OUT") & (ev.date > "2021") & (ev.date < "2025")].iloc[2]
    ev.loc[r.name, "action"] = "IN"; info = f"{r.date} {r.symbol} OUT->IN"; save_ev(ev)
else: raise SystemExit("unknown " + name)
env = dict(os.environ, NSEUNIVERSE_ROOT=str(M))
code = ("import time;t=time.time();from nseuniverse import membership,verify;"
        "membership.build();"
        "[print(r.name,r.status,r.summary[:160]) for r in (verify.check_curated_provenance(),verify.check_membership())];"
        "import pandas as pd;from nseuniverse import paths;"
        f"b=pd.read_parquet(r'{FRESH}/data/build/membership/coverage.parquet');m=pd.read_parquet(paths.BUILD/'membership'/'coverage.parquet');"
        "f=lambda c:c[c.status=='VERIFIED'].assign(d=lambda x:(pd.to_datetime(x.to_date)-pd.to_datetime(x.from_date)).dt.days+1).groupby('index_key').d.sum();"
        "bb,mm=f(b),f(m);dd=(mm.reindex(bb.index.union(mm.index)).fillna(0)-bb.reindex(bb.index.union(mm.index)).fillna(0));dd=dd[dd!=0];"
        "print('COVERAGE_CHANGE(verified calendar days vs baseline):',dd.to_dict() or 'none')")
t0 = time.time()
p = subprocess.run([str(S / "venv" / "Scripts" / "python.exe"), "-c", code], env=env, capture_output=True, text=True, cwd=str(M))
out = (p.stdout + p.stderr).strip().splitlines()
print(f"[{name}] {info} | rc={p.returncode} {time.time()-t0:.0f}s")
for l in out[-6:]: print("   ", l[:260])
