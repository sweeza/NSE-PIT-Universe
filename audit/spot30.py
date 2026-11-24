"""Spot check: 30 membership dates against NSE constituent files held in data/raw/constituents_archive.
Draw: seeded, stratified over indices (at most 4 per index), only captures dated 2010-01-04 or later that fall inside a
verified window of the index. Compare: the capture's symbol set against api.index_members(index, capture date);
a symbol renamed since counts as a match when the ISIN is the same. Run: python -I audit/spot30.py"""
import io, os, re, random, warnings
from pathlib import Path
import pandas as pd

warnings.simplefilter("ignore")
import nseuniverse.api as nse

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "data" / "raw" / "constituents_archive"
KEY = {"ind_niftylist": "NIFTY50", "nifty50": "NIFTY50", "ind_jrniftylist": "NIFTYNEXT50", "niftynext50": "NIFTYNEXT50",
       "ind_cnx100list": "NIFTY100", "nifty100": "NIFTY100", "ind_cnx200list": "NIFTY200", "nifty200": "NIFTY200",
       "ind_cnx500list": "NIFTY500", "nifty500": "NIFTY500", "ind_cnxautolist": "NIFTYAUTO", "niftyauto": "NIFTYAUTO",
       "ind_cnxbanklist": "NIFTYBANK", "niftybank": "NIFTYBANK", "ind_cnxfinancelist": "NIFTYFINANCIALSERVICES",
       "ind_cnxfmcglist": "NIFTYFMCG", "niftyfmcg": "NIFTYFMCG", "ind_cnxitlist": "NIFTYIT", "niftyit": "NIFTYIT",
       "ind_cnxmedialist": "NIFTYMEDIA", "niftymedia": "NIFTYMEDIA", "ind_cnxmetallist": "NIFTYMETAL", "niftymetal": "NIFTYMETAL",
       "ind_cnxmidcaplist": "NIFTYMIDCAP100", "niftymidcap100": "NIFTYMIDCAP100", "ind_cnxpharmalist": "NIFTYPHARMA",
       "niftypharma": "NIFTYPHARMA", "ind_cnxpsubanklist": "NIFTYPSUBANK", "niftypsubank": "NIFTYPSUBANK",
       "ind_cnxrealtylist": "NIFTYREALTY", "niftyrealty": "NIFTYREALTY", "ind_niftymidcap50list": "NIFTYMIDCAP50",
       "niftymidcap50": "NIFTYMIDCAP50", "niftymidcap150": "NIFTYMIDCAP150", "niftylargemidcap250": "NIFTYLARGEMIDCAP250",
       "niftymidsmallcap400": "NIFTYMIDSMALLCAP400", "niftysmallcap100": "NIFTYSMALLCAP100", "niftysmallcap250": "NIFTYSMALLCAP250"}


def parse(f: Path):
    raw = f.read_bytes()
    if raw[:2] == bytes([0x1f, 0x8b]):
        import gzip; raw = gzip.decompress(raw)
    try:
        a = pd.read_csv(io.BytesIO(raw), dtype=str, encoding="latin-1", on_bad_lines="skip")
    except Exception:
        return None                                   # not a constituent CSV (HTML page, damaged capture): not usable
    a.columns = [c.strip() for c in a.columns]
    if "Symbol" not in a.columns:
        return None
    a = a[~a["Symbol"].fillna("").str.upper().str.startswith("DUMMY")]
    if "Series" in a:
        a = a[a["Series"].fillna("EQ").isin(["EQ", "BE", "BZ", "SM"])]
    return a


cov = nse.coverage()
cov = cov[cov.status == "VERIFIED"]
cands = []
for f in sorted(ARCH.glob("*.csv")):
    m = re.match(r"(.+)_(\d{14})\.csv$", f.name)
    if not m or m.group(1) not in KEY:
        continue
    k, d = KEY[m.group(1)], pd.Timestamp(m.group(2)[:8])
    w = cov[(cov.index_key == k) & (cov.from_date <= d) & (cov.to_date >= d)]
    if d >= pd.Timestamp("2010-01-04") and len(w) and parse(f) is not None:
        cands.append((k, d, f))
print(len(cands), "usable captures in verified windows")
random.seed(20261124)
random.shuffle(cands)
pick, per = [], {}
for k, d, f in cands:          # round-robin by index so one index cannot dominate
    if per.get(k, 0) < 4:
        pick.append((k, d, f)); per[k] = per.get(k, 0) + 1
    if len(pick) == 30:
        break
rows = []
for k, d, f in sorted(pick, key=lambda x: (x[0], x[1])):
    a = parse(f)
    mem = nse.index_members(k, d)
    A, B = set(a["Symbol"].str.strip()), set(mem["symbol"])
    onlyA, onlyB = A - B, B - A
    isinA = dict(zip(a["Symbol"].str.strip(), a["ISIN Code"].str.strip())) if "ISIN Code" in a else {}
    isinB = dict(zip(mem["symbol"], mem["isin_last"]))
    ia = {isinA.get(s): s for s in onlyA if isinA.get(s)}; ib = {isinB.get(s): s for s in onlyB if isinB.get(s)}
    same = set(ia) & set(ib)
    onlyA = {s for s in onlyA if isinA.get(s) not in same}; onlyB = {s for s in onlyB if isinB.get(s) not in same}
    rows.append((k, d.date().isoformat(), f.name, len(A), len(B), ",".join(sorted(onlyA)), ",".join(sorted(onlyB)),
                 "MATCH" if not onlyA and not onlyB else "DIFF"))
r = pd.DataFrame(rows, columns=["index", "capture_date", "file", "nse_n", "build_n", "only_in_nse_file", "only_in_build", "result"])
r.to_csv(ROOT / "audit" / "spot30_result.csv", index=False)
pd.set_option("display.width", 250, "display.max_colwidth", 60)
print(r.drop(columns="file").to_string(index=False))
print(r.result.value_counts().to_dict())
