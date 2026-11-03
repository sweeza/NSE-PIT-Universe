"""
Downloads daily NSE Bhavcopy in-memory (or to temporary storage) using official NSE endpoints.
Includes cookie handshake, realistic headers, retry logic, and fallback support.
"""

import io
import os
import zipfile
import requests
import pandas as pd
from datetime import datetime, date

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/all-reports",
}

def fetch_nse_bhavcopy_stream(target_date: date) -> pd.DataFrame:
    """
    Fetches the daily NSE Bhavcopy directly into memory as a pandas DataFrame.
    Does not leave raw files on disk.
    """
    d_str = target_date.strftime("%d%m%Y")
    d_ud = target_date.strftime("%d%b%Y").upper()
    yr = target_date.strftime("%Y")
    mon = target_date.strftime("%b").upper()
    
    session = requests.Session()
    # Initial handshake to acquire cookies
    try:
        session.get("https://www.nseindia.com", headers=HEADERS, timeout=10)
    except Exception:
        pass

    # URL formats:
    # 1. New UDPR format (cmBhavcopy.csv.zip)
    url_udpr = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d_str}_F_0000.csv.zip"
    # 2. Classic cm format
    url_classic = f"https://archives.nseindia.com/content/historical/EQUITIES/{yr}/{mon}/cm{d_ud}bhav.csv.zip"

    urls = [url_udpr, url_classic]

    for url in urls:
        for attempt in range(3):
            try:
                r = session.get(url, headers=HEADERS, timeout=15)
                if r.status_code == 200 and len(r.content) > 1000:
                    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                        csv_name = z.namelist()[0]
                        with z.open(csv_name) as f:
                            df = pd.read_csv(f)
                            # Normalize columns
                            df.columns = [c.strip().upper() for c in df.columns]
                            rename_map = {
                                "TRADED_QTY": "TOTTRDQTY",
                                "TRADED_VAL": "TOTTRDVAL",
                                "TOTAL_TRADES": "TOTALTRADES",
                                "PREV_CLOSE": "PREVCLOSE",
                                "ISIN_CODE": "ISIN",
                                "SERIES_NAME": "SERIES",
                                "SYMBOL_NAME": "SYMBOL",
                                "TckrSymb": "SYMBOL",
                                "OpnPric": "OPEN",
                                "HghPric": "HIGH",
                                "LwPric": "LOW",
                                "ClsPric": "CLOSE",
                                "LastPric": "LAST",
                                "PrvsClsgPric": "PREVCLOSE",
                                "TtlTradgVol": "TOTTRDQTY",
                                "TtlTrfVal": "TOTTRDVAL",
                                "TtlNbOfTxsExctd": "TOTALTRADES",
                                "ISIN": "ISIN",
                                "SctySrs": "SERIES",
                            }
                            df = df.rename(columns=rename_map)
                            return df
            except Exception:
                pass

    return pd.DataFrame()
