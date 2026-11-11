"""
Exchange Calendar and Official NSE Trading Holidays Module.

Provides:
- Comprehensive Point-in-Time NSE Capital Market (CM) trading holiday database (1997-2026+).
- Identification of trading vs non-trading days (weekends + official exchange holidays).
- Support for special trading sessions (Diwali Muhurat trading, Union Budget Saturday sessions).
- Candidate trading session generation for daily automated updater.
- Offline-first architecture with optional dynamic online synchronization with NSE API.
"""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Set, Union
import numpy as np
import pandas as pd
import requests

import config
import jugaad_data.holidays as jh

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Comprehensive registry of verified special trading sessions in NSE Capital Market history:
# 1. Special Saturday/Sunday sessions (Diwali Muhurat, Union Budget, Disaster Recovery drills).
# 2. Weekday Diwali Muhurat trading sessions (1-hour official evening trading session with published Bhavcopy).
# 3. Known historical dates where regular trading occurred despite initial gazette holiday announcements.
SPECIAL_TRADING_SESSIONS: Set[date] = {
    # Special Weekend Sessions
    date(2004, 4, 17),  # Saturday
    date(2004, 10, 9),  # Saturday
    date(2005, 6, 4),   # Saturday
    date(2005, 11, 26), # Saturday
    date(2006, 4, 29),  # Saturday
    date(2006, 6, 25),  # Sunday
    date(2006, 10, 21), # Saturday - Diwali Muhurat 2006
    date(2009, 10, 17), # Saturday - Diwali Muhurat 2009
    date(2010, 2, 6),   # Saturday - Special Budget Session 2010
    date(2012, 1, 7),   # Saturday - Testing Session
    date(2012, 3, 3),   # Saturday - Special Trading
    date(2012, 4, 28),  # Saturday - Special Trading
    date(2012, 9, 8),   # Saturday - Testing Session
    date(2013, 5, 11),  # Saturday - Testing Session
    date(2013, 11, 3),  # Sunday   - Diwali Muhurat 2013
    date(2014, 3, 22),  # Saturday - Testing Session
    date(2015, 2, 28),  # Saturday - Union Budget 2015
    date(2016, 10, 30), # Sunday   - Diwali Muhurat 2016
    date(2019, 10, 27), # Sunday   - Diwali Muhurat 2019
    date(2020, 11, 14), # Saturday - Diwali Muhurat 2020
    date(2023, 11, 12), # Sunday   - Diwali Muhurat 2023
    date(2024, 3, 2),   # Saturday - Special Live DR Trading 2024
    date(2024, 5, 18),  # Saturday - Special Live DR Trading 2024
    date(2025, 2, 1),   # Saturday - Union Budget 2025
    date(2026, 11, 8),  # Sunday   - Diwali Muhurat 2026

    # Weekday Diwali Muhurat Trading Sessions (Traded sessions on official holiday dates)
    date(2004, 11, 12), # Friday   - Diwali Muhurat 2004
    date(2005, 11, 1),  # Tuesday  - Diwali Muhurat 2005
    date(2007, 11, 9),  # Friday   - Diwali Muhurat 2007
    date(2008, 10, 28), # Tuesday  - Diwali Muhurat 2008
    date(2010, 11, 5),  # Friday   - Diwali Muhurat 2010
    date(2011, 10, 26), # Wednesday- Diwali Muhurat 2011
    date(2012, 11, 13), # Tuesday  - Diwali Muhurat 2012
    date(2014, 10, 23), # Thursday - Diwali Muhurat 2014
    date(2015, 11, 11), # Wednesday- Diwali Muhurat 2015
    date(2017, 10, 19), # Thursday - Diwali Muhurat 2017
    date(2018, 11, 7),  # Wednesday- Diwali Muhurat 2018
    date(2021, 11, 4),  # Thursday - Diwali Muhurat 2021
    date(2022, 10, 24), # Monday   - Diwali Muhurat 2022
    date(2024, 11, 1),  # Friday   - Diwali Muhurat 2024
    date(2025, 10, 21), # Tuesday  - Diwali Muhurat 2025

    # Verified Traded Sessions that were not market holidays
    date(2004, 1, 1),   # Thursday - New Year 2004 (Traded session in canonical history)
    date(2020, 7, 31),  # Friday   - Bakri Id rescheduled to Saturday Aug 1, 2020 (Traded)
}

