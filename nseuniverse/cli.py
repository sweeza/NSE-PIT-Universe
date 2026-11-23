"""Command line: fetch | build | verify | determinism"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
import tempfile
from pathlib import Path

from . import fetch, paths, pipeline, verify


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nseuniverse")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download raw files (the only command that uses the network)")
    f.add_argument("what", choices=["bhavcopy", "indexdaily", "indexhist", "press", "market", "all"])
    sub.add_parser("build", help="offline: raw/ + curated/ -> build/")
    v = sub.add_parser("verify", help="run integrity checks; exit 1 on any FAIL")
    v.add_argument("--only", nargs="*")
    sub.add_parser("determinism", help="build twice into temp dirs and compare checksums")
    sub.add_parser("update", help="fetch recent data, rebuild, and verify")
    a = ap.parse_args(argv)

    if a.cmd == "fetch":
        if a.what in ("bhavcopy", "all"):
            fetch.fetch_range("bhav_udiff"); fetch.fetch_range("bhav_legacy")
        if a.what in ("indexdaily", "all"):
            fetch.fetch_range("index_daily")
        if a.what in ("indexhist", "all"):
            fetch.fetch_index_history()
        if a.what in ("press", "all"):
            fetch.fetch_press_releases()
        if a.what in ("market", "all"):
            for s in ("delivery_mto", "band_changes", "fo_secban", "sec_list"):
                fetch.fetch_range(s)
            print(fetch.fetch_deals_today())
        return 0
    if a.cmd == "update":
        fetch.fetch_range("bhav_udiff")
        fetch.fetch_range("index_daily")
        for s in ("delivery_mto", "band_changes", "fo_secban", "sec_list"):
            fetch.fetch_range(s)
        print(fetch.fetch_deals_today())
        print(pipeline.build_all())
        res = verify.run()
        fails = [r for r in res if r.status == "FAIL"]
        print(f"\n{len(res) - len(fails)}/{len(res)} checks without FAIL")
        return 1 if fails else 0
    if a.cmd == "build":
        print(pipeline.build_all())
        return 0
    if a.cmd == "verify":
        res = verify.run(a.only)
        fails = [r for r in res if r.status == "FAIL"]
        print(f"\n{len(res) - len(fails)}/{len(res)} checks without FAIL")
        return 1 if fails else 0
    if a.cmd == "determinism":
        sums = []
        for i in range(2):
            d = Path(tempfile.mkdtemp(prefix=f"nseu_det{i}_"))
            pipeline.build_all(d)
            sums.append((d / "checksums.txt").read_text())
            shutil.rmtree(d, ignore_errors=True)
        same = sums[0] == sums[1]
        print("DETERMINISTIC" if same else "NOT DETERMINISTIC")
        return 0 if same else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
