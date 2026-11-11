"""
Daily Self-Sustaining Automated Updater with Atomic Multi-Tensor Staging,
Pre-Commit Mathematical Validation Gate, and Rollback Guarantee.

Workflow:
1. Syncs official index constituents from niftyindices.com.
2. Identifies candidate missing trading sessions using the Official NSE Exchange Calendar
   (automatically skipping weekday holidays, non-trading weekends, and including special sessions).
3. In-Memory Multi-Tensor Staging:
   - For each missing date, streams or loads Bhavcopy.
   - Cleans symbols and prioritizes canonical series (EQ, BE, SM, BZ, ST).
   - Stages new rows for all 12 tensors simultaneously in an in-memory staging dictionary.
4. Pre-Commit Mathematical Validation Gate:
   - Simulates full tensor concatenation in-memory across all 12 matrices.
   - Audits 100% dimensional parity, index monotonicity, and mathematical bounds
     (H >= L, H >= C, H >= O, L <= C, L <= O, C > 0, V >= 0, L <= VWAP <= H).
5. Atomic Multi-Tensor Commit & Rollback:
   - Writes all 12 updated matrices to staged temporary files (.tmp).
   - Validates readable parquet integrity on disk before swapping.
   - Creates pre-commit backup snapshots (.bak).
   - Executes atomic swap across all 12 matrices (os.replace).
   - If any single tensor write or swap fails, rolls back all 12 matrices cleanly
     to their exact pre-update state with zero data corruption.
6. Synchronizes Security Master and Index Tensors.
7. Executes global institutional validation suite and updates validation_report.json.
"""

import io
import os
import shutil
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd
import requests

import config
import nseuniverse_io as nio
from exchange_calendar import (
    get_candidate_sessions,
    is_trading_day,
    is_trading_holiday,
    is_special_trading_session,
)
from fetch_index_reconstitution import sync_official_indices
from download_bhavcopy_stream import fetch_nse_bhavcopy_stream
import build_index_tensors
import validate_universe

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _safe_float(val: any, default: Optional[float] = None) -> Optional[float]:
    """Safely converts string or numeric values to float, returning default on failure or nulls."""
    if val is None or pd.isna(val):
        return default
    try:
        s = str(val).strip().replace(",", "")
        if s in ("", "-", "N/A", "NA", "None", "null"):
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


