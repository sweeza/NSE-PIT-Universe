"""Filesystem layout. Everything lives under one root; nothing is written elsewhere."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("NSEUNIVERSE_ROOT", Path(__file__).resolve().parents[1]))
DATA = ROOT / "data"
RAW = DATA / "raw"            # exactly as downloaded; never edited
CURATED = DATA / "curated"    # hand-entered facts, each citing a file in raw/
BUILD = DATA / "build"        # derived; safe to delete and regenerate

BHAV_RAW = RAW / "bhavcopy"
INDEX_DAILY_RAW = RAW / "indexdaily"
INDEX_HIST_RAW = RAW / "indexhist"
PRESS_RAW = RAW / "pressreleases"
MARKET_RAW = RAW / "market"      # delivery (MTO), price-band changes, security lists, F&O ban lists, deals
HELD = RAW / "held"           # inputs obtained before this rebuild (origin not re-verified)

MANIFEST = RAW / "manifest.csv"   # path,url,sha256,bytes,fetched_utc
ABSENT = RAW / "absent.csv"       # source,date,http,note   (days NSE has no file for)

START_DATE = "2004-01-01"
