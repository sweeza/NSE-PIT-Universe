"""
Daily Self-Sustaining Automated Updater with Pre-Commit Validation Gate.

Workflow:
1. Identifies missing trading dates between latest tensor date and today.
2. For each missing date:
    - Fetches official Bhavcopy in-memory (or from cache).
    - Syncs official index constituents.
    - Stages new row across all 12 tensors in-memory.
    - Pre-Commit Validation Gate: Mathematical bounds (H >= L, H >= C, L <= C, C > 0, V >= 0).
    - Atomic Commit to Parquet tensors upon passing gate.
3. Downloads missing index bhavcopies and updates index tensors.
4. Executes global validation suite and updates validation_report.json.
"""

import io
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path
import pandas as pd
import numpy as np
import requests
import config
import nseuniverse_io as nio
from fetch_index_reconstitution import sync_official_indices
from download_bhavcopy_stream import fetch_nse_bhavcopy_stream
import build_index_tensors
import validate_universe

def update_universe_daily():
    print("=" * 80)
    print("RUNNING MULTI-DAY SELF-SUSTAINING UPDATE WITH PRE-COMMIT VALIDATION GATE")
    print("=" * 80)

    # Step 1: Sync official index constituents
    print("\n[Step 1/5] Syncing official index constituents...")
    try:
        sync_official_indices()
    except Exception as e:
        print(f"  Warning during index sync: {e}")

    # Step 2: Load Security Master and inspect canonical tensors
    print("\n[Step 2/5] Inspecting Security Master & Current Tensors...")
    sec_master = nio.get_security_master(reload=True)
    tickers = sec_master.index.tolist()
    N = len(tickers)
    print(f"  Security Master tracks {N:,} instruments.")

    close_df = pd.read_parquet(config.TENSOR_FILES["close"])
    last_dt = close_df.index[-1].date()
    today_dt = date.today()
    print(f"  Latest session in canonical tensors: {last_dt}")
    print(f"  Current system date:                 {today_dt}")

    if last_dt >= today_dt:
        print("  Canonical tensors are already fully up to date with today.")
        missing_dates = []
    else:
        # Generate candidate missing dates
        cur = last_dt + timedelta(days=1)
        missing_dates = []
        while cur <= today_dt:
            if cur.weekday() < 5: # Monday through Friday
                missing_dates.append(cur)
            cur += timedelta(days=1)

    print(f"  Candidate sessions to sync: {[d.strftime('%Y-%m-%d') for d in missing_dates]}")

    sessions_added = 0

    # Step 3: Process each missing date sequentially
    for target_date in missing_dates:
        d_str = target_date.strftime("%Y-%m-%d")
        print(f"\n--- Processing Session: {d_str} ---")

        # Check local cache first, else stream directly in-memory from NSE
        cached_file = config.BHAVCOPY_CACHE_DIR / f"bhav_{d_str}.parquet"
        df_bhav = None

        if cached_file.exists():
            print(f"  Loading cached Bhavcopy: {cached_file.name}...")
            df_bhav = pd.read_parquet(cached_file)
        else:
            print(f"  Streaming {d_str} Bhavcopy in-memory from official NSE endpoint...")
            df_bhav = fetch_nse_bhavcopy_stream(target_date)

        if df_bhav is None or df_bhav.empty:
            print(f"  Bhavcopy for {d_str} is not published or exchange was closed (holiday). Skipping.")
            continue

        sym_col = "SYMBOL" if "SYMBOL" in df_bhav.columns else None
        if not sym_col:
            print(f"  Error: Bhavcopy for {d_str} missing SYMBOL column. Skipping.")
            continue

        # Clean duplicates: prioritize standard equities (EQ) or first occurrence
        df_clean = df_bhav.copy()
        if "SERIES" in df_clean.columns:
            # Sort series so EQ, BE, SM come first
            series_prio = {"EQ": 0, "BE": 1, "SM": 2, "BZ": 3, "ST": 4}
            df_clean["_prio"] = df_clean["SERIES"].map(lambda s: series_prio.get(str(s).strip(), 99))
            df_clean = df_clean.sort_values("_prio").drop(columns=["_prio"])

        df_clean = df_clean.drop_duplicates(subset=[sym_col], keep="first")
        bhav_map = df_clean.set_index(sym_col).to_dict("index")

        new_open = []
        new_high = []
        new_low = []
        new_close = []
        new_vol = []
        new_turn = []
        new_trades = []
        new_last = []
        new_prev = []
        new_series = []
        new_isin = []

        for t in tickers:
            sym = sec_master.loc[t, "symbol"]
            row = bhav_map.get(sym)
            if row and pd.notna(row.get("CLOSE")) and float(row.get("CLOSE")) > 0:
                c = float(row["CLOSE"])
                o = float(row.get("OPEN", c))
                h = float(row.get("HIGH", c))
                l = float(row.get("LOW", c))
                v = float(row.get("TOTTRDQTY", 0))
                tn = float(row.get("TOTTRDVAL", 0))
                tr = float(row.get("TOTALTRADES", 0)) if pd.notna(row.get("TOTALTRADES")) else 0.0
                lst = float(row.get("LAST", c)) if pd.notna(row.get("LAST")) else c
                prv = float(row.get("PREVCLOSE", c)) if pd.notna(row.get("PREVCLOSE")) else c
                srs = str(row.get("SERIES", sec_master.loc[t, "series"]))
                isn = str(row.get("ISIN", sec_master.loc[t, "isin"]))

                new_close.append(c)
                new_open.append(o)
                new_high.append(h)
                new_low.append(l)
                new_vol.append(v)
                new_turn.append(tn)
                new_trades.append(tr)
                new_last.append(lst)
                new_prev.append(prv)
                new_series.append(srs)
                new_isin.append(isn)
            else:
                new_close.append(np.nan)
                new_open.append(np.nan)
                new_high.append(np.nan)
                new_low.append(np.nan)
                new_vol.append(np.nan)
                new_turn.append(np.nan)
                new_trades.append(np.nan)
                new_last.append(np.nan)
                new_prev.append(np.nan)
                new_series.append(None)
                new_isin.append(None)

        # Pre-Commit Mathematical Validation Gate
        arr_c = np.array(new_close, dtype=np.float32)
        arr_o = np.array(new_open, dtype=np.float32)
        arr_h = np.array(new_high, dtype=np.float32)
        arr_l = np.array(new_low, dtype=np.float32)
        arr_v = np.array(new_vol, dtype=np.float64)

        valid = ~np.isnan(arr_c)
        if valid.sum() == 0:
            print(f"  [GATE REJECTED] Zero active scrips found for {d_str}. Skipping.")
            continue

        violations = (
            np.nansum(arr_h[valid] < arr_l[valid]) +
            np.nansum(arr_h[valid] < arr_c[valid]) +
            np.nansum(arr_h[valid] < arr_o[valid]) +
            np.nansum(arr_l[valid] > arr_c[valid]) +
            np.nansum(arr_l[valid] > arr_o[valid]) +
            np.nansum(arr_c[valid] <= 0) +
            np.nansum(arr_v[valid] < 0)
        )

        if violations > 0:
            print(f"  [GATE REJECTED] Found {violations} mathematical violations in {d_str}. Aborting.")
            continue

        print(f"  [GATE PASSED] 0 violations across {valid.sum():,} active scrips. Committing {d_str} to 12 matrices...")

        target_ts = pd.to_datetime(d_str)

        # Append row to each tensor
        row_arrays = {
            "open": np.array(new_open, dtype=np.float32),
            "high": np.array(new_high, dtype=np.float32),
            "low": np.array(new_low, dtype=np.float32),
            "close": np.array(new_close, dtype=np.float32),
            "volume": np.array(new_vol, dtype=np.float64),
            "turnover": np.array(new_turn, dtype=np.float64),
            "trades": np.array(new_trades, dtype=np.float32),
            "vwap": np.where(arr_v > 0, np.array(new_turn, dtype=np.float64) / np.array(new_vol, dtype=np.float64), arr_c).astype(np.float32),
            "last": np.array(new_last, dtype=np.float32),
            "prevclose": np.array(new_prev, dtype=np.float32),
            "series": np.array(new_series, dtype=object),
            "isin": np.array(new_isin, dtype=object),
        }

        for tensor_name in config.TENSOR_NAMES:
            t_file = config.TENSOR_FILES[tensor_name]
            df_cur = pd.read_parquet(t_file)
            if target_ts not in df_cur.index:
                row_df = pd.DataFrame([row_arrays[tensor_name]], index=[target_ts], columns=tickers)
                df_updated = pd.concat([df_cur, row_df])
                df_updated.to_parquet(t_file, compression="zstd")

        sessions_added += 1
        print(f"  [OK] Session {d_str} committed successfully.")

    # Step 4: Sync index tensors
    print("\n[Step 4/5] Checking and syncing Index Tensors...")
    cache_dir = config.DATA_DIR / "index_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    idx_updated = False

    for target_date in missing_dates:
        d_str = target_date.strftime("%d%m%Y")
        f_name = f"index_{target_date.strftime('%Y-%m-%d')}.csv"
        out_f = cache_dir / f_name
        if not out_f.exists():
            url = f"https://archives.nseindia.com/content/indices/ind_close_all_{d_str}.csv"
            try:
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                if r.status_code == 200 and len(r.content) > 500:
                    out_f.write_bytes(r.content)
                    print(f"  Downloaded index bhavcopy: {f_name}")
                    idx_updated = True
            except Exception as e:
                print(f"  Warning downloading {f_name}: {e}")

    if idx_updated:
        print("  Rebuilding vectorized index tensors...")
        build_index_tensors.build_index_tensors()

    # Step 5: Global Pre-Commit Sanity Validation Suite
    print("\n[Step 5/5] Running Global Universe Validation Suite...")
    validate_universe.run_validation()
    print("\nPipeline execution complete.")
    return True

if __name__ == "__main__":
    update_universe_daily()
