"""
Download and cache all official NSE Index Bhavcopies from nsearchives.nseindia.com.
Uses ThreadPoolExecutor with exponential backoff and rate-limit handling.
"""

import time
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import config

INDEX_CACHE_DIR = config.DATA_DIR / "index_cache"
INDEX_CACHE_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def download_single_index(dt: pd.Timestamp) -> bool:
    date_str = dt.strftime("%d%m%Y")
    out_file = INDEX_CACHE_DIR / f"index_{dt.strftime('%Y-%m-%d')}.csv"

    if out_file.exists() and out_file.stat().st_size > 200:
        return True

    url = f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{date_str}.csv"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                content = resp.read()
                if len(content) > 200 and b"Index Name" in content:
                    with open(out_file, "wb") as f:
                        f.write(content)
                    return True
                else:
                    return False
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            time.sleep(1.0 * (attempt + 1))
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return False


def run_download(max_workers: int = 8):
    print("=" * 70)
    print("DOWNLOADING OFFICIAL NSE INDEX ARCHIVES (2012 TO PRESENT)")
    print("=" * 70)

    # Get trading dates from existing equity bhavcopy cache
    bhav_files = list(config.BHAVCOPY_CACHE_DIR.glob("*.parquet"))
    all_dates = sorted([
        pd.to_datetime(f.stem.replace("bhav_", ""))
        for f in bhav_files
        if pd.to_datetime(f.stem.replace("bhav_", "")) >= pd.to_datetime("2012-02-21")
    ])

    existing = {
        f.stem.replace("index_", "")
        for f in INDEX_CACHE_DIR.glob("*.csv")
        if f.stat().st_size > 200
    }
    to_download = [d for d in all_dates if d.strftime("%Y-%m-%d") not in existing]

    print(f"Total sessions: {len(all_dates):,}")
    print(f"Already cached: {len(existing):,}")
    print(f"Pending to fetch: {len(to_download):,}")

    success_count = len(existing)
    miss_count = 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download_single_index, d): d for d in to_download}
        for i, fut in enumerate(as_completed(futures), 1):
            res = fut.result()
            if res:
                success_count += 1
            else:
                miss_count += 1

            if i % 100 == 0 or i == len(to_download):
                elapsed = time.time() - t0
                print(f"  [{i}/{len(to_download)}] Cached: {success_count:,} | Misses/404: {miss_count:,} | Elapsed: {elapsed:.1f}s")

    print(f"\nFinished! Total valid index files in cache: {len(list(INDEX_CACHE_DIR.glob('*.csv'))):,}")


if __name__ == "__main__":
    run_download()
