"""Index values from two independent NSE publications.

  daily files   nsearchives .../ind_close_all_DDMMYYYY.csv   2012-02-21 ->   (OHLC, PE, PB, yield)
  history API   niftyindices.com BackPage endpoints          from each index's base date
                (price OHLC, total-return, PE/PB/yield)

Both are parsed into the same long table with a `src` column. Nothing is merged silently:
`values()` prefers the daily file where it exists and the history API otherwise, and verify.py
compares the two wherever both cover a date.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import paths

COLS = ["index_key", "index_name", "date", "open", "high", "low", "close", "tri", "ntr",
        "pe", "pb", "div_yield", "volume", "turnover", "src"]


def key(name: str) -> str:
    return re.sub(r"[^A-Z0-9&]+", "", name.upper())


def name_map() -> dict[str, str]:
    """any published spelling (trading or long name) -> canonical long name key."""
    d = json.loads((paths.INDEX_HIST_RAW / "IndexMapping.json").read_text(encoding="utf-8-sig"))
    m = {}
    for r in d:
        canon = key(r["Index_long_name"])
        m[canon] = canon
        m[key(r["Trading_Index_Name"])] = canon
    ren = paths.CURATED / "index_renames.csv"
    if ren.exists():
        for r in pd.read_csv(ren).itertuples():
            m[key(r.old_name)] = key(r.canonical_name)
    return m


def _num(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip().replace({"-": np.nan, "": np.nan, "nan": np.nan, "None": np.nan})
    return pd.to_numeric(s.str.replace(",", ""), errors="raise").astype("float64")


def _daily_date(col: pd.Series) -> pd.Series:
    """Daily files use DD-MM-YYYY; a few use DD/MM/YYYY. Exactly those two are accepted."""
    c = col.str.strip()
    d = pd.to_datetime(c, format="%d-%m-%Y", errors="coerce")
    bad = d.isna()
    if bad.any():
        d[bad] = pd.to_datetime(c[bad], format="%d/%m/%Y", errors="raise")
    return d


def parse_daily(blob: bytes, ctx: str = "") -> pd.DataFrame:
    import io
    df = pd.read_csv(io.BytesIO(blob), dtype=str, keep_default_na=False, encoding="latin1")
    df.columns = [c.strip() for c in df.columns]
    need = {"Index Name", "Index Date", "Closing Index Value"}
    if not need <= set(df.columns):
        raise ValueError(f"{ctx}: unexpected index file header {list(df.columns)}")
    out = pd.DataFrame({
        "index_name": df["Index Name"].str.strip(),
        "date": _daily_date(df["Index Date"]),
        "open": _num(df["Open Index Value"]), "high": _num(df["High Index Value"]),
        "low": _num(df["Low Index Value"]), "close": _num(df["Closing Index Value"]),
        "volume": _num(df["Volume"]) if "Volume" in df else np.nan,
        "turnover": _num(df["Turnover (Rs. Cr.)"]) if "Turnover (Rs. Cr.)" in df else np.nan,
        "pe": _num(df["P/E"]) if "P/E" in df else np.nan,
        "pb": _num(df["P/B"]) if "P/B" in df else np.nan,
        "div_yield": _num(df["Div Yield"]) if "Div Yield" in df else np.nan,
    })
    if out["date"].nunique() != 1:
        raise ValueError(f"{ctx}: several dates in one index file")
    return out


def daily_table() -> pd.DataFrame:
    parts = []
    for p in sorted(paths.INDEX_DAILY_RAW.rglob("ind_close_all_*.csv")):
        parts.append(parse_daily(p.read_bytes(), p.name))
    if not parts:
        return pd.DataFrame(columns=COLS)
    t = pd.concat(parts, ignore_index=True)
    m = name_map()
    t["index_key"] = t["index_name"].map(lambda n: m.get(key(n), key(n)))
    t["src"] = "daily"
    for c in ("tri", "ntr"):
        t[c] = np.nan
    return t[COLS]


def _hist_frames(endpoint: str) -> pd.DataFrame:
    rows = []
    for p in sorted((paths.INDEX_HIST_RAW / endpoint).glob("*.json")):
        for r in json.loads(p.read_text(encoding="utf-8")):
            rows.append(r)
    return pd.DataFrame(rows)


def history_table() -> pd.DataFrame:
    m = name_map()
    px = _hist_frames("price")
    if px.empty:
        return pd.DataFrame(columns=COLS)
    px["index_name"] = px["INDEX_NAME"].str.strip()
    px["date"] = pd.to_datetime(px["HistoricalDate"], format="%d %b %Y")
    for c, n in (("open", "OPEN"), ("high", "HIGH"), ("low", "LOW"), ("close", "CLOSE")):
        px[c] = _num(px[n])
    px = px[["index_name", "date", "open", "high", "low", "close"]]
    tri = _hist_frames("tri")
    if not tri.empty:
        tri["index_name"] = tri["Index Name"].str.strip()
        tri["date"] = pd.to_datetime(tri["Date"], format="%d %b %Y")
        tri["tri"] = _num(tri["TotalReturnsIndex"]); tri["ntr"] = _num(tri["NTR_Value"])
        tri = tri[["index_name", "date", "tri", "ntr"]]
        px = px.merge(tri, on=["index_name", "date"], how="outer")
    pe = _hist_frames("pepb")
    if not pe.empty:
        pe["index_name"] = pe["Index Name"].str.strip()
        pe["date"] = pd.to_datetime(pe["DATE"], format="%d %b %Y")
        pe["pe"] = _num(pe["pe"]); pe["pb"] = _num(pe["pb"]); pe["div_yield"] = _num(pe["divYield"])
        px = px.merge(pe[["index_name", "date", "pe", "pb", "div_yield"]], on=["index_name", "date"], how="outer")
    for c in COLS:
        if c not in px:
            px[c] = np.nan
    px["index_key"] = px["index_name"].map(lambda n: m.get(key(n), key(n)))
    px["src"] = "history"
    return px[COLS].drop_duplicates(["index_key", "date"], keep="last")


def resolve_daily_duplicates(d: pd.DataFrame, h: pd.DataFrame):
    """A daily file can contain two rows for one index and date (seen on 2023-10-04, one of them
    wrong). A duplicate is resolved only by evidence: keep the row whose close the history API
    confirms (exact to 0.011); if none or several do, keep none and log it. Returns (clean, log)."""
    dup = d[d.duplicated(["index_key", "date"], keep=False)]
    if dup.empty:
        return d, pd.DataFrame(columns=["index_key", "date", "close", "decision", "evidence"])
    hh = h.set_index(["index_key", "date"])["close"]
    drop_idx, log = [], []
    for (k, dte), g in dup.groupby(["index_key", "date"]):
        ref = hh.get((k, dte), np.nan)
        match = g[(g.close - ref).abs() <= 0.011] if pd.notna(ref) else g.iloc[0:0]
        keep = match.index[0] if len(match) == 1 else None
        for ix, r in g.iterrows():
            if ix == keep:
                log.append((k, dte, r.close, "KEPT", f"matches history close {ref}"))
            else:
                drop_idx.append(ix)
                why = f"history close {ref} differs" if keep is not None else (
                    "no history value to decide" if pd.isna(ref) else "several rows match history")
                log.append((k, dte, r.close, "DROPPED", why))
    clean = d.drop(index=drop_idx)
    return clean, pd.DataFrame(log, columns=["index_key", "date", "close", "decision", "evidence"])


def build(out_dir: Path | None = None) -> dict:
    out_dir = out_dir or paths.BUILD / "indices"
    out_dir.mkdir(parents=True, exist_ok=True)
    d, h = daily_table(), history_table()
    keep = set(pd.read_csv(paths.CURATED / "index_universe.csv").index_key)       # only the verified equity indices
    d, h = d[d.index_key.isin(keep)], h[h.index_key.isin(keep)]
    d, log = resolve_daily_duplicates(d, h)
    log.sort_values(["index_key", "date", "close"], kind="mergesort").to_csv(out_dir / "daily_duplicate_resolution.csv", index=False)
    for name, t in (("daily", d), ("history", h)):
        t = t.sort_values(["index_key", "date"], kind="mergesort").reset_index(drop=True)
        t.to_parquet(out_dir / f"index_{name}.parquet", index=False, compression="zstd", compression_level=9)
    return {"daily_rows": len(d), "history_rows": len(h),
            "indices_daily": d["index_key"].nunique() if len(d) else 0,
            "indices_history": h["index_key"].nunique() if len(h) else 0,
            "duplicate_rows_dropped": int((log.decision == "DROPPED").sum()) if len(log) else 0}


def values(index: str | None = None) -> pd.DataFrame:
    """One row per (index, date). The daily-file row is primary where it exists, else the history
    API row. Where both sources cover a date and their closes differ by more than 0.011, the row
    carries conflict=True and alt_close = the other source's close; nothing is hidden or averaged.
    tri / ntr come from the history API (the daily file has none)."""
    d = pd.read_parquet(paths.BUILD / "indices" / "index_daily.parquet")
    h = pd.read_parquet(paths.BUILD / "indices" / "index_history.parquet")
    if index:
        k = name_map().get(key(index), key(index))
        d, h = d[d.index_key == k], h[h.index_key == k]
    hi = h.set_index(["index_key", "date"])
    di = d.set_index(["index_key", "date"])
    extra = h[~hi.index.isin(di.index)]
    t = pd.concat([d, extra], ignore_index=True).set_index(["index_key", "date"])
    both = t.index.isin(hi.index) & (t["src"] == "daily").values
    t["alt_close"] = np.nan
    t.loc[both, "alt_close"] = hi["close"].reindex(t.index[both]).values
    t.loc[t["src"] == "daily", ["tri", "ntr"]] = hi[["tri", "ntr"]].reindex(t.index[t["src"] == "daily"]).values
    t["conflict"] = (t["close"] - t["alt_close"]).abs() > 0.011
    return t.reset_index().sort_values(["index_key", "date"], kind="mergesort").reset_index(drop=True)
