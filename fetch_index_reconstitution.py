"""
Fetches and syncs official index constituent lists from niftyindices.com.
Caches raw CSVs and outputs normalized constituent mappings.
"""

import time
import requests
import pandas as pd
from pathlib import Path
import config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*"
}

def sync_official_indices():
    """Downloads all official broad-market and sectoral index constituent files."""
    config.RAW_INDICES_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    
    print("=" * 70)
    print("SYNCING OFFICIAL NIFTY INDEX CONSTITUENTS FROM NIFTYINDICES.COM")
    print("=" * 70)
    
    for idx_name, url in config.OFFICIAL_INDEX_URLS.items():
        out_csv = config.RAW_INDICES_DIR / f"{idx_name}.csv"
        success = False
        for attempt in range(3):
            try:
                r = requests.get(url, headers=HEADERS, timeout=12)
                if r.status_code == 200 and "Company Name" in r.text:
                    out_csv.write_text(r.text, encoding="utf-8")
                    df = pd.read_csv(out_csv)
                    results[idx_name] = len(df)
                    print(f"  [OK] {idx_name:24}: {len(df)} constituents saved.")
                    success = True
                    break
            except Exception as e:
                time.sleep(1.0)
        
        if not success:
            if out_csv.exists():
                df = pd.read_csv(out_csv)
                results[idx_name] = len(df)
                print(f"  [WARN] {idx_name:24}: download failed, using existing cache ({len(df)} constituents).")
            else:
                print(f"  [FAIL] {idx_name:24}: Failed to fetch.")

    return results

if __name__ == "__main__":
    sync_official_indices()
