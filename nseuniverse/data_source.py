"""
Data and cache management for nseuniverse.
Handles local tensor discovery and transparent on-demand cloud downloading/caching.
"""

import os
import shutil
import urllib.request
from pathlib import Path
from typing import Optional, Dict
import pandas as pd

# Remote repository raw CDN base
DEFAULT_REMOTE_BASE = "https://media.githubusercontent.com/media/sweeza/NSE-PIT-Universe/main/data"

# Local user cache default directory (~/.cache/nseuniverse)
USER_CACHE_DIR = Path(os.environ.get("NSEUNIVERSE_CACHE_DIR", Path.home() / ".cache" / "nseuniverse"))

# Local repo check (if running inside this repository clone)
_CURRENT_DIR = Path(__file__).resolve().parent.parent
_REPO_DATA_DIR = _CURRENT_DIR / "data"

TENSOR_NAMES = [
    "open", "high", "low", "close", "volume", "turnover",
    "trades", "vwap", "last", "prevclose", "series", "isin"
]

INDEX_NAMES = [
    "nifty50", "niftynext50", "nifty100", "nifty200",
    "largemid250", "midcap150", "smallcap250", "midsmall400", "nifty500", "totalmarket",
    "niftybank", "niftyit", "niftyauto", "niftypharma",
    "niftyhealthcare", "niftyfmcg", "niftymetal", "niftyenergy", "niftyoilgas",
    "niftyfinance", "niftyrealty", "niftymedia", "niftyconsumerdurables"
]


def _get_remote_url(relative_path: str) -> str:
    base = os.environ.get("NSEUNIVERSE_REMOTE_URL", DEFAULT_REMOTE_BASE).rstrip("/")
    return f"{base}/{relative_path.lstrip('/')}"


def _download_file(url: str, dest_path: Path, show_progress: bool = True) -> Path:
    """Downloads a file over HTTP with progress reporting."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
    
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "nseuniverse-client/1.0 (Python)"}
    )
    
    with urllib.request.urlopen(req) as resp, open(tmp_path, "wb") as out_file:
        total_size = int(resp.headers.get("Content-Length", 0))
        block_size = 1024 * 1024  # 1 MB
        downloaded = 0
        
        while True:
            chunk = resp.read(block_size)
            if not chunk:
                break
            out_file.write(chunk)
            downloaded += len(chunk)
            if show_progress and total_size > 0:
                mb_down = downloaded / (1024 * 1024)
                mb_total = total_size / (1024 * 1024)
                print(f"\rDownloading {dest_path.name}: {mb_down:.1f}/{mb_total:.1f} MB ({downloaded*100/total_size:.1f}%)", end="", flush=True)
                
    if show_progress and total_size > 0:
        print()  # newline
        
    shutil.move(tmp_path, dest_path)
    return dest_path


def resolve_file(relative_path: str, auto_download: bool = True) -> Path:
    """
    Resolves a file path:
    1. Checks local repository data directory (_REPO_DATA_DIR).
    2. Checks user cache directory (USER_CACHE_DIR).
    3. If missing and auto_download=True, downloads from GitHub LFS CDN.
    """
    # 1. Local repository check
    if _REPO_DATA_DIR.exists():
        repo_file = _REPO_DATA_DIR / relative_path
        if repo_file.exists():
            return repo_file

    # 2. User cache check
    cache_file = USER_CACHE_DIR / relative_path
    if cache_file.exists():
        return cache_file

    # 3. On-demand download
    if not auto_download:
        raise FileNotFoundError(f"File {relative_path} not found locally and auto_download is disabled.")

    remote_url = _get_remote_url(relative_path)
    return _download_file(remote_url, cache_file)


def get_security_master_path() -> Path:
    return resolve_file("metadata/security_master.parquet")


def get_corporate_actions_path() -> Path:
    return resolve_file("metadata/applied_corporate_actions.parquet")


def get_tensor_path(name: str) -> Path:
    name_clean = name.lower().strip()
    return resolve_file(f"tensors/{name_clean}.parquet")


def get_index_path(index_name: str) -> Path:
    name_clean = index_name.lower().strip()
    return resolve_file(f"metadata/pit_memberships/{name_clean}.parquet")