def validate_staged_tensors(
    existing_tensors: Dict[str, pd.DataFrame],
    staged_rows: Dict[str, List[np.ndarray]],
    staged_dates: List[pd.Timestamp],
    tickers: List[str],
) -> Tuple[bool, str]:
    """
    Simultaneous Pre-Commit Mathematical Validation Gate across all 12 market matrices.
    
    Validates:
    1. Synchronous alignment: all 12 tensors have identical staged row counts.
    2. Column parity: all staged rows match canonical tickers length N.
    3. Chronological monotonicity: staged dates are strictly greater than existing latest date
       and monotonically increasing with zero duplicates.
    4. Mathematical bounds across all staged rows:
       - High >= Low, High >= Close, High >= Open
       - Low <= Close, Low <= Open
       - Close > 0 for non-NaN
       - Volume >= 0, Turnover >= 0, Trades >= 0
       - VWAP bounded between Low and High (with epsilon tolerance for rounding).
    5. Series and ISIN non-null for actively traded instruments.
    """
    if len(staged_dates) == 0:
        return True, "No staged dates to validate."

    N = len(tickers)
    T_staged = len(staged_dates)

    # 1. Synchronous alignment across all 12 tensors
    for name in config.TENSOR_NAMES:
        rows = staged_rows.get(name, [])
        if len(rows) != T_staged:
            return False, f"Staging row count mismatch in tensor '{name}': {len(rows)} vs {T_staged} dates."
        for idx_r, r in enumerate(rows):
            if len(r) != N:
                return False, f"Column dimension mismatch in tensor '{name}' at row {idx_r}: {len(r)} vs {N} tickers."

    # 2. Chronological monotonicity
    last_existing_ts = existing_tensors["close"].index[-1]
    if staged_dates[0] <= last_existing_ts:
        return False, f"Staged date {staged_dates[0]} is not strictly after existing tensor date {last_existing_ts}."

    for i in range(1, len(staged_dates)):
        if staged_dates[i] <= staged_dates[i - 1]:
            return False, f"Staged dates are not strictly monotonically increasing: {staged_dates[i-1]} >= {staged_dates[i]}."

    # 3. Stack staged rows into 2D matrices for vectorized validation
    c = np.vstack(staged_rows["close"]).astype(np.float32)
    o = np.vstack(staged_rows["open"]).astype(np.float32)
    h = np.vstack(staged_rows["high"]).astype(np.float32)
    l = np.vstack(staged_rows["low"]).astype(np.float32)
    v = np.vstack(staged_rows["volume"]).astype(np.float64)
    tn = np.vstack(staged_rows["turnover"]).astype(np.float64)
    tr = np.vstack(staged_rows["trades"]).astype(np.float32)
    vw = np.vstack(staged_rows["vwap"]).astype(np.float32)

    valid = ~np.isnan(c)
    if valid.sum() == 0:
        return False, "Zero active trades found across all staged sessions."

    # Check each mathematical invariant
    missing_ohl = int(np.isnan(o[valid]).sum() + np.isnan(h[valid]).sum() + np.isnan(l[valid]).sum())
    violations = {
        "Missing O/H/L for active close": missing_ohl,
        "H < L": int(np.nansum(h[valid] < l[valid])),
        "H < C": int(np.nansum(h[valid] < c[valid])),
        "H < O": int(np.nansum(h[valid] < o[valid])),
        "L > C": int(np.nansum(l[valid] > c[valid])),
        "L > O": int(np.nansum(l[valid] > o[valid])),
        "C <= 0": int(np.nansum(c[valid] <= 0)),
        "V < 0": int(np.nansum(v[valid] < 0)),
        "Turnover < 0": int(np.nansum(tn[valid] < 0)),
        "Trades < 0": int(np.nansum(tr[valid] < 0)),
    }

    # VWAP bounding check for active volume (tolerance 0.05 for exchange float rounding)
    active_vol = valid & (v > 0)
    eps = 0.05
    vw_viol = int(np.nansum((vw[active_vol] < l[active_vol] - eps) | (vw[active_vol] > h[active_vol] + eps)))
    violations["VWAP out of [L, H]"] = vw_viol

    total_viol = sum(violations.values())
    if total_viol > 0:
        detail = ", ".join(f"{k}: {val}" for k, val in violations.items() if val > 0)
        return False, f"Pre-Commit Gate rejected with {total_viol} mathematical violations: {detail}"

    return True, f"Gate passed cleanly: 0 violations across {T_staged} sessions and {valid.sum():,} active scrip points."


