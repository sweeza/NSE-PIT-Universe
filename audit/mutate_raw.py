"""Stage 7 (raw layer): inject one error into a RAW input of a scratch root, rebuild, run verify checks.
Usage: python audit/mutate_raw.py NAME SCRATCH_DIR [--fix-manifest]
NAME: cell_small | cell_big | ratio_flip | delete_raw
 cell_small   RELIANCE close x1.015 on one 2015 legacy bhavcopy day
 cell_big     RELIANCE close x10 (a typo) on the same day
 ratio_flip   WIPRO 2010-06-15 'Bonus 2:3' -> 'Bonus 3:2' in the held corporate-action JSON
 delete_raw   remove one raw bhavcopy zip that the manifest lists
--fix-manifest rewrites the manifest hash of the changed file, i.e. an error that is consistent with the manifest.
Real raw data is never modified: the scratch root holds junctions to unchanged folders and copies of changed ones.
"""
import csv, hashlib, io, os, shutil, subprocess, sys, zipfile, time
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
name, scratch = sys.argv[1], Path(sys.argv[2])
fix = "--fix-manifest" in sys.argv
root = scratch / (name + ("_fix" if fix else "_nofix"))
if root.exists(): subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(root)], check=False, capture_output=True)
def junc(link, target): subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
RAW = REPO / "data" / "raw"
(root / "data" / "build").mkdir(parents=True)
shutil.copytree(REPO / "data" / "curated", root / "data" / "curated")
rraw = root / "data" / "raw"; rraw.mkdir()
shutil.copy(RAW / "manifest.csv", rraw / "manifest.csv"); shutil.copy(RAW / "absent.csv", rraw / "absent.csv")
touched = None   # (relative path, new bytes or None=delete)
TARGET = "cm10JUN2015bhav.csv.zip"
def mod_zip(factor):
    src = next((RAW / "bhavcopy" / "legacy" / "2015").glob(TARGET))
    z = zipfile.ZipFile(src); inner = z.namelist()[0]; txt = z.read(inner).decode("latin1").split("\n")
    hdr = [h.strip() for h in txt[0].split(",")]; ic = hdr.index("CLOSE")
    for i, l in enumerate(txt):
        f = l.split(",")
        if len(f) > ic and f[0] == "RELIANCE" and f[1] == "EQ":
            old = f[ic]; f[ic] = f"{float(old)*factor:.2f}"; txt[i] = ",".join(f); print("changed", old, "->", f[ic]); break
    else: raise SystemExit("row not found")
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as o: o.writestr(inner, "\n".join(txt).encode("latin1"))
    return src, b.getvalue()
if name in ("cell_small", "cell_big", "delete_raw"):
    src, new = mod_zip(1.015 if name == "cell_small" else 10) if name != "delete_raw" else (next((RAW/"bhavcopy"/"legacy"/"2015").glob(TARGET)), None)
    rel = src.relative_to(REPO).as_posix()
    # bhavcopy/legacy/<year> junctions except 2015, which is copied
    (rraw / "bhavcopy" / "legacy").mkdir(parents=True)
    junc(rraw / "bhavcopy" / "udiff", RAW / "bhavcopy" / "udiff")
    for y in (RAW / "bhavcopy" / "legacy").iterdir():
        if y.name == "2015": shutil.copytree(y, rraw / "bhavcopy" / "legacy" / "2015")
        else: junc(rraw / "bhavcopy" / "legacy" / y.name, y)
    for d in RAW.iterdir():
        if d.is_dir() and d.name != "bhavcopy": junc(rraw / d.name, d)
    dst = root / rel
    if new is None: dst.unlink()
    else: dst.write_bytes(new)
    touched = (rel, new)
elif name == "ratio_flip":
    for d in RAW.iterdir():
        if d.is_dir() and d.name != "held": junc(rraw / d.name, d)
    shutil.copytree(RAW / "held", rraw / "held")
    p = rraw / "held" / "raw_corporate_actions_1995_2026.json"
    t = p.read_text(encoding="utf-8")
    key = '"exDate": "15-Jun-2010"'
    # locate the WIPRO record
    i = 0; n = 0
    while True:
        i = t.find("Bonus 2:3 And Final Dividend Rs.6/- Per Share", i)
        if i < 0: break
        seg = t[max(0, i - 600): i + 600]
        if '"symbol": "WIPRO"' in seg and key in seg:
            t = t[:i] + "Bonus 3:2 And Final Dividend Rs.6/- Per Share" + t[i + len("Bonus 2:3 And Final Dividend Rs.6/- Per Share"):]; n += 1; break
        i += 10
    assert n == 1, "record not found"
    p.write_text(t, encoding="utf-8", newline="")
    touched = ("data/raw/held/raw_corporate_actions_1995_2026.json", p.read_bytes())
if fix and touched and touched[1] is not None:
    rows = list(csv.DictReader(open(rraw / "manifest.csv", newline="", encoding="latin1")))
    fn = list(rows[0].keys())
    for r in rows:
        if r["path"] == touched[0]:
            r["sha256"] = hashlib.sha256(touched[1]).hexdigest(); r["bytes"] = str(len(touched[1]))
    with open(rraw / "manifest.csv", "w", newline="", encoding="latin1") as f:
        w = csv.DictWriter(f, fn); w.writeheader(); w.writerows(rows)
print("scratch root", root, "touched", touched[0] if touched else None, "fix_manifest", fix)
checks = ["manifest"] if not fix else ["manifest", "bhavcopy_lossless", "overlap_days", "calendar", "table_sanity", "identity", "actions", "adjusted_continuity"]
code = (f"import sys;sys.path.insert(0,r'{REPO}');import time;t=time.time();from nseuniverse import pipeline,verify\n"
        + ("" if not fix else "print(pipeline.build_all(with_indices=False),flush=True)\n")
        + f"r=verify.run({checks!r})\n"
        "print('DONE',round(time.time()-t))\n")
env = dict(os.environ, NSEUNIVERSE_ROOT=str(root))
p = subprocess.run([sys.executable, "-I", "-c", code], env=env, capture_output=True, text=True, cwd=str(root))
print((p.stdout + p.stderr)[-6000:])
