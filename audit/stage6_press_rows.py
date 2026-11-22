"""Stage 6.6 (mechanical, all rows): each curated press event's symbol must appear in the cited release text,
and the event date must fall 0..150 days after the release date (taken from the file name ind_prsDDMMYYYY)."""
import re, pandas as pd
from pathlib import Path
e = pd.read_csv("data/curated/index_events_press.csv", dtype=str).fillna("")
T = Path("data/build/press_text"); cache = {}
def txt(n):
    if n not in cache:
        p = T / (Path(n).stem + ".txt"); cache[n] = p.read_text(errors="replace") if p.exists() else None
    return cache[n]
bad_sym, bad_date, no_text, total = [], [], [], 0
for r in e.itertuples():
    files = [Path(s.strip()).name for s in r.source.split(";") if s.strip()]
    total += 1
    ok_sym = False; ok_date = False; have = False
    for f in files:
        t = txt(f)
        if t is None: continue
        have = True
        if re.search(r"(?<![A-Z0-9&-])" + re.escape(r.symbol) + r"(?![A-Z0-9&-])", t): ok_sym = True
        m = re.match(r"ind_prs(\d{2})(\d{2})(\d{4})", f)
        if m:
            rd = pd.Timestamp(f"{m.group(3)}-{m.group(2)}-{m.group(1)}"); dd = (pd.Timestamp(r.date) - rd).days
            if 0 <= dd <= 150: ok_date = True
    if not have: no_text.append(r)
    else:
        if not ok_sym: bad_sym.append(r)
        if not ok_date: bad_date.append(r)
print("rows", total, "| no extractable text", len(no_text), "| symbol absent from cited text", len(bad_sym), "| date outside 0..150d of release", len(bad_date))
for name, L in (("symbol absent", bad_sym), ("date window", bad_date), ("no text", no_text)):
    print("--", name, "(first 12)")
    for r in L[:12]: print("  ", r.index_key, r.date, r.symbol, r.action, r.source[:70])
import collections
print("symbol-absent by index:", collections.Counter(r.index_key for r in bad_sym).most_common(6))
print("symbol-absent by source:", collections.Counter(r.source for r in bad_sym).most_common(8))
rest = [r for r in bad_sym if "ind_prs23082021" not in r.source]
print("excluding the image-only 2021 release:", len(rest))
for r in rest[:25]: print("  ", r.index_key, r.date, r.symbol, r.action, r.source[-40:])
