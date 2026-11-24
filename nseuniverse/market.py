"""Delivery quantity (NSE MTO file) attached to the bhavcopy.

Raw files live in data/raw/market/delivery/ (fetch.py). The parser returns what the file says; nothing is filled.
Every row is attached to a security (sec_id) through the bhavcopy row of the same day, symbol and series.

Table written to data/build/market/:
  delivery.parquet   date, symbol, series, traded_qty, deliv_qty, deliv_pct, sec_id   (NSE MTO file)

Price bands, ASM/GSM, F&O, deals, impact cost and shares outstanding were removed from the build on 2026-11-24
(git tag full-2026-11-24 holds that version).
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import paths


def _date_from_name(name: str) -> pd.Timestamp:
    m = re.search(r"(\d{2})(\d{2})(\d{4})", name)
    return pd.Timestamp(int(m.group(3)), int(m.group(2)), int(m.group(1)))


def parse_mto(raw: bytes, date: pd.Timestamp) -> pd.DataFrame:
    """Security-wise delivery position. Data rows start with record type 20:
    20, serial, symbol, series, quantity traded, deliverable quantity, percent."""
    rows = []
    for line in raw.decode("latin-1").splitlines():
        p = line.strip().split(",")
        if len(p) == 7 and p[0] == "20":
            rows.append((date, p[2].strip(), p[3].strip(), p[4], p[5], p[6]))
    df = pd.DataFrame(rows, columns=["date", "symbol", "series", "traded_qty", "deliv_qty", "deliv_pct"])
    for c in ("traded_qty", "deliv_qty", "deliv_pct"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


class UnknownLayout(ValueError):
    """A file whose header is not one of the known layouts. It is skipped and counted, never guessed."""


SKIPPED: list[str] = []          # files refused for an unknown layout in the last build()


def _read_dir(kind: str, pattern: str, parser) -> pd.DataFrame:
    frames = []
    for f in sorted((paths.MARKET_RAW / kind).rglob(pattern)):
        try:
            d = parser(f.read_bytes(), _date_from_name(f.name))
        except UnknownLayout:
            SKIPPED.append(f.name)
            continue
        if len(d):
            frames.append(d)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _attach(df: pd.DataFrame, t: pd.DataFrame) -> pd.DataFrame:
    """sec_id from the bhavcopy row with the same date, symbol and series; if the series is not there that day,
    from the same date and symbol when that identifies exactly one security."""
    if df.empty:
        return df.assign(sec_id=pd.Series([], dtype=object))
    k = t[["date", "symbol", "series", "sec_id"]].drop_duplicates(["date", "symbol", "series"])
    has_series = "series" in df.columns
    out = df.merge(k, on=["date", "symbol", "series"], how="left") if has_series else df.assign(sec_id=np.nan)
    out["sec_id"] = out["sec_id"].astype(object)
    miss = out["sec_id"].isna()
    if miss.any():
        keys = out.loc[miss, ["date", "symbol"]].drop_duplicates()
        cand = keys.merge(t[["date", "symbol", "sec_id"]].drop_duplicates(), on=["date", "symbol"], how="inner")
        n = cand.groupby(["date", "symbol"]).sec_id.transform("nunique")
        one = cand[n == 1].drop_duplicates(["date", "symbol"])
        fill = out.loc[miss, ["date", "symbol"]].merge(one, on=["date", "symbol"], how="left")["sec_id"].values
        out.loc[miss, "sec_id"] = fill
    return out


def build(out: Path, t: pd.DataFrame) -> dict:
    """t: the canonical bhavcopy table with sec_id. Returns row counts and the delivery-vs-bhavcopy volume check."""
    out.mkdir(parents=True, exist_ok=True)
    SKIPPED.clear()
    d = _attach(_read_dir("delivery", "MTO_*.DAT", parse_mto), t)
    if len(d):
        d = d.sort_values(["date", "symbol", "series"], kind="mergesort").reset_index(drop=True)
    d.to_parquet(out / "delivery.parquet", index=False, compression="zstd", compression_level=9)
    info = {"delivery": {"rows": len(d), "unattached": int(d["sec_id"].isna().sum()) if len(d) else 0},
            "skipped_unknown_layout": sorted(SKIPPED)}
    if len(d):
        v = t[["date", "symbol", "series", "volume"]].drop_duplicates(["date", "symbol", "series"])
        m = d.merge(v, on=["date", "symbol", "series"], how="inner")
        info["delivery_volume_match"] = {"compared": len(m), "equal": int((m.traded_qty == m.volume).sum())}
    return info
