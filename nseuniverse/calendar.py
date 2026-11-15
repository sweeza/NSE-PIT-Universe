"""Trading calendar derived from evidence, not from a holiday list.

A date is a trading day iff NSE published a bhavcopy for it. The independent cross-check is the
daily index file (a second NSE publication): from 2012-02-21 both must exist on exactly the same
days. Any disagreement is reported by verify.py.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from . import bhavcopy, paths


def bhavcopy_days() -> list[dt.date]:
    return sorted({d for d, _, _ in bhavcopy.raw_files()})


def index_days() -> list[dt.date]:
    out = []
    for p in sorted(paths.INDEX_DAILY_RAW.rglob("ind_close_all_*.csv")):
        out.append(dt.datetime.strptime(p.stem.split("_")[-1], "%d%m%Y").date())
    return sorted(out)


def trading_days() -> pd.DatetimeIndex:
    return pd.DatetimeIndex(bhavcopy_days(), name="date")


def build() -> pd.DataFrame:
    """One row per calendar day in range: whether each publication exists."""
    b = set(bhavcopy_days())
    i = set(index_days())
    if not b:
        return pd.DataFrame(columns=["date", "bhavcopy", "index_file", "weekday"])
    rng = pd.date_range(min(b), max(b), freq="D")
    df = pd.DataFrame({"date": rng})
    df["bhavcopy"] = df["date"].dt.date.isin(b)
    df["index_file"] = df["date"].dt.date.isin(i)
    df["weekday"] = df["date"].dt.dayofweek
    return df
