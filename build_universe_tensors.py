"""
High-Performance Vectorized Tensor Builder for Canonical NSE Universe.
Uses PyArrow columnar projection and multi-threaded batching.
Reduces processing time from ~50 minutes to under 2 minutes.
"""

import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import numpy as np
import pyarrow.parquet as pq
import config

def process_file_batch(file_batch):
    """Reads a chunk of files using columnar projection and returns extracted records."""
    results = []
    cols_to_read = ["SYMBOL", "OPEN", "HIGH", "LOW", "CLOSE", "LAST", "PREVCLOSE", "TOTTRDQTY", "TOTTRDVAL", "TOTALTRADES", "SERIES", "ISIN"]
    
    for f, d_idx in file_batch:
        try:
            # Check schema of file
            schema = pq.read_schema(f)
            avail_cols = [c for c in cols_to_read if c in schema.names]
            tbl = pq.read_table(f, columns=avail_cols)
            df = tbl.to_pandas()
            if "SYMBOL" in df.columns:
                results.append((d_idx, df))
        except Exception:
            continue
    return results

def build_universe_tensors_fast():
    t_start = time.time()
    print("=" * 70)
    print("BUILDING 12 CANONICAL EXTENDED TENSORS (HIGH-PERFORMANCE ENGINE)")
    print("=" * 70)

    config.TENSOR_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load Master Security Master
    sec_master = pd.read_parquet(config.SECURITY_MASTER_FILE)
    tickers = sec_master.index.tolist()
    symbol_to_ticker = {sec_master.loc[t, "symbol"]: t for t in tickers}
    N = len(tickers)
    print(f"  Security Master: {N:,} scrips")

    # 2. Extract Trading Dates
    bhav_files = sorted(list(config.BHAVCOPY_CACHE_DIR.glob("*.parquet")))
    date_file_pairs = []
    for f in bhav_files:
        name = f.stem.replace("bhav_", "")
        try:
            d = pd.to_datetime(name)
            if d >= pd.to_datetime("2004-01-01") and d <= pd.to_datetime("2026-10-31"):
                date_file_pairs.append((d, f))
        except Exception:
            continue

    date_file_pairs = sorted(date_file_pairs, key=lambda x: x[0])
    dates = [p[0] for p in date_file_pairs]
    T = len(dates)
    print(f"  Sessions: {T:,} dates ({dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')})")

    # Pre-map ticker index
    ticker_to_idx = {t: i for i, t in enumerate(tickers)}
    symbol_to_nidx = {sec_master.loc[t, "symbol"]: i for i, t in enumerate(tickers)}

    print("  Allocating high-speed contiguous buffers...")
    arr_open = np.full((T, N), np.nan, dtype=np.float32)
    arr_high = np.full((T, N), np.nan, dtype=np.float32)
    arr_low = np.full((T, N), np.nan, dtype=np.float32)
    arr_close = np.full((T, N), np.nan, dtype=np.float32)
    arr_volume = np.full((T, N), np.nan, dtype=np.float64)
    arr_turnover = np.full((T, N), np.nan, dtype=np.float64)
    arr_trades = np.full((T, N), np.nan, dtype=np.float32)
    arr_last = np.full((T, N), np.nan, dtype=np.float32)
    arr_prevclose = np.full((T, N), np.nan, dtype=np.float32)
    arr_series = np.full((T, N), None, dtype=object)
    arr_isin = np.full((T, N), None, dtype=object)

    print("  Reading Bhavcopies in parallel with multi-threaded PyArrow...")
    # Batch files into chunks of 100
    file_batches = []
    chunk_size = 100
    all_pairs_with_idx = [(p[1], idx) for idx, p in enumerate(date_file_pairs)]
    for i in range(0, len(all_pairs_with_idx), chunk_size):
        file_batches.append(all_pairs_with_idx[i:i + chunk_size])

    with ThreadPoolExecutor(max_workers=8) as executor:
        for batch_res in executor.map(process_file_batch, file_batches):
            for t_idx, df in batch_res:
                syms = df["SYMBOL"].astype(str).str.strip().values
                closes = df["CLOSE"].values if "CLOSE" in df.columns else None
                opens = df["OPEN"].values if "OPEN" in df.columns else closes
                highs = df["HIGH"].values if "HIGH" in df.columns else closes
                lows = df["LOW"].values if "LOW" in df.columns else closes
                vols = df["TOTTRDQTY"].values if "TOTTRDQTY" in df.columns else None
                turns = df["TOTTRDVAL"].values if "TOTTRDVAL" in df.columns else None
                trades = df["TOTALTRADES"].values if "TOTALTRADES" in df.columns else None
                lasts = df["LAST"].values if "LAST" in df.columns else closes
                prevs = df["PREVCLOSE"].values if "PREVCLOSE" in df.columns else closes
                series = df["SERIES"].values if "SERIES" in df.columns else None
                isins = df["ISIN"].values if "ISIN" in df.columns else None

                for k, s in enumerate(syms):
                    n_idx = symbol_to_nidx.get(s)
                    if n_idx is None:
                        continue
                    c = closes[k] if closes is not None else np.nan
                    if pd.notna(c) and c > 0:
                        arr_close[t_idx, n_idx] = c
                        arr_open[t_idx, n_idx] = opens[k] if opens is not None and pd.notna(opens[k]) else c
                        arr_high[t_idx, n_idx] = highs[k] if highs is not None and pd.notna(highs[k]) else c
                        arr_low[t_idx, n_idx] = lows[k] if lows is not None and pd.notna(lows[k]) else c
                        if vols is not None and pd.notna(vols[k]):
                            arr_volume[t_idx, n_idx] = vols[k]
                        if turns is not None and pd.notna(turns[k]):
                            arr_turnover[t_idx, n_idx] = turns[k]
                        if trades is not None and pd.notna(trades[k]):
                            arr_trades[t_idx, n_idx] = trades[k]
                        if lasts is not None and pd.notna(lasts[k]):
                            arr_last[t_idx, n_idx] = lasts[k]
                        if prevs is not None and pd.notna(prevs[k]):
                            arr_prevclose[t_idx, n_idx] = prevs[k]
                        if series is not None and pd.notna(series[k]):
                            arr_series[t_idx, n_idx] = str(series[k]).strip()
                        if isins is not None and pd.notna(isins[k]):
                            arr_isin[t_idx, n_idx] = str(isins[k]).strip()

    # VWAP Calculation
    print("  Vectorized VWAP calculation...")
    with np.errstate(divide='ignore', invalid='ignore'):
        arr_vwap = np.where(arr_volume > 0, (arr_turnover / arr_volume).astype(np.float32), arr_close)
        arr_vwap = np.clip(arr_vwap, arr_low, arr_high)

    print(f"  Bhavcopy ingestion completed in {time.time() - t_start:.1f}s. Writing 12 Parquets...")

    matrices = {
        "open": (arr_open, np.float32),
        "high": (arr_high, np.float32),
        "low": (arr_low, np.float32),
        "close": (arr_close, np.float32),
        "volume": (arr_volume, np.float64),
        "turnover": (arr_turnover, np.float64),
        "trades": (arr_trades, np.float32),
        "vwap": (arr_vwap, np.float32),
        "last": (arr_last, np.float32),
        "prevclose": (arr_prevclose, np.float32),
        "series": (arr_series, object),
        "isin": (arr_isin, object),
    }

    for name, (arr, dt) in matrices.items():
        out_path = config.TENSOR_FILES[name]
        df_out = pd.DataFrame(arr, index=dates, columns=tickers)
        if dt != object:
            df_out = df_out.astype(dt)
        df_out.to_parquet(out_path)
        print(f"    [OK] Saved {out_path.name} ({out_path.stat().st_size / (1024*1024):.1f} MB)")

    print("=" * 70)
    print(f"ALL 12 CANONICAL TENSORS BUILT IN {time.time() - t_start:.1f}s")
    print("=" * 70)

if __name__ == "__main__":
    build_universe_tensors_fast()