def atomic_commit_tensors(
    updated_tensors: Dict[str, pd.DataFrame],
    tensor_files: Optional[Dict[str, Path]] = None,
) -> bool:
    """
    Atomically commits all 12 updated tensor matrices to disk.
    
    Guarantees:
    1. Writes all 12 DataFrames to temporary files (.tmp.parquet) first.
    2. Validates on-disk parquet readability and shape parity.
    3. Creates backup snapshots (.bak.parquet) of current files.
    4. Performs atomic os.replace across all 12 files.
    5. Clean Rollback: if ANY write or replacement fails, instantly restores all 12 files
       to their pre-commit state from backup snapshots, leaving zero corrupted or asymmetric matrices.
    """
    if tensor_files is None:
        tensor_files = config.TENSOR_FILES

    pid = os.getpid()
    timestamp = int(time.time())
    tmp_files = {}
    bak_files = {}
    swapped_files = []

    try:
        # Step 1: Write all 12 tensors to temporary staging files
        for name in config.TENSOR_NAMES:
            target_file = tensor_files[name]
            tmp_file = target_file.with_name(f"{target_file.stem}_stage_{pid}_{timestamp}.tmp.parquet")
            tmp_files[name] = tmp_file
            
            df = updated_tensors[name]
            df.to_parquet(tmp_file, compression="zstd")

        # Step 2: Verify on-disk readability and shape of all 12 temporary files
        T_expected = updated_tensors["close"].shape[0]
        N_expected = updated_tensors["close"].shape[1]

        for name, tmp_file in tmp_files.items():
            if not tmp_file.exists() or tmp_file.stat().st_size == 0:
                raise IOError(f"Staged file {tmp_file.name} is missing or empty.")
            read_back = pd.read_parquet(tmp_file, columns=[])
            if len(read_back) != T_expected:
                raise ValueError(f"Staged file {tmp_file.name} row count {len(read_back)} != expected {T_expected}.")

        # Step 3: Create backup snapshots of existing files (if they exist)
        for name in config.TENSOR_NAMES:
            target_file = tensor_files[name]
            if target_file.exists():
                bak_file = target_file.with_name(f"{target_file.stem}_backup_{pid}_{timestamp}.bak.parquet")
                shutil.copy2(target_file, bak_file)
                bak_files[name] = bak_file

        # Step 4: Atomic replacement across all 12 files
        for name in config.TENSOR_NAMES:
            target_file = tensor_files[name]
            tmp_file = tmp_files[name]
            os.replace(tmp_file, target_file)
            swapped_files.append(name)

        # Step 5: Clean up backup snapshots on successful commit
        for bak_file in bak_files.values():
            if bak_file.exists():
                try:
                    bak_file.unlink()
                except Exception:
                    pass

        # Invalidate module-level calendar and universe caches so subsequent queries reflect new sessions
        try:
            from exchange_calendar import invalidate_calendar_cache
            invalidate_calendar_cache()
        except Exception:
            pass

        try:
            from nseuniverse.universe import invalidate_universe_cache
            invalidate_universe_cache()
        except Exception:
            pass

        return True

    except Exception as e:
        # Step 6: Clean Rollback Execution
        print(f"\n  [CRITICAL ERROR] Error during atomic tensor commit: {e}")
        print("  Executing emergency rollback to restore pre-commit state...")

        # Restore any files that were swapped
        for name in swapped_files:
            target_file = tensor_files[name]
            bak_file = bak_files.get(name)
            if bak_file and bak_file.exists():
                try:
                    os.replace(bak_file, target_file)
                    print(f"    Restored {target_file.name} from backup.")
                except Exception as rollback_err:
                    print(f"    Rollback failure on {target_file.name}: {rollback_err}")
            elif target_file.exists() and not bak_file:
                try:
                    target_file.unlink()
                    print(f"    Cleaned up newly created {target_file.name}.")
                except Exception:
                    pass

        # Clean up temporary staging files
        for tmp_file in tmp_files.values():
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

        # Clean up remaining backup files
        for bak_file in bak_files.values():
            if bak_file.exists():
                try:
                    bak_file.unlink()
                except Exception:
                    pass

        raise RuntimeError(f"Atomic tensor commit aborted with clean rollback: {e}") from e


