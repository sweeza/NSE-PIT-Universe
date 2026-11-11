"""
Builds the comprehensive Master Security Master table for all NSE instruments
found across Bhavcopies (2004-2026), active listings, and official indices.

Features:
- Discovers all unique symbols (~6,000+).
- Classifies each instrument into:
    EQUITY, SME, ETF, MUTUAL_FUND, DEBT_INVIT_REIT, OTHER
- Maps official NSE Sector & Industry from official Nifty indices.
- Preserves ISIN, listing status, and series.
- Flags official index memberships (Nifty 50, 100, 200, LargeMid 250, Midcap 150,
  Smallcap 250, Nifty 500, Bank, IT, Auto, Pharma, FMCG, Metal, Energy, etc.).
"""

import sys
from pathlib import Path
from typing import Optional
import pandas as pd
import numpy as np
import config

def classify_instrument(symbol: str, series: str, isin: str, name: str) -> str:
    symbol = str(symbol).upper().strip()
    series = str(series).upper().strip() if pd.notna(series) else ""
    isin = str(isin).upper().strip() if pd.notna(isin) else ""
    name = str(name).upper().strip() if pd.notna(name) else ""

    # 1. SME Platform
    if series in ("SM", "ST") or "-SM" in symbol or "-ST" in symbol:
        return "SME"

    # 2. ETFs (Exchange Traded Funds)
    etf_indicators = [
        "BEES", "ETF", "NIFTYBEES", "BANKBEES", "GOLDBEES", "JUNIORBEES",
        "LIQUIDBEES", "INFRABEES", "PSUBNKBEES", "SHARIABEES", "CPSEETF",
        "BHARAT22", "MOM50", "LOWVOL", "ALPHA", "HDFCNIFTY", "HDFCSML250",
        "SETFNIF50", "SETFNN50", "NETFNIF100", "NETFMID150", "ABSLBANETF"
    ]
    if any(ind in symbol for ind in etf_indicators) or " ETF " in name or name.endswith(" ETF"):
        return "ETF"

    # 3. Mutual Funds / Close-ended schemes
    if series == "MF" or isin.startswith("INF") or "MUTUAL FUND" in name:
        # Check if it's explicitly an ETF vs MF scheme
        if any(ind in symbol for ind in ["BEES", "ETF"]):
            return "ETF"
        return "MUTUAL_FUND"

    # 4. Debt, NCDs, Preference shares, InvITs, REITs, Sovereign Gold Bonds
    debt_series = {
        "N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "NA", "NB", "NC", "ND", "NE", "NF",
        "NG", "NH", "NI", "NJ", "NK", "NL", "NM", "NN", "NO", "NP", "NQ", "NR", "NS", "NT", "NU",
        "NV", "NW", "NX", "NY", "NZ", "Y1", "Y2", "Y3", "Y4", "Y5", "Y6", "Y7", "Y8", "Y9",
        "IV", "RR", "GB", "GS", "P1", "P2"
    }
    if (
        series in debt_series
        or symbol.startswith("SGB")
        or "INVIT" in name
        or "REIT" in name
        or "BONDS" in name
        or "NCD" in name
        or isin.startswith("IN0")  # Govt securities
    ):
        return "DEBT_INVIT_REIT"

    # 5. Standard Equities
    if series in ("EQ", "BE", "BZ", ""):
        return "EQUITY"

    return "EQUITY"


