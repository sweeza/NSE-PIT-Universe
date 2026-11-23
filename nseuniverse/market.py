"""Market-activity files: delivery quantity, price bands and their changes, ASM/GSM remarks, F&O ban lists.

Raw files live in data/raw/market/ (fetch.py). Parsers return what the file says; nothing is filled.
Every row is attached to a security (sec_id) through the bhavcopy row of the same day, symbol and series.

Tables written to data/build/market/:
  delivery.parquet      date, symbol, series, traded_qty, deliv_qty, deliv_pct, sec_id   (NSE MTO file, 2005-)
  band_changes.parquet  date, symbol, series, band_from, band_to, sec_id                 (daily change file, 2010-)
  sec_list.parquet      date, symbol, series, band, remarks, sec_id                      (security list, 2020-)
  fo_ban.parquet        date, symbol, sec_id                                             (securities in the F&O ban period)
  deals.parquet         date, symbol, client_name, buy_sell, quantity, price, remarks, kind, sec_id
  impact_cost.parquet   date, symbol, series, isin, category, impact_cost_pct, sec_id    (monthly NCL file, 2019-)
  shares.parquet        date, symbol, series, isin, par_val, shares_outstanding, sec_id  (NSE MII security master, 2024-02-05-;
                        only rows attached to a security that traded that day)
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


def parse_fo_bhav(raw: bytes, date: pd.Timestamp) -> pd.DataFrame:
    """Derivatives bhavcopy (zip, legacy or UDiFF) -> one row per stock with contracts that day:
    date, symbol, fut (has stock futures), opt (has stock options). Index contracts are ignored."""
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(raw))
    name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
    df = pd.read_csv(z.open(name), dtype=str, encoding="latin-1", index_col=False).fillna("")
    df.columns = [c.strip() for c in df.columns]
    if {"INSTRUMENT", "SYMBOL"} <= set(df.columns):
        kind, sym = df["INSTRUMENT"].str.strip(), df["SYMBOL"].str.strip()
        fut, opt = kind == "FUTSTK", kind == "OPTSTK"
    elif {"FinInstrmTp", "TckrSymb"} <= set(df.columns):
        kind, sym = df["FinInstrmTp"].str.strip(), df["TckrSymb"].str.strip()
        fut, opt = kind == "STF", kind == "STO"
    else:
        raise UnknownLayout(f"columns {list(df.columns)}")
    x = pd.DataFrame({"symbol": sym, "fut": fut, "opt": opt})
    x = x[x.fut | x.opt].groupby("symbol", as_index=False).agg(fut=("fut", "max"), opt=("opt", "max"))
    x.insert(0, "date", date)
    return x


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


def _read_fo() -> pd.DataFrame:
    frames = []
    root = paths.MARKET_RAW / "fobhav"
    for f in sorted(root.rglob("*.zip")) if root.exists() else []:
        m = re.search(r"_(\d{8})_F_", f.name)
        d = pd.Timestamp(m.group(1)) if m else pd.Timestamp(dt.datetime.strptime(f.name[2:11], "%d%b%Y"))
        try:
            x = parse_fo_bhav(f.read_bytes(), d)
        except Exception:                 # a damaged zip or an unknown layout is listed, not guessed
            SKIPPED.append(f.name)
            continue
        if len(x):
            frames.append(x)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)       # 2024-07-05 exists in both formats: one row per date and symbol
    return out.groupby(["date", "symbol"], as_index=False).agg(fut=("fut", "max"), opt=("opt", "max"))


def _parse_deal_dates(s: pd.Series) -> pd.Series:
    cleaned = s.str.strip()
    d = pd.to_datetime(cleaned, format="%d-%b-%Y", errors="coerce")
    miss = d.isna() & (cleaned != "")
    if miss.any():
        d = d.fillna(pd.to_datetime(cleaned[miss], format="mixed", dayfirst=True, errors="coerce"))
    return d


def parse_deals(raw: bytes, kind: str) -> pd.DataFrame:
    """Bulk deals, block deals, or short selling CSV (archive or daily snapshot). Raises UnknownLayout on unrecognised headers."""
    if kind not in ("bulk", "block", "short"):
        raise ValueError(f"unknown deals kind: {kind!r}")
    text = raw.decode("utf-8-sig", errors="replace")
    df = pd.read_csv(io.StringIO(text), dtype=str, index_col=False).fillna("")
    df.columns = [re.sub(r"\s+", " ", c.strip().lower()).replace(" / ", "/") for c in df.columns]
    cols = set(df.columns)
    if kind in ("bulk", "block") and {"date", "symbol", "client name", "buy/sell", "quantity traded", "trade price/wght. avg. price"} <= cols:
        out = pd.DataFrame({
            "date": _parse_deal_dates(df["date"]),
            "symbol": df["symbol"].str.strip(),
            "client_name": df["client name"].str.strip(),
            "buy_sell": df["buy/sell"].str.strip().str.upper(),
            "quantity": pd.to_numeric(df["quantity traded"].str.replace(",", "", regex=False).str.strip(), errors="coerce"),
            "price": pd.to_numeric(df["trade price/wght. avg. price"].str.replace(",", "", regex=False).str.strip(), errors="coerce"),
            "remarks": df["remarks"].str.strip().replace("-", "") if "remarks" in cols else "",
            "kind": kind,
        })
    elif kind == "short" and {"date", "symbol", "quantity"} <= cols:
        out = pd.DataFrame({
            "date": _parse_deal_dates(df["date"]),
            "symbol": df["symbol"].str.strip(),
            "client_name": "",
            "buy_sell": "",
            "quantity": pd.to_numeric(df["quantity"].str.replace(",", "", regex=False).str.strip(), errors="coerce"),
            "price": np.nan,
            "remarks": "",
            "kind": kind,
        })
    else:
        raise UnknownLayout(f"deals ({kind}) columns {list(df.columns)}")
    return out[(out.symbol != "") & out.date.notna()].reset_index(drop=True)


def _read_deals() -> pd.DataFrame:
    frames = []
    root = paths.MARKET_RAW / "deals"
    for f in sorted(root.rglob("*.csv")) if root.exists() else []:
        prefix = f.name.split("_", 1)[0].lower()
        if prefix not in ("bulk", "block", "short"):
            continue
        try:
            d = parse_deals(f.read_bytes(), prefix)
        except UnknownLayout:
            SKIPPED.append(f.name)
            continue
        if len(d):
            frames.append(d)
    if not frames:
        return pd.DataFrame()
    key = ["date", "kind", "symbol", "client_name", "buy_sell", "quantity", "price"]
    parts = []
    for d in frames:
        d = d.copy()
        d["_n"] = d.groupby(key, dropna=False).cumcount()      # the 1st, 2nd ... identical row inside ONE file
        parts.append(d)
    out = pd.concat(parts, ignore_index=True)
    # A row listed in two files (a daily snapshot and a window, or two windows sharing a day) counts once; identical
    # rows inside one file are separate deals and are all kept.
    return out.drop_duplicates(key + ["_n"]).drop(columns="_n").reset_index(drop=True)


def parse_impact_cost(raw: bytes, date: pd.Timestamp) -> pd.DataFrame:
    """Monthly NSE Clearing security category & 6-month rolling mean impact cost (.T01).
    Header: 10,<MMM>,<YYYY>,<count>. Data: 20,<symbol>,<series>,<isin>,<category>,<impact_cost_pct>.
    Raises UnknownLayout if header or data rows do not match the known 6-field layout."""
    lines = [l.strip() for l in raw.decode("latin-1").splitlines() if l.strip()]
    if not lines:
        raise UnknownLayout("empty impact_cost file")
    hdr = lines[0].strip('"').strip().split(",")
    if len(hdr) < 4 or hdr[0] != "10":
        raise UnknownLayout(f"unexpected impact_cost header: {lines[0]!r}")
    rows = []
    for line in lines[1:]:
        clean = line.strip('"').strip()
        p = [x.strip() for x in clean.split(",")]
        if len(p) != 6 or p[0] != "20":
            raise UnknownLayout(f"unexpected impact_cost row: {line!r}")
        rows.append((date, p[1], p[2], p[3], p[4], p[5]))
    df = pd.DataFrame(rows, columns=["date", "symbol", "series", "isin", "category", "impact_cost_pct"])
    df["category"] = pd.to_numeric(df["category"], errors="coerce").astype("Int64")
    df["impact_cost_pct"] = pd.to_numeric(df["impact_cost_pct"], errors="coerce")
    return df[df.symbol != ""].reset_index(drop=True)


MII_COLUMNS = ["TckrSymb", "SctySrs", "ISIN", "ParVal", "IssdCptl"]


def parse_mii(raw: bytes, date: pd.Timestamp) -> pd.DataFrame:
    """NSE MII security master (gzip CSV, one row per security and series). `IssdCptl` is the issued share count;
    `FreeFltCptl` is empty in NSE's file and is not read. Raises UnknownLayout if the expected columns are absent.
    A missing or non-numeric count stays NaN."""
    import gzip
    try:
        body = gzip.decompress(raw)
    except OSError as e:
        raise UnknownLayout(f"not gzip: {e}")
    df = pd.read_csv(io.BytesIO(body), dtype=str, encoding="latin-1", index_col=False, usecols=lambda c: c in MII_COLUMNS)
    if any(c not in df.columns for c in MII_COLUMNS):
        raise UnknownLayout(f"MII columns {list(df.columns)} lack {MII_COLUMNS}")
    out = pd.DataFrame({"date": date, "symbol": df["TckrSymb"].str.strip(), "series": df["SctySrs"].str.strip(),
                        "isin": df["ISIN"].str.strip(), "par_val": pd.to_numeric(df["ParVal"], errors="coerce"),
                        "shares_outstanding": pd.to_numeric(df["IssdCptl"], errors="coerce")})
    return out[out.symbol.notna() & (out.symbol != "")].reset_index(drop=True)


def _read_impact_cost() -> pd.DataFrame:
    frames = []
    root = paths.MARKET_RAW / "impactcost"
    for f in sorted(root.rglob("C_CATG_*.T01")) if root.exists() else []:
        m = re.match(r"C_CATG_([A-Z]{3})(\d{4})\.T01$", f.name, re.IGNORECASE)
        if not m:
            SKIPPED.append(f.name)
            continue
        d = pd.Timestamp(dt.datetime.strptime(m.group(1).upper() + m.group(2), "%b%Y"))
        try:
            x = parse_impact_cost(f.read_bytes(), d)
        except UnknownLayout:
            SKIPPED.append(f.name)
            continue
        if len(x):
            frames.append(x)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _attach_monthly(df: pd.DataFrame, t: pd.DataFrame) -> pd.DataFrame:
    """Attach monthly rows (date = month start) to sec_id using bhavcopy rows in the same calendar month:
    first by (month, symbol, series), then by (month, symbol) when unique, then by (month, isin) if available."""
    if df.empty:
        return df.assign(sec_id=pd.Series([], dtype=object))
    tm = t[["date", "symbol", "series", "sec_id"]].copy()
    tm["month"] = tm["date"].dt.to_period("M").dt.to_timestamp()
    out = df.assign(month=df["date"].dt.to_period("M").dt.to_timestamp())
    k1 = tm.groupby(["month", "symbol", "series"]).sec_id.agg(lambda s: s.iloc[0] if s.nunique() == 1 else np.nan).dropna().reset_index()
    out = out.merge(k1, on=["month", "symbol", "series"], how="left")
    out["sec_id"] = out["sec_id"].astype(object)
    miss = out["sec_id"].isna()
    if miss.any():
        k2 = tm.groupby(["month", "symbol"]).sec_id.agg(lambda s: s.iloc[0] if s.nunique() == 1 else np.nan).dropna().reset_index()
        fill = out.loc[miss, ["month", "symbol"]].merge(k2, on=["month", "symbol"], how="left")["sec_id"].values
        out.loc[miss, "sec_id"] = fill
    miss = out["sec_id"].isna()
    if miss.any() and "isin" in t.columns and "isin" in out.columns:
        ti = t[["date", "isin", "sec_id"]].dropna(subset=["isin"]).copy()
        ti["month"] = ti["date"].dt.to_period("M").dt.to_timestamp()
        k3 = ti.groupby(["month", "isin"]).sec_id.agg(lambda s: s.iloc[0] if s.nunique() == 1 else np.nan).dropna().reset_index()
        fill = out.loc[miss, ["month", "isin"]].merge(k3, on=["month", "isin"], how="left")["sec_id"].values
        out.loc[miss, "sec_id"] = fill
    return out.drop(columns=["month"])


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
        "fo_stocks": _read_fo(),
        "deals": _read_deals(),
        "impact_cost": _read_impact_cost(),
        "shares": _read_dir("mii", "NSE_CM_security_*.csv.gz", parse_mii),
    }
    for name, df in tabs.items():
        n_unattached = 0
        if name == "shares" and len(df):       # the master lists every instrument and auxiliary series (BL, RL, IQ ...):
            keys = t[["date", "symbol", "series"]].drop_duplicates()        # keep the rows that traded that day in that series
            kept = df.merge(keys, on=["date", "symbol", "series"], how="inner")
            n_unattached = len(df) - len(kept)
            df = kept
        df = _attach_monthly(df, t) if name == "impact_cost" else _attach(df, t)
        tabs[name] = df
        if len(df):
            sort_cols = [c for c in ("date", "kind", "symbol", "series", "client_name") if c in df.columns]
            df = df.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)
        df.to_parquet(out / f"{name}.parquet", index=False, compression="zstd", compression_level=9)
        info[name] = {"rows": len(df), "unattached": n_unattached if name == "shares" else (int(df["sec_id"].isna().sum()) if len(df) else 0)}
    info["skipped_unknown_layout"] = sorted(SKIPPED)
    d = tabs["delivery"]
    if len(d):
        v = t[["date", "symbol", "series", "volume"]].drop_duplicates(["date", "symbol", "series"])
        m = d.merge(v, on=["date", "symbol", "series"], how="inner")
        info["delivery_volume_match"] = {"compared": len(m), "equal": int((m.traded_qty == m.volume).sum())}
    return info
