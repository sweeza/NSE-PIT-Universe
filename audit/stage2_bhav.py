"""Stage 2.1: independent bhavcopy reader (zipfile + csv only, no project parsers).

Compares every selected raw day with data/build/bhavcopy parquet: row counts for all days,
cell-by-cell for a seeded sample of 300 days. Selection rule mirrored independently:
one file per date, UDiFF preferred over legacy.
Usage: python audit/stage2_bhav.py [seed]
"""
import csv, io, sys, zipfile, random, datetime as dt, math
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 20261122
LEG = {"SYMBOL": "symbol", "SERIES": "series", "OPEN": "open", "HIGH": "high", "LOW": "low",
       "CLOSE": "close", "LAST": "last", "PREVCLOSE": "prev_close", "TOTTRDQTY": "volume",
       "TOTTRDVAL": "turnover", "TOTALTRADES": "trades", "ISIN": "isin"}
UD = {"TckrSymb": "symbol", "SctySrs": "series", "OpnPric": "open", "HghPric": "high",
      "LwPric": "low", "ClsPric": "close", "LastPric": "last", "PrvsClsgPric": "prev_close",
      "TtlTradgVol": "volume", "TtlTrfVal": "turnover", "TtlNbOfTxsExctd": "trades",
      "ISIN": "isin", "FinInstrmNm": "name", "FinInstrmId": "instrument_id", "SttlmPric": "settle_price"}
NUM = ["open", "high", "low", "close", "last", "prev_close", "volume", "turnover", "trades", "settle_price"]


def file_date(p):
    n = p.name
    if n.startswith("BhavCopy_NSE_CM"):
        return dt.datetime.strptime(n.split("_")[6], "%Y%m%d").date(), "udiff"
    return dt.datetime.strptime(n[2:11], "%d%b%Y").date(), "legacy"


def read(p, kind):
    z = zipfile.ZipFile(p)
    nm = z.namelist()
    assert len(nm) == 1, (p, nm)
    txt = z.read(nm[0]).decode("latin1")
    rd = csv.reader(io.StringIO(txt))
    hdr = [h.strip() for h in next(rd)]
    mp = LEG if kind == "legacy" else UD
    idx = {mp[h]: i for i, h in enumerate(hdr) if h in mp}
    rows = {}
    n = 0
    for r in rd:
        if not r or all(not c.strip() for c in r):
            continue
        n += 1
        g = lambda k: r[idx[k]].strip() if k in idx and idx[k] < len(r) else None
        key = (g("symbol"), g("series"))
        rec = {}
        for k in idx:
            if k in NUM:
                v = g(k)
                rec[k] = float("nan") if v in (None, "", "-") else float(v)
            else:
                rec[k] = g(k) or None
        rows[key] = rec
    return n, rows


def main():
    files = {}
    for p in sorted((ROOT / "data/raw/bhavcopy").rglob("*.zip")):
        d, k = file_date(p)
        if d not in files or k == "udiff":
            files[d] = (k, p)
    days = sorted(files)
    print("selected days", len(days), "seed", SEED)
    build = pd.concat([pd.read_parquet(f) for f in sorted((ROOT / "data/build/bhavcopy").glob("*.parquet"))])
    cnt = build.groupby("date").size()
    # 1. row counts, all days
    bad_cnt = []
    for d in days:
        k, p = files[d]
        z = zipfile.ZipFile(p)
        txt = z.read(z.namelist()[0]).decode("latin1")
        lines = [l for l in txt.splitlines() if l.strip()]
        n = len(lines) - 1
        b = int(cnt.get(pd.Timestamp(d), 0))
        if n != b:
            bad_cnt.append((d, k, n, b))
    extra = set(cnt.index.date) - set(days)
    print("row-count mismatches", len(bad_cnt), "build days not in raw", len(extra))
    for x in bad_cnt[:20]: print("  count", x)
    # 2. cell by cell for 300 seeded days
    rnd = random.Random(SEED)
    sample = sorted(rnd.sample(days, 300))
    # force era boundaries
    udays = [d for d in days if files[d][0] == "udiff"]
    force = {days[0], days[-1], udays[0], udays[-1]} if udays else {days[0], days[-1]}
    sample = sorted(set(sample) | force)
    cells = mism = 0
    miss_rows = extra_rows = 0
    examples = []
    cols_cmp = ["isin", "name", "instrument_id"] + NUM
    for d in sample:
        k, p = files[d]
        n, rows = read(p, k)
        g = build[build["date"] == pd.Timestamp(d)]
        bm = {(r.symbol, r.series): r for r in g.itertuples(index=False)}
        miss_rows += len(set(rows) - set(bm)); extra_rows += len(set(bm) - set(rows))
        for key, rec in rows.items():
            b = bm.get(key)
            if b is None: continue
            for c in rec:
                if c in ("symbol", "series"): continue
                if c not in cols_cmp: continue
                cells += 1
                bv = getattr(b, c)
                rv = rec[c]
                if isinstance(rv, float):
                    ok = (math.isnan(rv) and (bv is None or (isinstance(bv, float) and math.isnan(bv)))) or \
                         (not math.isnan(rv) and bv is not None and not (isinstance(bv, float) and math.isnan(bv)) and rv == float(bv))
                else:
                    ok = (rv == bv) or (rv is None and bv is None)
                if not ok:
                    mism += 1
                    if len(examples) < 20: examples.append((d, key, c, rv, bv))
    print(f"sampled days {len(sample)}  cells {cells}  mismatches {mism}  rows missing in build {miss_rows}  extra in build {extra_rows}")
    for e in examples: print("  cell", e)


main()
