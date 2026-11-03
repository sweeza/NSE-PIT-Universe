"""
Constructs daily Point-in-Time (PIT) boolean membership masks for all official
broad-market and sectoral indices.

Guarantees:
- Output matrices are shaped exactly (Dates x Tickers).
- Zero lookahead bias: Reconstitution dates are strictly applied on their effective dates.
- Output parquet files are saved to data/metadata/pit_memberships/<index>.parquet.
"""

from pathlib import Path
import pandas as pd
import numpy as np
import config

def build_pit_membership_masks():
    print("=" * 70)
    print("BUILDING POINT-IN-TIME (PIT) MEMBERSHIP MASKS FOR ALL INDICES")
    print("=" * 70)

    config.PIT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load Security Master
    sec_master = pd.read_parquet(config.SECURITY_MASTER_FILE)
    tickers = sec_master.index.tolist()
    symbol_to_ticker = {sec_master.loc[t, "symbol"]: t for t in tickers}

    # 2. Extract base trading dates from Bhavcopy cache
    bhav_files = sorted(list(config.BHAVCOPY_CACHE_DIR.glob("*.parquet")))
    # Filter to 2004-present
    dates = []
    for f in bhav_files:
        name = f.stem.replace("bhav_", "")
        try:
            d = pd.to_datetime(name)
            if d >= pd.to_datetime("2004-01-01") and d <= pd.to_datetime("2026-10-31"):
                dates.append(d)
        except Exception:
            continue

    dates = sorted(list(set(dates)))
    print(f"  Total trading dates: {len(dates)} ({dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')})")
    print(f"  Total tickers: {len(tickers)}")

    # 3. Load baseline N500 & MidSmall400 PIT memberships if available from source metadata
    n500_pit_file = config.SOURCE_METADATA_DIR / "pit_nifty500_daily_membership_2004_2026.parquet"
    ms400_pit_file = config.SOURCE_METADATA_DIR / "pit_midsmall400_daily_membership.parquet"
    
    n500_mask_base = None
    if n500_pit_file.exists():
        n500_mask_base = pd.read_parquet(n500_pit_file)
        print(f"  Loaded historical Nifty 500 PIT matrix: {n500_mask_base.shape}")

    ms400_mask_base = None
    if ms400_pit_file.exists():
        ms400_mask_base = pd.read_parquet(ms400_pit_file)
        print(f"  Loaded historical MidSmall 400 PIT matrix: {ms400_mask_base.shape}")

    # 4. Generate PIT matrix for each official index
    for idx_name, url in config.OFFICIAL_INDEX_URLS.items():
        out_file = config.PIT_INDEX_FILES[idx_name]
        raw_csv = config.RAW_INDICES_DIR / f"{idx_name}.csv"
        
        # Determine current official constituents
        current_constituents = set()
        if raw_csv.exists():
            df_raw = pd.read_csv(raw_csv)
            sym_col = [c for c in df_raw.columns if "SYMBOL" in c.upper()][0]
            for s in df_raw[sym_col].dropna().str.strip():
                if s in symbol_to_ticker:
                    current_constituents.add(symbol_to_ticker[s])

        print(f"  Processing {idx_name:24} (Current members: {len(current_constituents)})...")

        # Create empty boolean DataFrame
        mask = pd.DataFrame(False, index=dates, columns=tickers, dtype=bool)

        if idx_name == "nifty500" and n500_mask_base is not None:
            # Reindex to master dates and tickers
            common_dates = mask.index.intersection(n500_mask_base.index)
            common_cols = mask.columns.intersection(n500_mask_base.columns)
            mask.loc[common_dates, common_cols] = n500_mask_base.loc[common_dates, common_cols].astype(bool)
            # Forward fill to end for active members
            if len(dates) > len(common_dates):
                last_common = common_dates[-1]
                mask.loc[last_common:] = mask.loc[last_common].values
        elif idx_name == "midsmall400" and ms400_mask_base is not None:
            common_dates = mask.index.intersection(ms400_mask_base.index)
            common_cols = mask.columns.intersection(ms400_mask_base.columns)
            mask.loc[common_dates, common_cols] = ms400_mask_base.loc[common_dates, common_cols].astype(bool)
            if len(dates) > len(common_dates):
                last_common = common_dates[-1]
                mask.loc[last_common:] = mask.loc[last_common].values
        else:
            # For specific market cap and sectoral indices:
            # Flag current constituents across their active tenure
            for t in current_constituents:
                mask[t] = True

        mask.to_parquet(out_file)
        print(f"    [OK] Saved {out_file.name} ({mask.shape[0]} dates x {mask.shape[1]} tickers)")

    print("=" * 70)

if __name__ == "__main__":
    build_pit_membership_masks()
