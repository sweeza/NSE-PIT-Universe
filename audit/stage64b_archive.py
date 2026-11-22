"""Stage 6.4b: compare archived NSE constituent CSVs (Internet Archive captures) with the build's membership.
Usage: python -I audit/stage64b_archive.py OUTDIR list|fetch|compare
Downloads go to OUTDIR (never data/raw). One request per capture, 1.5 s apart."""
import sys, json, time, urllib.request, io
from pathlib import Path
import pandas as pd
OUT = Path(sys.argv[1]); (OUT/"caps").mkdir(parents=True, exist_ok=True)
INDEX = {"nifty50": "Nifty 50", "niftynext50": "Nifty Next 50", "nifty100": "Nifty 100", "nifty200": "Nifty 200",
         "nifty500": "Nifty 500", "niftymidcap150": "Nifty Midcap 150", "niftysmallcap250": "Nifty Smallcap 250",
         "niftylargemidcap250": "Nifty LargeMidcap 250", "niftymidcap50": "Nifty Midcap 50", "niftymidcap100": "Nifty Midcap 100",
         "niftysmallcap100": "Nifty Smallcap 100", "niftybank": "Nifty Bank", "niftyit": "Nifty IT", "niftypharma": "Nifty Pharma",
         "niftyfmcg": "Nifty FMCG", "niftyauto": "Nifty Auto", "niftymetal": "Nifty Metal", "niftyrealty": "Nifty Realty",
         "niftymedia": "Nifty Media", "niftypsubank": "Nifty PSU Bank", "niftymidsmallcap400": "Nifty MidSmallcap 400"}
URLS = ["niftyindices.com/IndexConstituent/ind_{s}list.csv", "nseindia.com/content/indices/ind_{s}list.csv",
        "www.niftyindices.com/IndexConstituent/ind_{s}list.csv", "www1.nseindia.com/content/indices/ind_{s}list.csv"]
def get(u, t=60):
    return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "membership-crosscheck/1.0"}), timeout=t).read()
mode = sys.argv[2]
if mode == "list":
    rows = []
    for s in INDEX:
        for pat in URLS:
            u = pat.format(s=s)
            try:
                d = json.loads(get(f"https://web.archive.org/cdx/search/cdx?url={u}&output=json&fl=timestamp,statuscode,digest&filter=statuscode:200&collapse=digest"))
            except Exception as e:
                print("ERR", u, e); continue
            for r in d[1:]:
                rows.append((s, r[0], u))
            time.sleep(1)
    pd.DataFrame(rows, columns=["slug", "ts", "url"]).sort_values(["slug", "ts"]).to_csv(OUT/"captures.csv", index=False)
    c = pd.read_csv(OUT/"captures.csv", dtype=str); print(len(c), "captures"); print(c.groupby("slug").ts.agg(["count", "min", "max"]))
elif mode == "fetch":
    c = pd.read_csv(OUT/"captures.csv", dtype=str)
    for r in c.itertuples():
        f = OUT/"caps"/f"{r.slug}_{r.ts}.csv"
        if f.exists(): continue
        try:
            b = get(f"https://web.archive.org/web/{r.ts}id_/https://{r.url}")
        except Exception as e:
            print("ERR", r.slug, r.ts, e); time.sleep(3); continue
        f.write_bytes(b); print("saved", f.name, len(b), flush=True); time.sleep(1.5)
if mode == "compare":
    import warnings; warnings.simplefilter("ignore")
    import nseuniverse.api as nse
    rows = []
    for f in sorted((OUT/"caps").glob("*.csv")):
        slug, ts = f.stem.split("_"); d = pd.Timestamp(ts[:8])
        raw = f.read_bytes()
        if raw[:2] == bytes([0x1f, 0x8b]):
            import gzip; raw = gzip.decompress(raw)
        a = pd.read_csv(io.BytesIO(raw), dtype=str, encoding="latin-1", on_bad_lines="skip")
        a.columns = [c.strip() for c in a.columns]
        if "Symbol" not in a.columns or "ISIN Code" not in a.columns:
            rows.append((slug, ts[:8], len(a), None, None, "", "", "UNPARSED: " + ",".join(a.columns)[:60])); continue
        a = a[a["Series"].fillna("EQ").isin(["EQ", "BE", "BZ", "SM"]) | a["Series"].isna()] if "Series" in a else a
        a = a[~a["Symbol"].str.upper().str.startswith("DUMMY")]
        try:
            m = nse.index_members(INDEX[slug], d)
        except Exception as e:
            rows.append((slug, ts[:8], len(a), None, None, "", "", f"REFUSED: {str(e)[:60]}")); continue
        A, B = set(a["Symbol"].str.strip()), set(m["symbol"])
        onlyA, onlyB = A - B, B - A
        isinA = dict(zip(a["Symbol"].str.strip(), a["ISIN Code"].str.strip())); isinB = dict(zip(m["symbol"], m["isin_last"]))
        # symbol renamed since: same ISIN on both sides is a match
        ia = {isinA[s]: s for s in onlyA}; ib = {isinB[s]: s for s in onlyB}
        same = set(ia) & set(ib)
        onlyA = {s for s in onlyA if isinA[s] not in same}; onlyB = {s for s in onlyB if isinB[s] not in same}
        rows.append((slug, ts[:8], len(a), len(m), len(A & B) + len(same), ",".join(sorted(onlyA)), ",".join(sorted(onlyB)),
                     "MATCH" if not onlyA and not onlyB else "DIFF"))
    r = pd.DataFrame(rows, columns=["slug", "date", "archive_n", "ours_n", "common", "only_archive", "only_ours", "result"])
    r.to_csv(OUT/"compare.csv", index=False)
    print(r.result.str.split(":").str[0].value_counts().to_dict())
    print(r.groupby("slug").result.apply(lambda s: s.str.split(":").str[0].value_counts().to_dict()).to_string())
