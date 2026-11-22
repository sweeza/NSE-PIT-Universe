"""Download press releases that exist on niftyindices.com but are not linked from its press-release page.

Candidates: every date for which a release is held, with suffixes _1.._4. A dead name returns HTML (recorded in
absent.csv), a real one returns a PDF (saved with a manifest row). Plain GETs, 4 workers, 0.2 s pause."""
import datetime as dt
import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor

from nseuniverse import fetch, paths

base = "https://www.niftyindices.com"
pdfdir = paths.PRESS_RAW / "pdf"
have = {p.name for p in pdfdir.glob("*.pdf")}
dates = sorted({m.group(1) for n in have if (m := re.match(r"ind_prs(\d{8})", n))})
absent = fetch._read_absent()
cands = []
for d in dates:
    for s in range(1, 5):
        name = f"ind_prs{d}_{s}.pdf"
        link = f"/Press_Release/{name}"
        if name in have or ("press_release", link) in absent:
            continue
        cands.append((name, link))
print(f"{len(dates)} dates, {len(cands)} candidates", flush=True)


def one(c):
    name, link = c
    st, b = fetch._get(base + link)
    time.sleep(0.2)
    if st == 200 and b[:4] == b"%PDF":
        dest = pdfdir / name
        tmp = dest.with_suffix(".part"); tmp.write_bytes(b); tmp.replace(dest)
        fetch._append(paths.MANIFEST, ["path", "url", "sha256", "bytes", "fetched_utc"],
                      [dest.relative_to(paths.ROOT).as_posix(), base + link, hashlib.sha256(b).hexdigest(), len(b),
                       dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")])
        return "fetched"
    fetch._append(paths.ABSENT, ["source", "date", "http", "note", "checked"],
                  ["press_release", link, st, "not-a-pdf", dt.date.today().isoformat()])
    return "absent"


counts = {}
with ThreadPoolExecutor(4) as ex:
    for k, r in enumerate(ex.map(one, cands), 1):
        counts[r] = counts.get(r, 0) + 1
        if k % 250 == 0:
            print(k, counts, flush=True)
print("done", counts, flush=True)
