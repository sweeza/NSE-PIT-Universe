"""
Vectorized Index Tensor Builder for Canonical NSE Indices (2012 to Present).
Parses all 3,620 cached daily index bhavcopies and generates 7 aligned index matrices:
- index_open.parquet
- index_high.parquet
- index_low.parquet
- index_close.parquet
- index_volume.parquet
- index_pe.parquet
- index_pb.parquet
- index_divyield.parquet
"""

import time
import re
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import pandas as pd
import numpy as np
import config

INDEX_CACHE_DIR = config.DATA_DIR / "index_cache"
INDEX_TENSOR_DIR = config.DATA_DIR / "index_tensors"
INDEX_TENSOR_DIR.mkdir(parents=True, exist_ok=True)

# Canonical mapping for historical name changes (e.g. S&P CNX Nifty / CNX Nifty -> Nifty 50)
CANONICAL_NAME_MAP = {
    "S&P CNX NIFTY": "NIFTY 50",
    "CNX NIFTY": "NIFTY 50",
    "NIFTY 50": "NIFTY 50",

    "CNX NIFTY JUNIOR": "NIFTY NEXT 50",
    "NIFTY NEXT 50": "NIFTY NEXT 50",

    "CNX 100": "NIFTY 100",
    "NIFTY 100": "NIFTY 100",

    "CNX 200": "NIFTY 200",
    "NIFTY 200": "NIFTY 200",

    "S&P CNX 500": "NIFTY 500",
    "CNX 500": "NIFTY 500",
    "NIFTY 500": "NIFTY 500",

    "CNX MIDCAP": "NIFTY MIDCAP 100",
    "NIFTY MIDCAP 100": "NIFTY MIDCAP 100",

    "CNX SMALLCAP": "NIFTY SMALLCAP 100",
    "NIFTY SMALLCAP 100": "NIFTY SMALLCAP 100",

    "CNX BANK": "NIFTY BANK",
    "NIFTY BANK": "NIFTY BANK",

    "CNX IT": "NIFTY IT",
    "NIFTY IT": "NIFTY IT",

    "CNX AUTO": "NIFTY AUTO",
    "NIFTY AUTO": "NIFTY AUTO",

    "CNX PHARMA": "NIFTY PHARMA",
    "NIFTY PHARMA": "NIFTY PHARMA",

    "CNX FMCG": "NIFTY FMCG",
    "NIFTY FMCG": "NIFTY FMCG",

    "CNX METAL": "NIFTY METAL",
    "NIFTY METAL": "NIFTY METAL",

    "CNX ENERGY": "NIFTY ENERGY",
    "NIFTY ENERGY": "NIFTY ENERGY",

    "CNX FINANCE": "NIFTY FINANCIAL SERVICES",
    "NIFTY FINANCIAL SERVICES": "NIFTY FINANCIAL SERVICES",

    "CNX REALTY": "NIFTY REALTY",
    "NIFTY REALTY": "NIFTY REALTY",

    "CNX MEDIA": "NIFTY MEDIA",
    "NIFTY MEDIA": "NIFTY MEDIA",

    "CNX INFRASTRUCTURE": "NIFTY INFRASTRUCTURE",
    "NIFTY INFRASTRUCTURE": "NIFTY INFRASTRUCTURE",

    "CNX COMMODITIES": "NIFTY COMMODITIES",
    "NIFTY COMMODITIES": "NIFTY COMMODITIES",

    "CNX CONSUMPTION": "NIFTY INDIA CONSUMPTION",
    "NIFTY INDIA CONSUMPTION": "NIFTY INDIA CONSUMPTION",

    "CNX PSE": "NIFTY PSE",
    "NIFTY PSE": "NIFTY PSE",

    "CNX PSU BANK": "NIFTY PSU BANK",
    "NIFTY PSU BANK": "NIFTY PSU BANK",

    "CNX MNC": "NIFTY MNC",
    "NIFTY MNC": "NIFTY MNC",

    "CNX SERVICE SECTOR": "NIFTY SERVICES SECTOR",
    "NIFTY SERVICES SECTOR": "NIFTY SERVICES SECTOR",

    "INDIA VIX": "INDIA VIX",
}


