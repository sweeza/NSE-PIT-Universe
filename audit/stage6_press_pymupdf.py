"""Stage 6.6 (independent extractor): re-read every cited press PDF with PyMuPDF (not the project's text files).
Checks, for ALL curated press events: (a) symbol token present, (b) direction: the nearest preceding
'being included'/'being excluded' phrase before some occurrence of the symbol agrees with IN/OUT."""
import re, collections, pandas as pd, pymupdf
from pathlib import Path
e = pd.read_csv("data/curated/index_events_press.csv", dtype=str).fillna("")
R = Path("data/raw/pressreleases/pdf"); cache = {}
def text(n):
    if n not in cache:
        p = R / n
        cache[n] = "\n".join(pg.get_text() for pg in pymupdf.open(p)) if p.exists() else None
    return cache[n]
res = collections.Counter(); bad = []
for r in e.itertuples():
    files = [Path(s.strip()).name for s in r.source.split(";") if s.strip()]
    ok_sym = ok_dir = False
    for f in files:
        t = text(f)
        if not t: continue
        for m in re.finditer(r"(?<![A-Z0-9&])" + re.escape(r.symbol) + r"(?![A-Z0-9&])", t):
            ok_sym = True
            pre = t[:m.start()].lower()
            i, x = pre.rfind("being included"), pre.rfind("being excluded")
            # also accept 'will replace'/'replaced' style tables: fall back to include/exclude words
            if i < 0 and x < 0: i, x = pre.rfind("includ"), pre.rfind("exclud")
            d = "IN" if i > x else "OUT"
            if d == r.action: ok_dir = True; break
        if ok_dir: break
    res[(ok_sym, ok_dir)] += 1
    if not (ok_sym and ok_dir): bad.append((r.index_key, r.date, r.symbol, r.action, r.source[-34:], ok_sym))
print("rows", len(e), "| (symbol_found, direction_agrees):", dict(res))
for b in bad[:40]: print("  ", b)
print("by index:", collections.Counter(b[0] for b in bad).most_common(8))