# Backward-compatible subset alias for weekend special sessions
SPECIAL_WEEKEND_SESSIONS: Set[date] = {d for d in SPECIAL_TRADING_SESSIONS if d.weekday() >= 5}

# Known fixed-date holiday descriptions
KNOWN_DESCRIPTIONS = {
    (1, 26): "Republic Day",
    (4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
    (5, 1): "Maharashtra Day",
    (8, 15): "Independence Day",
    (10, 2): "Mahatma Gandhi Jayanti",
    (12, 25): "Christmas",
}

_HOLIDAYS_CACHE: Optional[pd.DataFrame] = None
_HOLIDAY_DATES_CACHE: Optional[Set[date]] = None
_CANONICAL_DATES_CACHE: Optional[Set[date]] = None


def fetch_live_nse_holidays() -> List[dict]:
    """
    Attempts to fetch official trading holidays for the current year from NSE API.
    Returns empty list if offline or if handshake fails.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Referer": "https://www.nseindia.com/resources/exchange-communication-holidays",
    }
    session = requests.Session()
    try:
        session.get("https://www.nseindia.com", headers=headers, timeout=6)
        r = session.get(
            "https://www.nseindia.com/api/holiday-master?type=trading",
            headers=headers,
            timeout=8,
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("CM", [])
    except Exception:
        pass
    return []


def build_holidays_parquet(overwrite: bool = False) -> pd.DataFrame:
    """
    Constructs the authoritative Point-in-Time NSE trading holidays ledger (1997-2026+).
    Combines jugaad_data historical holiday dates with official NSE descriptions and live API feeds.
    Saves to data/metadata/holidays.parquet.
    """
    out_file = config.HOLIDAYS_FILE
    if out_file.exists() and not overwrite:
        df = pd.read_parquet(out_file)
        return df

    # 1. Base dates from verified jugaad_data registry (411 holidays 1997-2026)
    base_dates = set(jh.holidays_str)

    # 2. Live NSE official holidays
    live_holidays = fetch_live_nse_holidays()
    live_map = {}
    for item in live_holidays:
        raw_dt = item.get("tradingDate")
        desc = item.get("description", "Trading Holiday")
        if raw_dt:
            try:
                dt_obj = datetime.strptime(raw_dt.strip(), "%d-%b-%Y").date()
                d_str = dt_obj.strftime("%Y-%m-%d")
                live_map[d_str] = desc
                base_dates.add(d_str)
            except Exception:
                pass

    records = []
    for d_str in sorted(base_dates):
        dt_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
        weekday = dt_obj.strftime("%A")
        
        # Derive description
        desc = live_map.get(d_str)
        if not desc:
            desc = KNOWN_DESCRIPTIONS.get((dt_obj.month, dt_obj.day), "NSE Trading Holiday")
        
        is_sp = dt_obj in SPECIAL_TRADING_SESSIONS
        records.append({
            "date": d_str,
            "holiday_date": dt_obj,
            "description": desc,
            "weekday": weekday,
            "year": dt_obj.year,
            "is_trading_holiday": not is_sp,
            "segment": "CM",
        })

    df = pd.DataFrame(records)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_file, compression="zstd", index=False)
    print(f"  [OK] Saved {len(df)} official NSE trading holidays to {out_file.name}.")
    return df


def invalidate_calendar_cache():
    """Clears cached holiday and canonical tensor dates to force fresh reloads."""
    global _HOLIDAYS_CACHE, _HOLIDAY_DATES_CACHE, _CANONICAL_DATES_CACHE
    _HOLIDAYS_CACHE = None
    _HOLIDAY_DATES_CACHE = None
    _CANONICAL_DATES_CACHE = None


def get_holidays(reload: bool = False) -> pd.DataFrame:
    """Returns the comprehensive NSE Trading Holidays table."""
    global _HOLIDAYS_CACHE, _HOLIDAY_DATES_CACHE
    if _HOLIDAYS_CACHE is None or reload:
        out_file = config.HOLIDAYS_FILE
        if not out_file.exists():
            _HOLIDAYS_CACHE = build_holidays_parquet()
        else:
            _HOLIDAYS_CACHE = pd.read_parquet(out_file)
        
        # Active holiday dates are those marked as is_trading_holiday == True
        holiday_rows = _HOLIDAYS_CACHE[_HOLIDAYS_CACHE["is_trading_holiday"] == True] if "is_trading_holiday" in _HOLIDAYS_CACHE.columns else _HOLIDAYS_CACHE
        _HOLIDAY_DATES_CACHE = set(
            d if isinstance(d, date) else datetime.strptime(str(d), "%Y-%m-%d").date()
            for d in holiday_rows["date"]
        )
    return _HOLIDAYS_CACHE


def get_holiday_dates(reload: bool = False) -> Set[date]:
    """Returns the set of all official full NSE trading holiday dates."""
    global _HOLIDAY_DATES_CACHE
    if _HOLIDAY_DATES_CACHE is None or reload:
        get_holidays(reload=reload)
    return _HOLIDAY_DATES_CACHE or set()


def get_canonical_tensor_dates(reload: bool = False) -> Set[date]:
    """Returns the set of all trading session dates present in canonical tensors."""
    global _CANONICAL_DATES_CACHE
    if _CANONICAL_DATES_CACHE is None or reload:
        close_file = config.TENSOR_FILES["close"]
        if close_file.exists():
            df_close = pd.read_parquet(close_file, columns=[])
            _CANONICAL_DATES_CACHE = set(idx.date() for idx in df_close.index)
        else:
            _CANONICAL_DATES_CACHE = set()
    return _CANONICAL_DATES_CACHE or set()


def _to_date(dt: Union[date, datetime, str, pd.Timestamp]) -> date:
    """Coerces input to datetime.date object."""
    if isinstance(dt, pd.Timestamp):
        return dt.date()
    elif isinstance(dt, datetime):
        return dt.date()
    elif isinstance(dt, str):
        return datetime.strptime(dt[:10], "%Y-%m-%d").date()
    elif isinstance(dt, date):
        return dt
    raise ValueError(f"Cannot convert {type(dt)} to datetime.date: {dt}")


def is_trading_holiday(dt: Union[date, datetime, str, pd.Timestamp]) -> bool:
    """
    Checks whether the specified date is an official full NSE trading holiday (closed for all trading).
    Returns False for dates with special trading sessions (e.g. Diwali Muhurat trading).
    """
    d = _to_date(dt)
    if is_special_trading_session(d):
        return False
    return d in get_holiday_dates()


def is_special_trading_session(dt: Union[date, datetime, str, pd.Timestamp]) -> bool:
    """Checks whether the specified date was a designated special trading session (Muhurat, Budget, DR)."""
    d = _to_date(dt)
    return d in SPECIAL_TRADING_SESSIONS


def register_special_trading_session(dt: Union[date, datetime, str, pd.Timestamp]) -> date:
    """
    Dynamically registers an unannounced or newly scheduled special trading session 
    (e.g., ad-hoc disaster recovery testing session, special Saturday session) at runtime.
    Updates SPECIAL_TRADING_SESSIONS, SPECIAL_WEEKEND_SESSIONS, and invalidates calendar caches.
    """
    d = _to_date(dt)
    SPECIAL_TRADING_SESSIONS.add(d)
    if d.weekday() >= 5:
        SPECIAL_WEEKEND_SESSIONS.add(d)
    invalidate_calendar_cache()
    return d


def unregister_special_trading_session(dt: Union[date, datetime, str, pd.Timestamp]) -> None:
    """Removes a dynamically registered special trading session at runtime."""
    d = _to_date(dt)
    SPECIAL_TRADING_SESSIONS.discard(d)
    SPECIAL_WEEKEND_SESSIONS.discard(d)
    invalidate_calendar_cache()


def is_trading_day(dt: Union[date, datetime, str, pd.Timestamp], check_tensor_history: bool = True) -> bool:
    """
    Determines if a given date is a valid NSE trading day.
    
    Rules:
    1. If check_tensor_history=True and date <= latest tensor session, checks presence in canonical tensors.
    2. Special trading sessions (Diwali Muhurat, Budget, DR sessions) are ALWAYS valid trading days.
    3. Normal weekend dates (Saturday/Sunday): False.
    4. Weekday dates (Monday-Friday): True if NOT in official NSE trading holidays.
    """
    d = _to_date(dt)
    canonical = get_canonical_tensor_dates()
    
    if check_tensor_history and canonical:
        min_canonical = min(canonical)
        max_canonical = max(canonical)
        if min_canonical <= d <= max_canonical:
            return d in canonical

    # Beyond canonical bounds or when evaluating forward/synthetic calendars:
    if is_special_trading_session(d):
        return True

    if d.weekday() >= 5:  # Saturday (5) or Sunday (6)
        return False
    
    return not is_trading_holiday(d)


def get_trading_days(
    start_date: Union[date, datetime, str],
    end_date: Union[date, datetime, str],
) -> List[date]:
    """Returns list of valid NSE trading dates between start_date and end_date (inclusive)."""
    s = _to_date(start_date)
    e = _to_date(end_date)
    if s > e:
        return []
    
    cur = s
    trading_days = []
    while cur <= e:
        if is_trading_day(cur):
            trading_days.append(cur)
        cur += timedelta(days=1)
    return trading_days


def get_candidate_sessions(
    last_session: Union[date, datetime, str],
    target_date: Optional[Union[date, datetime, str]] = None,
) -> List[date]:
    """
    Returns candidate missing trading dates between last_session and target_date (default today).
    Filters out official NSE trading holidays and non-trading weekends while including special sessions.
    """
    last_dt = _to_date(last_session)
    tgt_dt = _to_date(target_date) if target_date else date.today()
    if last_dt >= tgt_dt:
        return []
    
    candidates = []
    cur = last_dt + timedelta(days=1)
    while cur <= tgt_dt:
        if is_trading_day(cur, check_tensor_history=False):
            candidates.append(cur)
        cur += timedelta(days=1)
    return candidates


def get_next_trading_day(dt: Union[date, datetime, str]) -> date:
    """Returns the immediate next NSE trading date after dt."""
    cur = _to_date(dt) + timedelta(days=1)
    while True:
        if is_trading_day(cur):
            return cur
        cur += timedelta(days=1)


def get_prev_trading_day(dt: Union[date, datetime, str]) -> date:
    """Returns the immediate prior NSE trading date before dt."""
    cur = _to_date(dt) - timedelta(days=1)
    while True:
        if is_trading_day(cur):
            return cur
        cur -= timedelta(days=1)


if __name__ == "__main__":
    print("Building / verifying official NSE Exchange Holiday Calendar...")
    df_h = build_holidays_parquet(overwrite=True)
    print(f"Total holidays: {len(df_h)} spanning {df_h['year'].min()} to {df_h['year'].max()}")
    sample_checks = [
        ("2026-01-26", "Republic Day 2026"),
        ("2026-11-10", "Diwali-Balipratipada 2026"),
        ("2024-01-22", "Ram Mandir Consecration 2024"),
        ("2025-02-01", "Union Budget 2025 (Saturday Special)"),
        ("2026-11-11", "Today"),
    ]
    for d_str, lbl in sample_checks:
        d = datetime.strptime(d_str, "%Y-%m-%d").date()
        is_h = is_trading_holiday(d)
        is_sp = is_special_trading_session(d)
        is_t = is_trading_day(d)
        print(f"  {d_str} ({lbl:38}): Holiday={is_h}, SpecialWeekend={is_sp}, TradingDay={is_t}")