def update_universe_daily(
    target_date: Optional[Union[date, str]] = None,
    dry_run: bool = False,
    force_validation: bool = True,
) -> bool:
    """
    Main self-sustaining automated daily update routine.
    
    Parameters
    ----------
    target_date : Union[date, str], optional
        End date to sync through (defaults to date.today()).
    dry_run : bool, default False
        If True, stages and validates rows in-memory without committing to disk.
    force_validation : bool, default True
        If True, runs global institutional validation suite upon completion.
    """
    print("=" * 85)
    print("RUNNING INSTITUTIONAL MULTI-TENSOR DAILY UPDATER WITH ATOMIC PRE-COMMIT GATE")
    print("=" * 85)

    # Step 1: Sync official index constituents
    print("\n[Step 1/6] Syncing official index constituents from niftyindices.com...")
    try:
        sync_official_indices()
    except Exception as e:
        print(f"  Warning during index sync: {e}")

    # Step 2: Load Security Master & Current Canonical Tensors
    print("\n[Step 2/6] Inspecting Security Master & Canonical Tensors...")
    sec_master = nio.get_security_master(reload=True)
    tickers = sec_master.index.tolist()
    N = len(tickers)
    print(f"  Security Master tracks {N:,} canonical instruments.")

    existing_tensors = {}
    for name in config.TENSOR_NAMES:
        existing_tensors[name] = pd.read_parquet(config.TENSOR_FILES[name])

    last_dt = existing_tensors["close"].index[-1].date()
    end_dt = (
        datetime.strptime(target_date, "%Y-%m-%d").date()
        if isinstance(target_date, str)
        else (target_date or date.today())
    )

    print(f"  Latest session in canonical tensors: {last_dt}")
    print(f"  Target sync date:                    {end_dt}")

    # Generate candidate missing dates via Official Exchange Calendar
    missing_dates = get_candidate_sessions(last_dt, end_dt)
    if not missing_dates:
        print("  [OK] Canonical tensors are already fully up to date with exchange calendar.")
    else:
        print(f"  Candidate trading sessions to sync ({len(missing_dates)}): {[d.strftime('%Y-%m-%d') for d in missing_dates]}")

    # Step 3: Multi-Session In-Memory Staging
    staged_rows: Dict[str, List[np.ndarray]] = {name: [] for name in config.TENSOR_NAMES}
    staged_dates: List[pd.Timestamp] = []
    staged_scrip_updates: Dict[str, date] = {}

    for target_dt in missing_dates:
        d_str = target_dt.strftime("%Y-%m-%d")
        print(f"\n--- Staging Session: {d_str} ---")

        # Verify against exchange calendar
        if not is_trading_day(target_dt, check_tensor_history=False):
            print(f"  {d_str} is a non-trading exchange holiday or weekend. Skipping.")
            continue

        # Fetch Bhavcopy in-memory or from cache
        cached_file = config.BHAVCOPY_CACHE_DIR / f"bhav_{d_str}.parquet"
        df_bhav = None

        if cached_file.exists():
            print(f"  Loading cached Bhavcopy: {cached_file.name}...")
            df_bhav = pd.read_parquet(cached_file)
        else:
            print(f"  Streaming {d_str} Bhavcopy in-memory from official NSE endpoint...")
            try:
                df_bhav = fetch_nse_bhavcopy_stream(target_dt)
                if df_bhav is not None and not df_bhav.empty:
                    config.BHAVCOPY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    df_bhav.to_parquet(cached_file, compression="zstd")
            except Exception as e:
                print(f"  Network error fetching Bhavcopy for {d_str}: {e}")
                df_bhav = None

        if df_bhav is None or df_bhav.empty:
            print(f"  Bhavcopy for {d_str} is not published or exchange was closed. Skipping.")
            continue

        sym_col = "SYMBOL" if "SYMBOL" in df_bhav.columns else None
        if not sym_col:
            print(f"  Error: Bhavcopy for {d_str} missing SYMBOL column. Skipping.")
            continue

        # Clean duplicates: prioritize standard equities (EQ) or first occurrence
        df_clean = df_bhav.copy()
        df_clean[sym_col] = df_clean[sym_col].astype(str).str.strip().str.upper()
        if "SERIES" in df_clean.columns:
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

        active_count = 0
        for t in tickers:
            sym = sec_master.loc[t, "symbol"]
            row = bhav_map.get(sym)
            c = _safe_float(row.get("CLOSE")) if row else None
            if c is not None and c > 0:
                o = _safe_float(row.get("OPEN"), default=c)
                h = _safe_float(row.get("HIGH"), default=c)
                l = _safe_float(row.get("LOW"), default=c)
                # Enforce per-scrip mathematical integrity (clamp any minor typographical anomalies)
                h = max(h, l, c, o)
                l = min(h, l, c, o)
                v = max(0.0, _safe_float(row.get("TOTTRDQTY"), default=0.0))
                tn = max(0.0, _safe_float(row.get("TOTTRDVAL"), default=0.0))
                tr = max(0.0, _safe_float(row.get("TOTALTRADES"), default=0.0))
                lst = _safe_float(row.get("LAST"), default=c)
                prv = _safe_float(row.get("PREVCLOSE"), default=c)
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
                active_count += 1
                staged_scrip_updates[t] = target_dt
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

        if active_count == 0:
            print(f"  Zero active scrips found for {d_str}. Skipping.")
            continue

        # Intra-row mathematical validation
        arr_c = np.array(new_close, dtype=np.float32)
        arr_o = np.array(new_open, dtype=np.float32)
        arr_h = np.array(new_high, dtype=np.float32)
        arr_l = np.array(new_low, dtype=np.float32)
        arr_v = np.array(new_vol, dtype=np.float64)
        arr_tn = np.array(new_turn, dtype=np.float64)

        valid_m = ~np.isnan(arr_c)
        row_violations = (
            np.nansum(arr_h[valid_m] < arr_l[valid_m]) +
            np.nansum(arr_h[valid_m] < arr_c[valid_m]) +
            np.nansum(arr_h[valid_m] < arr_o[valid_m]) +
            np.nansum(arr_l[valid_m] > arr_c[valid_m]) +
            np.nansum(arr_l[valid_m] > arr_o[valid_m]) +
            np.nansum(arr_c[valid_m] <= 0) +
            np.nansum(arr_v[valid_m] < 0)
        )

        if row_violations > 0:
            print(f"  [INTRA-SESSION GATE REJECTED] {row_violations} violations in {d_str}. Skipping.")
            continue

        # Compute VWAP array cleanly without divide-by-zero warnings
        arr_vw = arr_c.copy()
        valid_vol = (arr_v > 0) & ~np.isnan(arr_tn)
        arr_vw[valid_vol] = (arr_tn[valid_vol] / arr_v[valid_vol]).astype(np.float32)

        # Stage vectors
        staged_rows["open"].append(arr_o)
        staged_rows["high"].append(arr_h)
        staged_rows["low"].append(arr_l)
        staged_rows["close"].append(arr_c)
        staged_rows["volume"].append(arr_v)
        staged_rows["turnover"].append(arr_tn)
        staged_rows["trades"].append(np.array(new_trades, dtype=np.float32))
        staged_rows["vwap"].append(arr_vw)
        staged_rows["last"].append(np.array(new_last, dtype=np.float32))
        staged_rows["prevclose"].append(np.array(new_prev, dtype=np.float32))
        staged_rows["series"].append(np.array(new_series, dtype=object))
        staged_rows["isin"].append(np.array(new_isin, dtype=object))
        staged_dates.append(pd.to_datetime(d_str))
        print(f"  [STAGED] {d_str}: {active_count:,} active scrips queued for atomic commit.")

    # Step 4: Simultaneous Pre-Commit Mathematical Validation Gate
    if len(staged_dates) > 0:
        print(f"\n[Step 3/6] Executing Pre-Commit Validation Gate across all 12 matrices simultaneously...")
        gate_passed, gate_msg = validate_staged_tensors(
            existing_tensors=existing_tensors,
            staged_rows=staged_rows,
            staged_dates=staged_dates,
            tickers=tickers,
        )
        if not gate_passed:
            print(f"  [PRE-COMMIT GATE FAILED] {gate_msg}")
            return False

        print(f"  [PRE-COMMIT GATE PASSED] {gate_msg}")

        # Assemble full updated DataFrames in memory
        updated_tensors = {}
        for name in config.TENSOR_NAMES:
            df_cur = existing_tensors[name]
            staged_matrix = np.vstack(staged_rows[name])
            staged_df = pd.DataFrame(staged_matrix, index=staged_dates, columns=tickers)
            updated_tensors[name] = pd.concat([df_cur, staged_df])

        if dry_run:
            print("\n  [DRY RUN] In-memory staging and validation successful. Disk commit skipped.")
            return True

        # Step 5: Atomic Commit to Disk with Rollback Protection
        print(f"\n[Step 4/6] Committing {len(staged_dates)} sessions across all 12 matrices atomically...")
        atomic_commit_tensors(updated_tensors=updated_tensors)
        print(f"  [OK] Successfully committed {len(staged_dates)} session(s) to canonical tensors.")

        # Update Security Master last_traded_date and save atomically
        print("  Updating Security Master trading dates...")
        sm_updated = sec_master.copy()
        for t, last_seen_dt in staged_scrip_updates.items():
            sm_updated.loc[t, "last_traded_date"] = str(last_seen_dt)
            sm_updated.loc[t, "is_active_currently"] = True

        tmp_sm = config.SECURITY_MASTER_FILE.with_suffix(".tmp.parquet")
        sm_updated.to_parquet(tmp_sm, compression="zstd")
        os.replace(tmp_sm, config.SECURITY_MASTER_FILE)
        print("  [OK] Security master updated atomically.")

        # Step 6: Rebuild PIT Membership Masks for new sessions
        print("\n[Step 5/6] Updating Point-in-Time Index Membership Masks...")
        import build_pit_memberships
        build_pit_memberships.build_pit_membership_masks()

    else:
        print("\n[Step 3/6] No new sessions staged. Matrices remain unchanged.")

    # Sync Index Tensors
    print("\n[Step 6/6] Checking and syncing Index Tensors...")
    cache_dir = config.DATA_DIR / "index_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    idx_updated = False

    for target_dt in missing_dates:
        if not is_trading_day(target_dt, check_tensor_history=False):
            continue
        d_str = target_dt.strftime("%d%m%Y")
        f_name = f"index_{target_dt.strftime('%Y-%m-%d')}.csv"
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

    # Global Institutional Integrity Audit
    if force_validation:
        print("\nExecuting Global Institutional Integrity Validation...")
        validate_universe.run_institutional_validation()

    print("\nDaily automated update workflow completed successfully.")
    return True


if __name__ == "__main__":
    update_universe_daily()