def normalize_index_name(raw_name: str) -> str:
    cleaned = raw_name.strip().upper()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned in CANONICAL_NAME_MAP:
        return CANONICAL_NAME_MAP[cleaned]
    # Replace leading CNX with NIFTY
    if cleaned.startswith("CNX "):
        candidate = "NIFTY " + cleaned[4:]
        return CANONICAL_NAME_MAP.get(candidate, candidate)
    return cleaned


def parse_single_file(f_path: Path):
    try:
        date_str = f_path.stem.replace("index_", "")
        dt = pd.to_datetime(date_str)
        df = pd.read_csv(f_path)
        if df.empty or "Index Name" not in df.columns:
            return None

        # Clean column names
        df.columns = [c.strip() for c in df.columns]
        df["canonical_name"] = df["Index Name"].astype(str).apply(normalize_index_name)

        # Convert numeric fields
        num_cols = {
            "Open Index Value": "open",
            "High Index Value": "high",
            "Low Index Value": "low",
            "Closing Index Value": "close",
            "Volume": "volume",
            "P/E": "pe",
            "P/B": "pb",
            "Div Yield": "div_yield",
        }

        records = {}
        for orig, target in num_cols.items():
            if orig in df.columns:
                s = pd.to_numeric(df[orig].astype(str).str.replace(",", "").str.strip(), errors="coerce")
                records[target] = pd.Series(s.values, index=df["canonical_name"].values)

        return dt, records
    except Exception:
        return None


def build_index_tensors():
    t0 = time.time()
    print("=" * 70)
    print("BUILDING VECTORIZED INDEX TENSORS FROM OFFICIAL NSE ARCHIVES")
    print("=" * 70)

    files = sorted(list(INDEX_CACHE_DIR.glob("*.csv")))
    print(f"Total cached index files: {len(files):,}")

    results = []
    with ThreadPoolExecutor(max_workers=16) as executor:
        for res in executor.map(parse_single_file, files):
            if res is not None:
                results.append(res)

    results.sort(key=lambda x: x[0])
    dates = [r[0] for r in results]
    print(f"Successfully parsed sessions: {len(dates):,} ({dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')})")

    # Collect all unique canonical index names
    all_indices = set()
    for _, rec in results:
        if "close" in rec:
            all_indices.update(rec["close"].dropna().index)

    index_cols = sorted(list(all_indices))
    print(f"Total canonical index instruments: {len(index_cols):,}")

    # Build 8 matrices
    fields = ["open", "high", "low", "close", "volume", "pe", "pb", "div_yield"]
    for field in fields:
        matrix_data = []
        for dt, rec in results:
            if field in rec:
                row_series = rec[field]
                # If duplicates in canonical_name (rare), take the first
                row_series = row_series[~row_series.index.duplicated(keep="first")]
                row_vals = row_series.reindex(index_cols).values
            else:
                row_vals = np.full(len(index_cols), np.nan)
            matrix_data.append(row_vals)

        df_field = pd.DataFrame(matrix_data, index=pd.DatetimeIndex(dates), columns=index_cols)
        # Store as float32 to conserve disk space, volume as float64
        if field == "volume":
            df_field = df_field.astype(np.float64)
        else:
            df_field = df_field.astype(np.float32)

        out_path = INDEX_TENSOR_DIR / f"{field}.parquet"
        df_field.to_parquet(out_path, compression="snappy")
        print(f"  Saved {out_path.name:20s}: {df_field.shape[0]} dates x {df_field.shape[1]} indices ({out_path.stat().st_size / 1024:.1f} KB)")

    print(f"\nAll index tensors successfully built in {time.time()-t0:.2f}s!")


if __name__ == "__main__":
    build_index_tensors()
