"""Market-activity files: delivery quantity, price bands and their changes, ASM/GSM remarks, F&O ban lists.

Raw files live in data/raw/market/ (fetch.py). Parsers return what the file says; nothing is filled.
Every row is attached to a security (sec_id) through the bhavcopy row of the same day, symbol and series.

Tables written to data/build/market/:
  delivery.parquet      date, symbol, series, traded_qty, deliv_qty, deliv_pct, sec_id   (NSE MTO file, 2005-)
  band_changes.parquet  date, symbol, series, band_from, band_to, sec_id                 (daily change file, 2010-)
  sec_list.parquet      date, symbol, series, band, remarks, sec_id                      (security list, 2020-)
  fo_ban.parquet        date, symbol, sec_id                                             (securities in the F&O ban period)
"""
from __future__ import annotations

import csv
import datetime as dt
import io
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


def _frame(raw: bytes, need: list[str]) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), dtype=str, encoding="latin-1", index_col=False).fillna("")
    df.columns = [c.strip().lower().rstrip(".").strip() for c in df.columns]
    if any(n not in df.columns for n in need):
        raise UnknownLayout(f"columns {list(df.columns)} lack {need}")
    return df


def parse_band_changes(raw: bytes, date: pd.Timestamp) -> pd.DataFrame:
    """Columns: Sr. No(.), Symbol, Series, Security Name, From, To (header spelling varies; two 2017 files use
    'Min Band or no band' / 'Max Band or no band' and are refused as UnknownLayout)."""
    df = _frame(raw, ["symbol", "series", "from", "to"])
    out = pd.DataFrame({"date": date, "symbol": df["symbol"].str.strip(), "series": df["series"].str.strip(),
                        "band_from": df["from"].str.strip(), "band_to": df["to"].str.strip()})
    return out[~out.symbol.str.lower().isin(["", "nil"])].reset_index(drop=True)       # a "Nil" row means no change that day


def parse_sec_list(raw: bytes, date: pd.Timestamp) -> pd.DataFrame:
    df = _frame(raw, ["symbol", "series", "band", "remarks"])
    out = pd.DataFrame({"date": date, "symbol": df["symbol"].str.strip(), "series": df["series"].str.strip(),
                        "band": df["band"].str.strip(), "remarks": df["remarks"].str.strip().replace("-", "")})
    return out[out.symbol != ""].reset_index(drop=True)


def parse_secban(raw: bytes, date: pd.Timestamp) -> pd.DataFrame:
    """'Securities in Ban For Trade Date DD-MON-YYYY: NIL' or the same line followed by one security per line
    (an optional serial number first)."""
    lines = [l.strip() for l in raw.decode("latin-1").splitlines() if l.strip()]
    syms = []
    if lines and lines[0].upper().rstrip().endswith("NIL"):
        return pd.DataFrame({"date": pd.Series([], dtype="datetime64[ns]"), "symbol": pd.Series([], dtype=str)})
    for l in lines[1:] if lines and lines[0].lower().startswith("securities in ban") else lines:
        f = [x.strip() for x in l.split(",") if x.strip()]
        if f and f[0].isdigit():
            f = f[1:]
        syms += [x for x in f if re.fullmatch(r"[A-Z0-9&\-]+", x)]
    return pd.DataFrame({"date": date, "symbol": sorted(set(syms))})


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
    info = {}
    SKIPPED.clear()
    tabs = {
        "delivery": _read_dir("delivery", "MTO_*.DAT", parse_mto),
        "band_changes": _read_dir("bandchanges", "eq_band_changes_*.csv", parse_band_changes),
        "sec_list": _read_dir("seclist", "sec_list_*.csv", parse_sec_list),
        "fo_ban": _read_dir("fosecban", "fo_secban_*.csv", parse_secban),
    }
    for name, df in tabs.items():
        df = _attach(df, t)
        tabs[name] = df
        if len(df):
            df = df.sort_values([c for c in ("date", "symbol", "series") if c in df.columns], kind="mergesort").reset_index(drop=True)
        df.to_parquet(out / f"{name}.parquet", index=False, compression="zstd", compression_level=9)
        info[name] = {"rows": len(df), "unattached": int(df["sec_id"].isna().sum()) if len(df) else 0}
    info["skipped_unknown_layout"] = sorted(SKIPPED)
    d = tabs["delivery"]
    if len(d):
        v = t[["date", "symbol", "series", "volume"]].drop_duplicates(["date", "symbol", "series"])
        m = d.merge(v, on=["date", "symbol", "series"], how="inner")
        info["delivery_volume_match"] = {"compared": len(m), "equal": int((m.traded_qty == m.volume).sum())}
    return info
