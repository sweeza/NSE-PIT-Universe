"""Bhavcopy parsers: raw NSE zip files -> one canonical long table.

Canonical columns (one row per date, symbol, series):
  date, symbol, series, isin, open, high, low, close, last, prev_close,
  volume, turnover, trades, name, instrument_id, settle_price, src
A field the era did not publish is null. Nothing is filled, clipped or reordered
within a row; values are exactly what the file says.

The format is chosen by the file header, not by the date.
"""
from __future__ import annotations

import datetime as dt
import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from . import paths

COLUMNS = ["date", "symbol", "series", "isin", "open", "high", "low", "close", "last",
           "prev_close", "volume", "turnover", "trades", "name", "instrument_id",
           "settle_price", "src"]
_NUM = ["open", "high", "low", "close", "last", "prev_close", "volume", "turnover",
        "trades", "settle_price"]

_LEGACY_MAP = {"SYMBOL": "symbol", "SERIES": "series", "OPEN": "open", "HIGH": "high",
               "LOW": "low", "CLOSE": "close", "LAST": "last", "PREVCLOSE": "prev_close",
               "TOTTRDQTY": "volume", "TOTTRDVAL": "turnover", "TOTALTRADES": "trades",
               "ISIN": "isin", "TIMESTAMP": "date"}
_UDIFF_MAP = {"TradDt": "date", "TckrSymb": "symbol", "SctySrs": "series", "ISIN": "isin",
              "OpnPric": "open", "HghPric": "high", "LwPric": "low", "ClsPric": "close",
              "LastPric": "last", "PrvsClsgPric": "prev_close", "TtlTradgVol": "volume",
              "TtlTrfVal": "turnover", "TtlNbOfTxsExctd": "trades", "FinInstrmNm": "name",
              "FinInstrmId": "instrument_id", "SttlmPric": "settle_price"}


class BhavcopyError(ValueError):
    pass


def _csv_from_zip(blob: bytes) -> bytes:
    z = zipfile.ZipFile(io.BytesIO(blob))
    names = z.namelist()
    if len(names) != 1:
        raise BhavcopyError(f"expected 1 member in zip, got {names}")
    return z.read(names[0])


def _num(s: pd.Series, col: str, ctx: str) -> pd.Series:
    s = s.str.strip().replace({"": np.nan, "-": np.nan})
    out = pd.to_numeric(s, errors="coerce")
    bad = out.isna() & s.notna()
    if bad.any():
        raise BhavcopyError(f"{ctx}: non-numeric {col}: {s[bad].unique()[:3]}")
    return out.astype("float64")


def parse(blob: bytes, ctx: str = "") -> pd.DataFrame:
    """Parse one zipped bhavcopy (either era) into the canonical frame."""
    raw = _csv_from_zip(blob)
    df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding="latin1",
                     index_col=False)
    df.columns = [c.strip() for c in df.columns]
    cols = set(df.columns)
    if {"SYMBOL", "SERIES", "TIMESTAMP"} <= cols:
        mp, src = _LEGACY_MAP, "legacy"
    elif {"TckrSymb", "SctySrs", "TradDt"} <= cols:
        mp, src = _UDIFF_MAP, "udiff"
        if set(df["Sgmt"].unique()) != {"CM"}:
            raise BhavcopyError(f"{ctx}: unexpected segment {df['Sgmt'].unique()}")
    else:
        raise BhavcopyError(f"{ctx}: unrecognised header {list(df.columns)[:8]}")
    keep = [c for c in mp if c in df.columns]
    df = df[keep].rename(columns=mp)
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].str.strip()
    if src == "legacy":
        raw_d = df["date"]
        df["date"] = pd.to_datetime(raw_d, format="%d-%b-%Y", errors="coerce")
        bad = df["date"].isna()
        if bad.any():   # some files use a two-digit year; accept exactly that one alternative
            df.loc[bad, "date"] = pd.to_datetime(raw_d[bad], format="%d-%b-%y", errors="raise")
    else:
        df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="raise")
    if df["date"].nunique() != 1:
        raise BhavcopyError(f"{ctx}: file holds several dates {df['date'].unique()[:3]}")
    for c in _NUM:
        if c in df.columns:
            df[c] = _num(df[c], c, ctx)
    for c in ("isin", "name", "instrument_id"):
        if c in df.columns:
            df[c] = df[c].replace({"": None})
    df["src"] = src
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = np.nan if c in _NUM else None
    df = df[COLUMNS]
    if df.duplicated(["symbol", "series"]).any():
        raise BhavcopyError(f"{ctx}: duplicate (symbol, series) rows")
    return df


def raw_files() -> list[tuple[dt.date, str, Path]]:
    """Every stored bhavcopy file as (date, kind, path), sorted."""
    out = []
    for p in sorted(paths.BHAV_RAW.rglob("*.zip")):
        n = p.name
        if n.startswith("BhavCopy_NSE_CM"):
            d = dt.datetime.strptime(n.split("_")[6], "%Y%m%d").date(); k = "udiff"
        else:
            d = dt.datetime.strptime(n[2:11], "%d%b%Y").date(); k = "legacy"
        out.append((d, k, p))
    return sorted(out, key=lambda t: (t[0], t[1]))


def select_per_day(files):
    """One file per date. Where both formats exist the richer UDiFF file wins; the
    overlap days are compared in verify.py."""
    by = {}
    for d, k, p in files:
        if d not in by or k == "udiff":
            by[d] = (k, p)
    return by


def _parse_path(path_str: str) -> pd.DataFrame:
    p = Path(path_str)
    return parse(p.read_bytes(), ctx=p.name)


def read_all(workers: int | None = None) -> pd.DataFrame:
    """Parse every selected raw file into one sorted canonical table (no sec_id yet).
    Files are parsed in parallel; the final sort makes the result independent of scheduling."""
    import os
    from concurrent.futures import ProcessPoolExecutor
    chosen = sorted(select_per_day(raw_files()).items())
    workers = workers or min(8, os.cpu_count() or 2)
    with ProcessPoolExecutor(workers) as ex:
        parts = list(ex.map(_parse_path, [str(p) for _, (_, p) in chosen], chunksize=32))
    for (d, (k, p)), df in zip(chosen, parts):
        if df["date"].iloc[0].date() != d:
            raise BhavcopyError(f"{p.name}: file date {df['date'].iloc[0].date()} != name date {d}")
    return pd.concat(parts, ignore_index=True).sort_values(
        ["date", "symbol", "series"], kind="mergesort").reset_index(drop=True)


def write(t: pd.DataFrame, out_dir: Path | None = None) -> dict:
    """One parquet per year; fixed writer settings so identical input gives identical bytes."""
    out_dir = out_dir or paths.BUILD / "bhavcopy"
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("bhavcopy_*.parquet"):
        f.unlink()
    for y, g in t.groupby(t["date"].dt.year):
        g.to_parquet(out_dir / f"bhavcopy_{y}.parquet", index=False, compression="zstd", compression_level=9)
    return {"days": int(t["date"].nunique()), "rows": len(t), "years": sorted(int(y) for y in t["date"].dt.year.unique())}


def load(start=None, end=None, build_dir: Path | None = None) -> pd.DataFrame:
    d = (build_dir or paths.BUILD) / "bhavcopy"
    parts = [pd.read_parquet(f) for f in sorted(d.glob("bhavcopy_*.parquet"))]
    t = pd.concat(parts, ignore_index=True)
    if start is not None:
        t = t[t["date"] >= pd.Timestamp(start)]
    if end is not None:
        t = t[t["date"] <= pd.Timestamp(end)]
    return t.reset_index(drop=True)
