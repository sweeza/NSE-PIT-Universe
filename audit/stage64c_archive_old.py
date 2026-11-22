"""Stage 6.4c: archived OLD-format NSE constituent lists (2006-2017, names ind_cnx*list.csv etc.) vs the build.
Usage: python -I audit/stage64c_archive_old.py OUTDIR fetch|compare   (OUTDIR holds old_cdx.json from the CDX query)
Downloads go to OUTDIR only, 1.5 s apart."""
import sys, json, re, time, io, gzip, urllib.request, warnings
from pathlib import Path
import pandas as pd
OUT = Path(sys.argv[1]); (OUT/"caps_old").mkdir(exist_ok=True)
NAME = {"ind_niftylist": "Nifty 50", "ind_jrniftylist": "Nifty Next 50", "ind_cnx100list": "Nifty 100", "ind_cnx200list": "Nifty 200",
        "ind_cnx500list": "Nifty 500", "ind_cnxbanklist": "Nifty Bank", "ind_cnxitlist": "Nifty IT", "ind_cnxpharmalist": "Nifty Pharma",
        "ind_cnxfmcglist": "Nifty FMCG", "ind_cnxrealtylist": "Nifty Realty", "ind_cnxmetallist": "Nifty Metal", "ind_cnxautolist": "Nifty Auto",
        "ind_cnxmedialist": "Nifty Media", "ind_cnxmidcaplist": "Nifty Midcap 100", "ind_niftymidcap50list": "Nifty Midcap 50",
        "ind_cnxpsubanklist": "Nifty PSU Bank", "ind_cnxfinancelist": "Nifty Financial Services"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "membership-crosscheck/1.0"}), timeout=60).read()
jobs, seen = [], set()
for u, ts, dg in json.load(open(OUT/"old_cdx.json"))[1:]:
    m = re.search(r"/(ind_[a-z0-9_]+list)\.csv", u, re.I)
    if not m or m.group(1).lower() not in NAME: continue
    k = (m.group(1).lower(), dg)
    if k in seen: continue
    seen.add(k); jobs.append((m.group(1).lower(), ts, u))
if sys.argv[2] == "fetch":
    for slug, ts, u in jobs:
        f = OUT/"caps_old"/f"{slug}_{ts}.csv"
        if f.exists(): continue
        try: b = get(f"https://web.archive.org/web/{ts}id_/{u}")
        except Exception as e: print("ERR", slug, ts, e); time.sleep(3); continue
        f.write_bytes(b); print("saved", f.name, len(b), flush=True); time.sleep(1.5)
else:
    warnings.simplefilter("ignore")
    import nseuniverse.api as nse
    rows = []
    for f in sorted((OUT/"caps_old").glob("*.csv")):
        slug, ts = f.stem.rsplit("_", 1); d = pd.Timestamp(ts[:8])
        raw = f.read_bytes()
        if raw[:2] == bytes([0x1f, 0x8b]): raw = gzip.decompress(raw)
        txt = raw.decode("latin-1").splitlines()
        hdr = next((i for i, l in enumerate(txt[:12]) if "symbol" in l.lower() and "," in l), 0)
        try: a = pd.read_csv(io.StringIO(chr(10).join(txt[hdr:])), dtype=str, on_bad_lines="skip")
        except Exception as e: rows.append((slug, ts[:8], 0, None, None, "", "", f"UNPARSED: {e}")); continue
        a.columns = [c.strip() for c in a.columns]
        cs = {c.lower(): c for c in a.columns}
        if "symbol" not in cs: rows.append((slug, ts[:8], len(a), None, None, "", "", "UNPARSED: " + ",".join(a.columns)[:50])); continue
        sy = a[cs["symbol"]].astype(str).str.strip(); A = set(sy[~sy.str.upper().str.startswith("DUMMY")])
        isn = dict(zip(sy, a[cs["isin code"]].astype(str).str.strip())) if "isin code" in cs else {}
        try: m = nse.index_members(NAME[slug], d)
        except Exception as e: rows.append((slug, ts[:8], len(A), None, None, "", "", f"REFUSED: {str(e)[:50]}")); continue
        B = set(m["symbol"]); onlyA, onlyB = A - B, B - A
        isinB = dict(zip(m["symbol"], m["isin_last"]))
        ia = {isn.get(s): s for s in onlyA if s in isn}; ib = {isinB[s]: s for s in onlyB}
        same = set(ia) & set(ib)
        onlyA = {s for s in onlyA if isn.get(s) not in same}; onlyB = {s for s in onlyB if isinB[s] not in same}
        rows.append((slug, ts[:8], len(A), len(m), len(A & B) + len(same), ",".join(sorted(onlyA)), ",".join(sorted(onlyB)),
                     "MATCH" if not onlyA and not onlyB else "DIFF"))
    r = pd.DataFrame(rows, columns=["slug", "date", "archive_n", "ours_n", "common", "only_archive", "only_ours", "result"])
    r.to_csv(OUT/"compare_old.csv", index=False)
    print(r.result.str.split(":").str[0].value_counts().to_dict())
