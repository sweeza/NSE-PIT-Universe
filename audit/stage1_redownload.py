"""Stage 1.1: re-download a seeded sample of raw files with plain GETs (one at a time, 1.2 s apart, generic User-Agent) into a scratch
folder and compare SHA-256 with data/raw/manifest.csv. Nothing is written to data/raw. Seed 20261122.
Usage: python -I audit/stage1_redownload.py scratchdir"""
import sys, time, random, hashlib, urllib.request, urllib.error
from pathlib import Path
import pandas as pd
R = Path(__file__).resolve().parents[1]; S = Path(sys.argv[1]); S.mkdir(parents=True, exist_ok=True)
m = pd.read_csv(R / "data/raw/manifest.csv", encoding="latin-1")
rng = random.Random(20261122)
leg = m[m.path.str.contains("bhavcopy/legacy")].sort_values("path"); udf = m[m.path.str.contains("bhavcopy/udiff")].sort_values("path")
def pick(df, n, edge=3):
    idx = list(range(len(df))); keep = set(idx[:edge] + idx[-edge:]); rest = [i for i in idx if i not in keep]
    return df.iloc[sorted(keep | set(rng.sample(rest, n - len(keep))))]
sample = pd.concat([pick(leg, 100).assign(g="bhav_legacy"), pick(udf, 50).assign(g="bhav_udiff"),
                    m[m.path.str.contains("indexdaily")].sample(20, random_state=20261122).assign(g="index_daily"),
                    m[m.path.str.contains("data/raw/constituents/")].assign(g="constituent"),
                    m[m.path.str.contains("pressreleases/pdf")].sample(100, random_state=20261122).assign(g="press")])
print(len(sample), "files", sample.bytes.sum() / 1e6, "MB expected", flush=True)
rows = []
for r in sample.itertuples():
    try:
        req = urllib.request.Request(r.url, headers={"User-Agent": "Mozilla/5.0 (research re-check)", "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=60) as f: b = f.read(); st = f.status
    except urllib.error.HTTPError as e: b, st = b"", e.code
    except Exception as e: b, st = b"", type(e).__name__
    h = hashlib.sha256(b).hexdigest() if b else ""
    rows.append((r.g, r.path, r.url, st, len(b), r.bytes, h == r.sha256, h))
    time.sleep(1.2)
    if len(rows) % 50 == 0: print(len(rows), "done", flush=True)
o = pd.DataFrame(rows, columns=["group", "path", "url", "http", "got_bytes", "manifest_bytes", "match", "got_sha"])
o.to_csv(S / "stage1_results.csv", index=False)
print(o.groupby("group").agg(n=("match", "size"), match=("match", "sum"), non200=("http", lambda x: int((x != 200).sum()))))
