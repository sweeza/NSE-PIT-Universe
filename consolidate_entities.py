"""
Phase 1: Consolidates historical symbol changes and ISIN mappings across all 12
vectorized market tensors, security master, and aliases.

Guarantees:
1. Zero data loss: All historical sessions from old tickers are forward-stitched into their
   canonical active ticker column.
2. 0 date conflicts: All transitions are strictly non-overlapping and chronological.
3. Alias map: Historical symbols automatically resolve to canonical tickers in nseuniverse.
"""

import sys
import json
from pathlib import Path
import pandas as pd
import numpy as np
import config

def build_entity_resolution_map():
    print("=" * 70)
    print("BUILDING UNIFIED ENTITY RESOLUTION MAP (ISIN + SYMBOLCHANGE)")
    print("=" * 70)

    close_df = pd.read_parquet(config.TENSOR_FILES["close"])
    isin_df = pd.read_parquet(config.TENSOR_FILES["isin"])
    all_cols = set(close_df.columns)

    # 1. Primary ISIN for each column
    col_isin = {}
    for col in isin_df.columns:
        s = isin_df[col].dropna()
        if not s.empty:
            val = s.value_counts().index[0]
            if val and str(val) != "None":
                col_isin[col] = str(val).strip()

    isin_to_cols = {}
    for col, val in col_isin.items():
        isin_to_cols.setdefault(val, []).append(col)

    isin_adj = {}
    for isin, cols in isin_to_cols.items():
        if len(cols) > 1:
            sorted_cols = sorted(
                cols,
                key=lambda c: close_df[c].dropna().index[0] if not close_df[c].dropna().empty else pd.to_datetime("2099-01-01")
            )
            canonical = sorted_cols[-1]
            for c in sorted_cols[:-1]:
                isin_adj[c] = canonical

    # 2. Add symbolchange.csv transitions
    sc_file = config.METADATA_DIR / "symbolchange.csv"
    sc_adj = {}
    if sc_file.exists():
        sc = pd.read_csv(sc_file)
        sc.columns = [c.strip().upper() for c in sc.columns]
        for _, row in sc.iterrows():
            old = str(row["OLD SYMBOL"]).strip().upper()
            new = str(row["NEW SYMBOL"]).strip().upper()
            if old and new and old != new:
                old_t, new_t = f"{old}.NS", f"{new}.NS"
                if old_t in all_cols and new_t in all_cols:
                    s_old = close_df[old_t].dropna()
                    s_new = close_df[new_t].dropna()
                    if not s_old.empty and not s_new.empty:
                        # Strictly chronological (non-overlapping)
                        if s_old.index[-1] <= s_new.index[0]:
                            sc_adj[old_t] = new_t
                    elif not s_old.empty and s_new.empty:
                        sc_adj[old_t] = new_t
                    elif s_old.empty and not s_new.empty:
                        sc_adj[old_t] = new_t

    combined = {}
    combined.update(isin_adj)
    combined.update(sc_adj)

    def find_target(curr):
        visited = set()
        while curr in combined and curr not in visited:
            visited.add(curr)
            curr = combined[curr]
        return curr

    target_map = {old: find_target(old) for old in combined}
    target_map = {old: tgt for old, tgt in target_map.items() if old != tgt}

    print(f"  Total mapped entity transitions: {len(target_map)}")

    # Verify 0 conflicts
    conflicts = 0
    for can_t in set(target_map.values()):
        sources = [s for s, t in target_map.items() if t == can_t]
        cols = [can_t] + sources
        dates_seen = set()
        for col in cols:
            d_set = set(close_df[col].dropna().index)
            overlap = dates_seen.intersection(d_set)
            if len(overlap) > 0:
                conflicts += 1
                print(f"  Conflict in {can_t}: {col} overlaps {len(overlap)} dates")
            dates_seen.update(d_set)

    assert conflicts == 0, f"Found {conflicts} date overlap conflicts!"
    print("  [PASS] 100% Conflict-free entity resolution verified.")

    # Update or merge alias map
    alias_file = config.METADATA_DIR / "symbol_alias_map.json"
    existing_aliases = json.loads(alias_file.read_text()) if alias_file.exists() else {}
    for k, v in target_map.items():
        existing_aliases[k.replace(".NS", "")] = v.replace(".NS", "")
    alias_file.write_text(json.dumps(existing_aliases, indent=2))
    print(f"  Saved cumulative alias map ({len(existing_aliases)} symbols) to {alias_file.name}")

    return target_map


def stitch_tensors(target_map):
    if not target_map:
        print("\nNo additional tensors to stitch.")
        return

    print("\n" + "=" * 70)
    print("STITCHING 12 MARKET TENSORS ACROSS CANONICAL ENTITY TIMELINES")
    print("=" * 70)

    can_to_sources = {}
    for old_t, can_t in target_map.items():
        can_to_sources.setdefault(can_t, []).append(old_t)

    old_cols_to_remove = set(target_map.keys())
    print(f"  Total obsolete symbol columns to consolidate: {len(old_cols_to_remove)}")
    print(f"  Total receiving canonical columns:            {len(can_to_sources)}")

    for tensor_name in config.TENSOR_NAMES:
        f_path = config.TENSOR_FILES[tensor_name]
        print(f"  Processing {tensor_name:12} ...", end="", flush=True)
        df = pd.read_parquet(f_path)

        for can_t, sources in can_to_sources.items():
            if can_t not in df.columns:
                continue
            for src in sources:
                if src in df.columns:
                    src_s = df[src]
                    if df[can_t].dtype == object:
                        mask = df[can_t].isna() & src_s.notna()
                    else:
                        mask = np.isnan(df[can_t]) & ~np.isnan(src_s)
                    if mask.any():
                        df.loc[mask, can_t] = src_s[mask]

        remaining_cols = [c for c in df.columns if c not in old_cols_to_remove]
        df_stitched = df[remaining_cols]
        df_stitched.to_parquet(f_path, compression="zstd")
        print(f" Done. Reshaped from {df.shape[1]} -> {df_stitched.shape[1]} columns.")

    print("\n  Updating Master Security Master...")
    sec_master = pd.read_parquet(config.SECURITY_MASTER_FILE)
    sec_master_stitched = sec_master.loc[[c for c in sec_master.index if c not in old_cols_to_remove]].copy()
    sec_master_stitched.to_parquet(config.SECURITY_MASTER_FILE)
    print(f"  Security Master updated: {len(sec_master)} -> {len(sec_master_stitched)} instruments.")


if __name__ == "__main__":
    t_map = build_entity_resolution_map()
    stitch_tensors(t_map)
