"""
Configuration module for Canonical All-Instrument NSE Universe ('00 Nifty Universe').
Centralizes paths, directories, asset classification rules, official indices, and schemas.
"""

from pathlib import Path

# Base Directories
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
METADATA_DIR = DATA_DIR / "metadata"
PIT_DIR = METADATA_DIR / "pit_memberships"
TENSOR_DIR = DATA_DIR / "tensors"
RAW_INDICES_DIR = DATA_DIR / "raw_indices"

# Shared Bhavcopy Cache (reusing the 7,892 cached Bhavcopies archive)
SHARED_BHAVCOPY_DIR = (
    Path(r"G:\My Drive\01 Projects\10 Antigravity Playground\04 Fin Markets Feeler\N500 Universe with Bhavcopies\data\bhavcopy_cache")
)
BHAVCOPY_CACHE_DIR = SHARED_BHAVCOPY_DIR if SHARED_BHAVCOPY_DIR.exists() else DATA_DIR / "bhavcopy_cache"

# Source Metadata from N500 project
SOURCE_METADATA_DIR = (
    Path(r"G:\My Drive\01 Projects\10 Antigravity Playground\04 Fin Markets Feeler\N500 Universe with Bhavcopies\data\metadata")
)

# Canonical Output Files
SECURITY_MASTER_FILE = METADATA_DIR / "security_master.parquet"
CORPORATE_ACTIONS_FILE = METADATA_DIR / "corporate_actions.parquet"
SYMBOL_CHANGE_FILE = METADATA_DIR / "symbolchange.csv"
INDEX_REBALANCING_FILE = METADATA_DIR / "index_rebalancing_events.parquet"
VALIDATION_REPORT_FILE = DATA_DIR / "validation_report.json"

# Market Data Extended Tensors (12 Synchronous Matrices)
TENSOR_NAMES = [
    "open", "high", "low", "close", "volume", "turnover",
    "trades", "vwap", "last", "prevclose", "series", "isin"
]
TENSOR_FILES = {name: TENSOR_DIR / f"{name}.parquet" for name in TENSOR_NAMES}

# Asset Class Definitions
ASSET_CLASSES = [
    "EQUITY",            # Standard equities (EQ, BE, BZ)
    "SME",               # NSE Emerge SME platform (SM, ST)
    "ETF",               # Exchange Traded Funds (EQ/ETF series)
    "MUTUAL_FUND",       # Close-ended MF schemes (MF series)
    "DEBT_INVIT_REIT",   # Debt, NCDs, Preference shares, InvITs, REITs (N1-NY, IV, RR, GB, GS)
    "OTHER"              # Miscellaneous/unclassified
]

# Official NiftyIndices URL map
OFFICIAL_INDEX_URLS = {
    # Broad Market / Mcap-weighted
    "nifty50": "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv",
    "niftynext50": "https://www.niftyindices.com/IndexConstituent/ind_niftynext50list.csv",
    "nifty100": "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv",
    "nifty200": "https://www.niftyindices.com/IndexConstituent/ind_nifty200list.csv",
    "largemid250": "https://www.niftyindices.com/IndexConstituent/ind_niftylargemidcap250list.csv",
    "midcap150": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
    "smallcap250": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
    "midsmall400": "https://www.niftyindices.com/IndexConstituent/ind_niftymidsmallcap400list.csv",
    "nifty500": "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "totalmarket": "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv",
    # Official Sectoral Indices
    "niftybank": "https://www.niftyindices.com/IndexConstituent/ind_niftybanklist.csv",
    "niftyit": "https://www.niftyindices.com/IndexConstituent/ind_niftyitlist.csv",
    "niftyauto": "https://www.niftyindices.com/IndexConstituent/ind_niftyautolist.csv",
    "niftypharma": "https://www.niftyindices.com/IndexConstituent/ind_niftypharmalist.csv",
    "niftyhealthcare": "https://www.niftyindices.com/IndexConstituent/ind_niftyhealthcarelist.csv",
    "niftyfmcg": "https://www.niftyindices.com/IndexConstituent/ind_niftyfmcglist.csv",
    "niftymetal": "https://www.niftyindices.com/IndexConstituent/ind_niftymetallist.csv",
    "niftyenergy": "https://www.niftyindices.com/IndexConstituent/ind_niftyenergylist.csv",
    "niftyoilgas": "https://www.niftyindices.com/IndexConstituent/ind_niftyoilgaslist.csv",
    "niftyfinance": "https://www.niftyindices.com/IndexConstituent/ind_niftyfinancelist.csv",
    "niftyrealty": "https://www.niftyindices.com/IndexConstituent/ind_niftyrealtylist.csv",
    "niftymedia": "https://www.niftyindices.com/IndexConstituent/ind_niftymedialist.csv",
    "niftyconsumerdurables": "https://www.niftyindices.com/IndexConstituent/ind_niftyconsumerdurableslist.csv",
}

# Mapping of Index Key to PIT mask file
PIT_INDEX_FILES = {
    idx: PIT_DIR / f"{idx}.parquet" for idx in OFFICIAL_INDEX_URLS.keys()
}
