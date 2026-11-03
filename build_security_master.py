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


def build_security_master():
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

    # 3. Discover all unique symbols across cached Bhavcopies (sample across all years + all recent)
    bhav_cache = list(config.BHAVCOPY_CACHE_DIR.glob("*.parquet"))
    print(f"  Scanning Bhavcopy archive ({len(bhav_cache)} files) for universe symbols...")

    bhav_info = {} # symbol -> {isin, series, name}
    
    # We sample 250 files across the timeline to capture every persistent and transient symbol
    step = max(1, len(bhav_cache) // 250)
    sampled_files = bhav_cache[::step] + bhav_cache[-30:] # include latest 30 sessions
    sampled_files = sorted(list(set(sampled_files)))

    for f in sampled_files:
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
                        if not bhav_info[s]["isin"] and isin_col and pd.notna(row[isin_col]):
                            bhav_info[s]["isin"] = str(row[isin_col]).strip()
        except Exception:
            continue

    print(f"  Discovered {len(bhav_info)} distinct symbols across Bhavcopy sample.")

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
    config.METADATA_DIR.mkdir(parents=True, exist_ok=True)
    sec_df.to_parquet(config.SECURITY_MASTER_FILE)

    print(f"\n  [OK] Master Security Master saved to {config.SECURITY_MASTER_FILE.name}")
    print(f"       Total instruments: {len(sec_df):,}")
    print("\n  Asset Class Distribution:")
    for ac, count in sec_df["asset_class"].value_counts().items():
        print(f"       - {ac:18}: {count:,}")
    print("=" * 70)
    return sec_df

if __name__ == "__main__":
    build_security_master()