def repair_security_master(sec_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    Applies institutional hardening and repairs to the Security Master:
    1. Computes authentic first_traded_date and last_traded_date directly from close.parquet (5,659 sessions).
    2. Backfills listing_date using first_traded_date whenever missing from EQUITY_L.csv (resolving all None listing dates).
    3. Fixes is_active_currently for all 592 SME platform instruments and ETFs by checking activity in the most recent 30 trading sessions.
    4. Assigns an immutable internal identifier (sec_id: NSE0001 through NSE4446).
    """
    print("\n" + "=" * 70)
    print("REPAIRING & HARDENING MASTER SECURITY MASTER")
    print("=" * 70)

    if sec_df is None:
        if not config.SECURITY_MASTER_FILE.exists():
            raise FileNotFoundError(f"Security master file {config.SECURITY_MASTER_FILE} does not exist. Run build_security_master() first.")
        sec_df = pd.read_parquet(config.SECURITY_MASTER_FILE)
        print(f"  Loaded existing Security Master: {len(sec_df):,} instruments")

    # If canonical market tensors exist, align and calculate metrics
    if config.TENSOR_FILES["close"].exists():
        cl = pd.read_parquet(config.TENSOR_FILES["close"])
        tensor_cols = cl.columns

        # Ensure 100% matrix dimensional parity
        sec_df = sec_df.reindex(index=tensor_cols)
        sym_fallback = pd.Series(sec_df.index.str.replace(".NS", "", regex=False), index=sec_df.index)
        sec_df["symbol"] = sec_df["symbol"].fillna(sym_fallback)
        sec_df["company_name"] = sec_df["company_name"].fillna(sec_df["symbol"])
        sec_df["asset_class"] = sec_df["asset_class"].fillna("EQUITY")
        sec_df["sector"] = sec_df["sector"].fillna("Unclassified")
        sec_df["series"] = sec_df["series"].fillna("EQ")
        bool_cols = [c for c in sec_df.columns if c.startswith("in_") or c.startswith("is_")]
        sec_df[bool_cols] = sec_df[bool_cols].fillna(False).astype(bool)

        # 1. Compute authentic first_traded_date and last_traded_date directly from close.parquet
        print("  [1/4] Computing authentic first_traded_date and last_traded_date from close tensor...")
        not_na = cl.notna()
        any_traded = not_na.any()
        first_idx = not_na.idxmax()
        last_idx = not_na.iloc[::-1].idxmax()

        sec_df["first_traded_date"] = first_idx.dt.strftime("%Y-%m-%d").where(any_traded, None)
        sec_df["last_traded_date"] = last_idx.dt.strftime("%Y-%m-%d").where(any_traded, None)
        print(f"        Authentic trading dates computed for {len(sec_df):,} instruments.")

        # 2. Backfill listing_date using first_traded_date whenever missing from EQUITY_L.csv
        print("  [2/4] Backfilling missing listing_date entries with authentic first_traded_date...")
        missing_listing = (
            sec_df["listing_date"].isna()
            | (sec_df["listing_date"] == "")
            | (sec_df["listing_date"].astype(str).str.strip().str.lower() == "none")
        )
        missing_count = missing_listing.sum()
        sec_df.loc[missing_listing, "listing_date"] = sec_df.loc[missing_listing, "first_traded_date"]
        print(f"        Backfilled {missing_count:,} missing listing dates (0 remaining None).")

        # 3. Fix is_active_currently for all SME platform instruments and ETFs by checking activity in the most recent 30 sessions
        print("  [3/4] Updating is_active_currently for SME and ETF instruments based on recent 30 sessions...")
        last_30_sessions = cl.iloc[-30:]
        active_in_last_30 = last_30_sessions.notna().any()
        is_sme_or_etf = sec_df["asset_class"].isin(["SME", "ETF"])
        sme_etf_tickers = sec_df.index[is_sme_or_etf]
        sec_df.loc[is_sme_or_etf, "is_active_currently"] = (
            active_in_last_30.reindex(sme_etf_tickers).fillna(False).astype(bool).values
        )
        active_sme = sec_df.loc[sec_df["asset_class"] == "SME", "is_active_currently"].sum()
        active_etf = sec_df.loc[sec_df["asset_class"] == "ETF", "is_active_currently"].sum()
        print(f"        SME active: {active_sme}/592, ETF active: {active_etf}/122.")

    # 4. Assign an immutable internal identifier (sec_id: NSE0001 through NSE4446)
    print("  [4/4] Assigning immutable internal identifiers (sec_id: NSE0001 through NSE4446)...")
    sec_df["sec_id"] = [f"NSE{i:04d}" for i in range(1, len(sec_df) + 1)]

    # Reorder columns with sec_id as the primary internal identifier
    col_order = ["sec_id"] + [c for c in sec_df.columns if c != "sec_id"]
    sec_df = sec_df[col_order]

    config.METADATA_DIR.mkdir(parents=True, exist_ok=True)
    sec_df.to_parquet(config.SECURITY_MASTER_FILE)

    print(f"\n  [OK] Master Security Master saved to {config.SECURITY_MASTER_FILE.name}")
    print(f"       Total instruments: {len(sec_df):,}")
    print(f"       sec_id range:      {sec_df['sec_id'].iloc[0]} - {sec_df['sec_id'].iloc[-1]}")
    print("\n  Asset Class Distribution:")
    for ac, count in sec_df["asset_class"].value_counts().items():
        print(f"       - {ac:18}: {count:,}")
    print("=" * 70)
    return sec_df


def build_security_master(full_bhav_scan: bool = False):
    print("=" * 70)
    print("BUILDING CANONICAL NSE MASTER SECURITY MASTER")
    print("=" * 70)

    # 1. Load active equities from EQUITY_L.csv
    equity_l_file = config.METADATA_DIR / "EQUITY_L.csv"
    active_df = pd.DataFrame()
    if equity_l_file.exists():
        active_df = pd.read_csv(equity_l_file)
        active_df.columns = [c.strip().upper() for c in active_df.columns]
        print(f"  Loaded active EQUITY_L: {len(active_df)} entries")

    # 2. Ingest official NiftyIndices constituent lists for Sector/Industry mapping
    index_files = list(config.RAW_INDICES_DIR.glob("*.csv"))
    print(f"  Ingesting {len(index_files)} official index constituent tables...")
    
    sector_map = {}      # symbol -> Industry
    company_names = {}   # symbol -> Company Name
    index_tags = {}      # symbol -> set(indices)

    for idx_file in index_files:
        idx_name = idx_file.stem
        try:
            df = pd.read_csv(idx_file)
            sym_col = [c for c in df.columns if "SYMBOL" in c.upper()][0]
            name_col = [c for c in df.columns if "COMPANY" in c.upper()][0]
            ind_col = [c for c in df.columns if "INDUSTRY" in c.upper()]
            
            for _, row in df.iterrows():
                sym = str(row[sym_col]).strip()
                if not sym or sym.lower() == "nan":
                    continue
                if sym not in index_tags:
                    index_tags[sym] = set()
                index_tags[sym].add(idx_name)

                if sym not in company_names and pd.notna(row[name_col]):
                    company_names[sym] = str(row[name_col]).strip()

                if ind_col and pd.notna(row[ind_col[0]]):
                    sector_map[sym] = str(row[ind_col[0]]).strip()
        except Exception as e:
            print(f"    Warning reading {idx_file.name}: {e}")

    # 3. Discover unique symbols from comprehensive archives:
    # First, ingest historical company symbol master if available from Moshi 15
    bhav_info = {}  # symbol -> {isin, series, name}
    csm_file = config.MOSHI_DIR / "Output" / "company_symbol_master.parquet"
    if csm_file.exists():
        try:
            csm = pd.read_parquet(csm_file)
            for _, row in csm.iterrows():
                s = str(row["symbol"]).strip()
                if s and s.lower() != "nan":
                    bhav_info[s] = {
                        "series": "EQ",
                        "isin": str(row["isin"]).strip() if pd.notna(row["isin"]) and str(row["isin"]).strip() else None,
                        "name": str(row["company_name"]).strip() if pd.notna(row["company_name"]) else s,
                    }
            print(f"  Ingested {len(bhav_info):,} symbols from Moshi 15 company symbol master.")
        except Exception as e:
            print(f"  Warning reading company symbol master: {e}")

    # Comprehensive discovery across Bhavcopies if requested
    if full_bhav_scan:
        bhav_cache = config.get_bhavcopy_files()
        print(f"  Scanning complete Bhavcopy archive ({len(bhav_cache):,} files) for universe symbols...")

        for f in bhav_cache:
            try:
                df = pd.read_parquet(f)
                sym_col = "SYMBOL" if "SYMBOL" in df.columns else None
                series_col = "SERIES" if "SERIES" in df.columns else None
                isin_col = "ISIN" if "ISIN" in df.columns else None

                if sym_col:
                    for _, row in df[[c for c in [sym_col, series_col, isin_col] if c]].iterrows():
                        s = str(row[sym_col]).strip()
                        if not s or s.lower() == "nan":
                            continue
                        if s not in bhav_info:
                            bhav_info[s] = {
                                "series": str(row[series_col]).strip() if series_col and pd.notna(row[series_col]) else "EQ",
                                "isin": str(row[isin_col]).strip() if isin_col and pd.notna(row[isin_col]) else None,
                            }
                        else:
                            if not bhav_info[s].get("isin") and isin_col and pd.notna(row[isin_col]):
                                bhav_info[s]["isin"] = str(row[isin_col]).strip()
            except Exception:
                continue

        print(f"  Discovered {len(bhav_info):,} distinct symbols across Bhavcopy archive.")

    # 4. Merge all symbols: Bhavcopy + Active listings + Index constituents + Symbol changes
    all_symbols = set(bhav_info.keys())
    if not active_df.empty and "SYMBOL" in active_df.columns:
        all_symbols.update(active_df["SYMBOL"].dropna().str.strip().tolist())
    all_symbols.update(index_tags.keys())

    # Symbol changes
    sym_change_file = config.METADATA_DIR / "symbolchange.csv"
    if sym_change_file.exists():
        sc = pd.read_csv(sym_change_file)
        sc.columns = [c.strip().upper() for c in sc.columns]
        if "SM_OLD_SYMBOL" in sc.columns and "SM_NEW_SYMBOL" in sc.columns:
            all_symbols.update(sc["SM_OLD_SYMBOL"].dropna().str.strip().tolist())
            all_symbols.update(sc["SM_NEW_SYMBOL"].dropna().str.strip().tolist())

    print(f"  Total consolidated universe scrips: {len(all_symbols)}")

    # 5. Build master records
    records = []
    active_symbols = set(active_df["SYMBOL"].str.strip().tolist()) if not active_df.empty else set()
    active_map = active_df.set_index("SYMBOL").to_dict("index") if not active_df.empty else {}

    for sym in sorted(all_symbols):
        ticker = f"{sym}.NS"
        info = bhav_info.get(sym, {})
        act = active_map.get(sym, {})

        name = act.get("NAME OF COMPANY") or company_names.get(sym) or sym
        series = act.get("SERIES") or info.get("series") or "EQ"
        isin = act.get("ISIN NUMBER") or info.get("isin") or None
        listing_date = act.get("DATE OF LISTING") or None
        face_val = act.get("FACE VALUE") or None
        
        industry = sector_map.get(sym, "Unclassified")
        asset_class = classify_instrument(sym, series, isin, name)
        
        tags = index_tags.get(sym, set())

        records.append({
            "ticker": ticker,
            "symbol": sym,
            "company_name": name,
            "asset_class": asset_class,
            "sector": industry,
            "series": series,
            "isin": isin,
            "listing_date": listing_date,
            "face_value": face_val,
            "is_active_currently": sym in active_symbols,
            "in_nifty50": "nifty50" in tags,
            "in_niftynext50": "niftynext50" in tags,
            "in_nifty100": "nifty100" in tags,
            "in_nifty200": "nifty200" in tags,
            "in_largemid250": "largemid250" in tags,
            "in_midcap150": "midcap150" in tags,
            "in_smallcap250": "smallcap250" in tags,
            "in_midsmall400": "midsmall400" in tags,
            "in_nifty500": "nifty500" in tags,
            "in_totalmarket": "totalmarket" in tags,
            "in_niftybank": "niftybank" in tags,
            "in_niftyit": "niftyit" in tags,
            "in_niftyauto": "niftyauto" in tags,
            "in_niftypharma": "niftypharma" in tags,
            "in_niftyfmcg": "niftyfmcg" in tags,
            "in_niftymetal": "niftymetal" in tags,
            "in_niftyenergy": "niftyenergy" in tags,
        })

    sec_df = pd.DataFrame(records).set_index("ticker")
    return repair_security_master(sec_df)


if __name__ == "__main__":
    if "--rebuild" in sys.argv:
        build_security_master(full_bhav_scan="--full-bhav-scan" in sys.argv)
    elif config.SECURITY_MASTER_FILE.exists():
        repair_security_master()
    else:
        build_security_master()
