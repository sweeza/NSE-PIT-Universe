"""
Unit and Regression Test Suite for Phase 4:
Atomic Daily Updates, Pre-Commit Mathematical Validation Gate, and Official Exchange Calendar.
"""

import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

import config
import nseuniverse_io as nio
import nseuniverse as nse
from exchange_calendar import (
    get_holidays,
    get_holiday_dates,
    is_trading_holiday,
    is_special_trading_session,
    is_trading_day,
    get_trading_days,
    get_candidate_sessions,
    get_next_trading_day,
    get_prev_trading_day,
    invalidate_calendar_cache,
    SPECIAL_WEEKEND_SESSIONS,
    SPECIAL_TRADING_SESSIONS,
)
from update_universe_daily import (
    validate_staged_tensors,
    atomic_commit_tensors,
    update_universe_daily,
    _safe_float,
)


class TestExchangeCalendar(unittest.TestCase):
    """Audits the Official NSE Exchange Calendar and Trading Session Logic."""

    def test_exchange_calendar_loading_and_schema(self):
        """Verifies that the holidays ledger loads cleanly with the expected schema."""
        df_h = get_holidays(reload=True)
        self.assertFalse(df_h.empty)
        expected_cols = {"date", "holiday_date", "description", "weekday", "year", "is_trading_holiday", "segment"}
        self.assertTrue(expected_cols.issubset(set(df_h.columns)))
        self.assertGreater(len(df_h), 400)
        self.assertLessEqual(df_h["year"].min(), 1997)
        self.assertGreaterEqual(df_h["year"].max(), 2026)

    def test_known_historical_and_future_holidays(self):
        """Verifies identification of official NSE trading holidays."""
        # Fixed national holidays
        self.assertTrue(is_trading_holiday("2026-01-26"))  # Republic Day 2026
        self.assertTrue(is_trading_holiday("2024-01-26"))  # Republic Day 2024
        self.assertTrue(is_trading_holiday("2025-08-15"))  # Independence Day 2025
        self.assertTrue(is_trading_holiday("2024-10-02"))  # Gandhi Jayanti 2024
        self.assertTrue(is_trading_holiday("2026-12-25"))  # Christmas 2026

        # Variable & Special Holidays
        self.assertTrue(is_trading_holiday("2026-11-10"))  # Diwali-Balipratipada 2026
        self.assertTrue(is_trading_holiday("2024-01-22"))  # Ram Mandir Pran Pratishtha
        self.assertTrue(is_trading_holiday("2020-04-14"))  # Dr. Ambedkar Jayanti 2020

        # Normal trading weekdays should NOT be holidays
        self.assertFalse(is_trading_holiday("2024-01-15"))  # Normal trading Monday
        self.assertFalse(is_trading_holiday("2026-11-11"))  # Normal trading Wednesday

    def test_special_weekend_trading_sessions(self):
        """Verifies identification of special weekend trading sessions (Muhurat, Budget)."""
        # Saturday Union Budget 2025
        self.assertTrue(is_special_trading_session("2025-02-01"))
        self.assertTrue(is_trading_day("2025-02-01"))

        # Saturday Union Budget 2015
        self.assertTrue(is_special_trading_session("2015-02-28"))
        self.assertTrue(is_trading_day("2015-02-28"))

        # Diwali Muhurat Trading Sessions on Weekends
        self.assertTrue(is_special_trading_session("2020-11-14"))  # Saturday
        self.assertTrue(is_trading_day("2020-11-14"))
        self.assertTrue(is_special_trading_session("2019-10-27"))  # Sunday
        self.assertTrue(is_trading_day("2019-10-27"))
        self.assertTrue(is_special_trading_session("2013-11-03"))  # Sunday
        self.assertTrue(is_trading_day("2013-11-03"))

        # Regular weekend dates should NOT be special sessions
        self.assertFalse(is_special_trading_session("2026-11-07"))  # Regular Saturday
        self.assertFalse(is_trading_day("2026-11-07"))
        self.assertFalse(is_special_trading_session("2026-11-15"))  # Regular Sunday
        self.assertFalse(is_trading_day("2026-11-15"))

    def test_is_trading_day_logic(self):
        """Verifies comprehensive is_trading_day logic across past and future sessions."""
        # Known historical session from close.parquet
        self.assertTrue(is_trading_day("2024-01-01"))
        self.assertTrue(is_trading_day("2026-11-03"))

        # Known historical holiday
        self.assertFalse(is_trading_day("2024-01-26"))
        self.assertFalse(is_trading_day("2026-11-10"))

        # Regular weekends
        self.assertFalse(is_trading_day("2026-11-14"))  # Saturday
        self.assertFalse(is_trading_day("2026-11-15"))  # Sunday

    def test_candidate_sessions_generation(self):
        """Verifies candidate session generation properly excludes holidays and normal weekends while including special sessions."""
        # Nov 3, 2026 (Tuesday) to Nov 11, 2026 (Wednesday):
        # Nov 4 (Wed): Candidate
        # Nov 5 (Thu): Candidate
        # Nov 6 (Fri): Candidate
        # Nov 7 (Sat): Normal Weekend -> Excluded
        # Nov 8 (Sun): Diwali Muhurat Special Trading Session -> Included!
        # Nov 9 (Mon): Candidate
        # Nov 10 (Tue): Official Holiday (Diwali-Balipratipada) -> Excluded
        # Nov 11 (Wed): Candidate
        cands = get_candidate_sessions("2026-11-03", "2026-11-11")
        cand_strs = [d.strftime("%Y-%m-%d") for d in cands]

        self.assertIn("2026-11-04", cand_strs)
        self.assertIn("2026-11-05", cand_strs)
        self.assertIn("2026-11-06", cand_strs)
        self.assertNotIn("2026-11-07", cand_strs)
        self.assertIn("2026-11-08", cand_strs)  # Diwali Muhurat session MUST be included
        self.assertIn("2026-11-09", cand_strs)
        self.assertNotIn("2026-11-10", cand_strs)  # Must be filtered as holiday
        self.assertIn("2026-11-11", cand_strs)

    def test_diwali_muhurat_trading_sessions(self):
        """Verifies that all verified Diwali Muhurat sessions (weekend and weekday) are recognized as trading days."""
        muhurat_sessions = [
            ("2026-11-08", "Sunday"),
            ("2024-11-01", "Friday"),
            ("2023-11-12", "Sunday"),
            ("2022-10-24", "Monday"),
            ("2020-11-14", "Saturday"),
            ("2019-10-27", "Sunday"),
            ("2013-11-03", "Sunday"),
            ("2006-10-21", "Saturday"),
        ]
        for d_str, day_name in muhurat_sessions:
            # Special trading sessions must be active trading days
            self.assertTrue(is_trading_day(d_str, check_tensor_history=False), f"Failed for {d_str} ({day_name})")
            self.assertTrue(is_special_trading_session(d_str), f"Not marked as special session: {d_str}")
            # And cannot be treated as non-trading holidays
            self.assertFalse(is_trading_holiday(d_str), f"Incorrectly marked as non-trading holiday: {d_str}")

    def test_next_and_prev_trading_day(self):
        """Verifies next and previous trading day navigation across long holiday weekends."""
        # Republic Day 2026: Jan 26 was a Monday.
        # Friday Jan 23 -> Next trading day should jump over weekend and Monday holiday to Tuesday Jan 27.
        next_d = get_next_trading_day("2026-01-23")
        self.assertEqual(next_d, date(2026, 1, 27))

        # Tuesday Jan 27 -> Previous trading day should jump backwards to Friday Jan 23.
        prev_d = get_prev_trading_day("2026-01-27")
        self.assertEqual(prev_d, date(2026, 1, 23))

    def test_client_api_exposure(self):
        """Verifies that exchange calendar functions are exposed directly on nseuniverse."""
        self.assertTrue(callable(nse.get_holidays))
        self.assertTrue(callable(nse.is_trading_day))
        self.assertTrue(callable(nse.is_trading_holiday))
        self.assertTrue(callable(nse.get_trading_days))
        self.assertTrue(callable(nse.get_next_trading_day))
        self.assertTrue(callable(nse.get_prev_trading_day))


class TestPreCommitValidationGate(unittest.TestCase):
    """Audits the simultaneous Pre-Commit Mathematical Validation Gate."""

    def setUp(self):
        self.tickers = ["RELIANCE.NS", "TCS.NS", "INFY.NS"]
        self.dates = pd.date_range("2026-01-01", periods=5, freq="B")
        self.existing_tensors = {}
        for name in config.TENSOR_NAMES:
            if name in ("series", "isin"):
                self.existing_tensors[name] = pd.DataFrame("EQ", index=self.dates, columns=self.tickers)
            else:
                self.existing_tensors[name] = pd.DataFrame(100.0, index=self.dates, columns=self.tickers)

    def _make_staged_row(self, c=100.0, o=100.0, h=105.0, l=95.0, v=1000.0, tn=100000.0):
        N = len(self.tickers)
        vw = tn / v if v > 0 else c
        return {
            "open": [np.full(N, o, dtype=np.float32)],
            "high": [np.full(N, h, dtype=np.float32)],
            "low": [np.full(N, l, dtype=np.float32)],
            "close": [np.full(N, c, dtype=np.float32)],
            "volume": [np.full(N, v, dtype=np.float64)],
            "turnover": [np.full(N, tn, dtype=np.float64)],
            "trades": [np.full(N, 50.0, dtype=np.float32)],
            "vwap": [np.full(N, vw, dtype=np.float32)],
            "last": [np.full(N, c, dtype=np.float32)],
            "prevclose": [np.full(N, c, dtype=np.float32)],
            "series": [np.array(["EQ"] * N, dtype=object)],
            "isin": [np.array(["INE000000000"] * N, dtype=object)],
        }

    def test_pre_commit_gate_passes_clean_data(self):
        """Verifies that fully valid staged rows pass the pre-commit gate."""
        staged_rows = self._make_staged_row(c=102.0, o=100.0, h=105.0, l=98.0, v=5000.0, tn=510000.0)
        staged_dates = [pd.Timestamp("2026-01-08")]

        passed, msg = validate_staged_tensors(
            existing_tensors=self.existing_tensors,
            staged_rows=staged_rows,
            staged_dates=staged_dates,
            tickers=self.tickers,
        )
        self.assertTrue(passed, msg)
        self.assertIn("0 violations", msg)

    def test_pre_commit_gate_rejects_high_less_than_low(self):
        """Verifies gate rejection when High < Low."""
        staged_rows = self._make_staged_row(h=90.0, l=95.0)  # High < Low!
        staged_dates = [pd.Timestamp("2026-01-08")]

        passed, msg = validate_staged_tensors(
            existing_tensors=self.existing_tensors,
            staged_rows=staged_rows,
            staged_dates=staged_dates,
            tickers=self.tickers,
        )
        self.assertFalse(passed)
        self.assertIn("H < L", msg)

    def test_pre_commit_gate_rejects_negative_price_and_volume(self):
        """Verifies gate rejection on non-positive close or negative volume."""
        # Non-positive close
        staged_rows_bad_c = self._make_staged_row(c=-5.0)
        staged_dates = [pd.Timestamp("2026-01-08")]
        passed_c, msg_c = validate_staged_tensors(
            existing_tensors=self.existing_tensors,
            staged_rows=staged_rows_bad_c,
            staged_dates=staged_dates,
            tickers=self.tickers,
        )
        self.assertFalse(passed_c)
        self.assertIn("C <= 0", msg_c)

        # Negative volume
        staged_rows_bad_v = self._make_staged_row(v=-100.0)
        passed_v, msg_v = validate_staged_tensors(
            existing_tensors=self.existing_tensors,
            staged_rows=staged_rows_bad_v,
            staged_dates=staged_dates,
            tickers=self.tickers,
        )
        self.assertFalse(passed_v)
        self.assertIn("V < 0", msg_v)

    def test_pre_commit_gate_rejects_non_monotonic_dates(self):
        """Verifies gate rejection when staged date is prior to or equal to latest tensor session."""
        staged_rows = self._make_staged_row()
        # Staged date is identical to existing latest date
        staged_dates = [self.dates[-1]]

        passed, msg = validate_staged_tensors(
            existing_tensors=self.existing_tensors,
            staged_rows=staged_rows,
            staged_dates=staged_dates,
            tickers=self.tickers,
        )
        self.assertFalse(passed)
        self.assertIn("not strictly after existing tensor date", msg)

    def test_pre_commit_gate_rejects_shape_mismatch(self):
        """Verifies gate rejection when a staged vector does not match the tickers length."""
        staged_rows = self._make_staged_row()
        # Corrupt volume row length to 2 instead of 3
        staged_rows["volume"] = [np.array([100.0, 200.0], dtype=np.float64)]
        staged_dates = [pd.Timestamp("2026-01-08")]

        passed, msg = validate_staged_tensors(
            existing_tensors=self.existing_tensors,
            staged_rows=staged_rows,
            staged_dates=staged_dates,
            tickers=self.tickers,
        )
        self.assertFalse(passed)
        self.assertIn("Column dimension mismatch", msg)

    def test_pre_commit_gate_rejects_missing_ohl_for_active_close(self):
        """Verifies gate rejection when close is valid but open, high, or low is NaN."""
        staged_rows = self._make_staged_row()
        # Set open to NaN for the first stock
        staged_rows["open"][0][0] = np.nan
        staged_dates = [pd.Timestamp("2026-01-08")]

        passed, msg = validate_staged_tensors(
            existing_tensors=self.existing_tensors,
            staged_rows=staged_rows,
            staged_dates=staged_dates,
            tickers=self.tickers,
        )
        self.assertFalse(passed)
        self.assertIn("Missing O/H/L for active close", msg)

    def test_safe_numeric_parsing(self):
        """Verifies _safe_float gracefully handles malformed, string-encoded, and missing values."""
        self.assertEqual(_safe_float(100.5), 100.5)
        self.assertEqual(_safe_float("1,250.75"), 1250.75)
        self.assertIsNone(_safe_float(" - "))
        self.assertIsNone(_safe_float("-"))
        self.assertIsNone(_safe_float("N/A"))
        self.assertIsNone(_safe_float("NA"))
        self.assertIsNone(_safe_float(""))
        self.assertIsNone(_safe_float(None))
        self.assertEqual(_safe_float(" - ", default=10.0), 10.0)
        self.assertEqual(_safe_float("invalid_str", default=50.0), 50.0)


class TestAtomicCommitAndRollback(unittest.TestCase):
    """Audits the Atomic Commit and Emergency Rollback Mechanism."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_nse_atomic_"))
        self.tickers = ["RELIANCE.NS", "TCS.NS", "INFY.NS"]
        self.dates = pd.date_range("2026-01-01", periods=4, freq="B")

        # Initialize mock on-disk parquet files for all 12 tensors
        self.tensor_files = {}
        self.base_tensors = {}
        for name in config.TENSOR_NAMES:
            p = self.test_dir / f"{name}.parquet"
            self.tensor_files[name] = p
            if name in ("series", "isin"):
                df = pd.DataFrame("EQ", index=self.dates, columns=self.tickers)
            else:
                df = pd.DataFrame(100.0, index=self.dates, columns=self.tickers, dtype=np.float32)
            df.to_parquet(p, compression="zstd")
            self.base_tensors[name] = df

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_happy_path_atomic_commit(self):
        """Verifies that 12 tensors commit atomically and clean up all temporary and backup files."""
        new_date = pd.Timestamp("2026-01-07")
        updated_tensors = {}
        for name in config.TENSOR_NAMES:
            df_cur = self.base_tensors[name]
            if name in ("series", "isin"):
                new_row = pd.DataFrame([["EQ"] * len(self.tickers)], index=[new_date], columns=self.tickers)
            else:
                new_row = pd.DataFrame([[105.0] * len(self.tickers)], index=[new_date], columns=self.tickers, dtype=np.float32)
            updated_tensors[name] = pd.concat([df_cur, new_row])

        success = atomic_commit_tensors(updated_tensors=updated_tensors, tensor_files=self.tensor_files)
        self.assertTrue(success)

        # Verify all 12 files on disk were updated to 5 rows
        for name, p in self.tensor_files.items():
            self.assertTrue(p.exists())
            df_disk = pd.read_parquet(p)
            self.assertEqual(len(df_disk), 5)
            self.assertEqual(df_disk.index[-1], new_date)

        # Verify zero temporary staging or backup files linger on disk
        tmps = list(self.test_dir.glob("*.tmp.parquet"))
        baks = list(self.test_dir.glob("*.bak.parquet"))
        self.assertEqual(len(tmps), 0)
        self.assertEqual(len(baks), 0)

    def test_emergency_rollback_on_io_failure(self):
        """
        Verifies that if an I/O error or failure occurs mid-commit (e.g. at tensor 6),
        the rollback mechanism triggers immediately and restores ALL 12 files to their exact
        pre-commit state with zero corruption or dimensional asymmetry.
        """
        new_date = pd.Timestamp("2026-01-07")
        updated_tensors = {}
        for name in config.TENSOR_NAMES:
            df_cur = self.base_tensors[name]
            if name in ("series", "isin"):
                new_row = pd.DataFrame([["EQ"] * len(self.tickers)], index=[new_date], columns=self.tickers)
            else:
                new_row = pd.DataFrame([[105.0] * len(self.tickers)], index=[new_date], columns=self.tickers, dtype=np.float32)
            updated_tensors[name] = pd.concat([df_cur, new_row])

        orig_replace = os.replace
        replace_counter = 0

        def flaky_replace(src, dst):
            nonlocal replace_counter
            replace_counter += 1
            # Allow first 5 replacements to succeed, fail on the 6th!
            if replace_counter == 6:
                raise PermissionError("Simulated Windows disk lock or permission error during replace!")
            return orig_replace(src, dst)

        with patch("os.replace", side_effect=flaky_replace):
            with self.assertRaises(RuntimeError) as ctx:
                atomic_commit_tensors(updated_tensors=updated_tensors, tensor_files=self.tensor_files)
            self.assertIn("Atomic tensor commit aborted with clean rollback", str(ctx.exception))

        # Critical Rollback Assertions:
        # Every single one of the 12 files on disk MUST be in its pre-commit state (exactly 4 rows)!
        for name, p in self.tensor_files.items():
            self.assertTrue(p.exists(), f"File {p.name} missing after rollback!")
            df_disk = pd.read_parquet(p)
            self.assertEqual(len(df_disk), 4, f"File {p.name} has {len(df_disk)} rows instead of 4 after rollback!")
            self.assertEqual(df_disk.index[-1], pd.Timestamp("2026-01-06"))

        # Zero temporary staging files should remain
        tmps = list(self.test_dir.glob("*.tmp.parquet"))
        self.assertEqual(len(tmps), 0)

    def test_rollback_cleans_up_newly_created_files(self):
        """Verifies that rollback unlinks any files that did not exist on disk prior to the commit attempt."""
        new_tensor_name = "series_extra"
        new_file = self.test_dir / f"{new_tensor_name}.parquet"
        self.assertFalse(new_file.exists())

        tensor_files = dict(self.tensor_files)
        tensor_files[new_tensor_name] = new_file

        new_date = pd.Timestamp("2026-01-07")
        updated_tensors = {}
        for name in config.TENSOR_NAMES:
            df_cur = self.base_tensors[name]
            if name in ("series", "isin"):
                new_row = pd.DataFrame([["EQ"] * len(self.tickers)], index=[new_date], columns=self.tickers)
            else:
                new_row = pd.DataFrame([[105.0] * len(self.tickers)], index=[new_date], columns=self.tickers, dtype=np.float32)
        full_index = list(self.base_tensors["close"].index) + [new_date]
        updated_tensors[new_tensor_name] = pd.DataFrame([["EQ"] * len(self.tickers)] * len(full_index), index=full_index, columns=self.tickers)

        orig_replace = os.replace
        def flaky_replace(src, dst):
            if new_file.name in str(dst):
                # Allow new_file to be swapped, then fail
                return orig_replace(src, dst)
            if "close" in str(dst):
                raise PermissionError("Disk failure during replace!")
            return orig_replace(src, dst)

        with patch("config.TENSOR_NAMES", list(config.TENSOR_NAMES) + [new_tensor_name]):
            with patch("os.replace", side_effect=flaky_replace):
                with self.assertRaises(RuntimeError):
                    atomic_commit_tensors(updated_tensors=updated_tensors, tensor_files=tensor_files)

        # Confirm newly created file was cleaned up and not left dangling on disk
        self.assertFalse(new_file.exists())

    def test_calendar_cache_invalidation_on_commit(self):
        """Verifies that invalidate_calendar_cache resets module caches cleanly."""
        from exchange_calendar import get_canonical_tensor_dates
        import exchange_calendar as ec

        # Populate cache
        dates = get_canonical_tensor_dates()
        self.assertIsNotNone(ec._CANONICAL_DATES_CACHE)

        # Invalidate
        invalidate_calendar_cache()
        self.assertIsNone(ec._CANONICAL_DATES_CACHE)
        self.assertIsNone(ec._HOLIDAYS_CACHE)
        self.assertIsNone(ec._HOLIDAY_DATES_CACHE)

    def test_daily_updater_network_dropout_resilience(self):
        """
        Verifies that update_universe_daily handles network connection dropouts or empty
        bhavcopy stream downloads gracefully without crashing or contaminating canonical tensors.
        """
        import requests
        from update_universe_daily import update_universe_daily

        with patch("update_universe_daily.sync_official_indices"):
            with patch("update_universe_daily.get_candidate_sessions", return_value=[date(2026, 11, 12)]):
                with patch("update_universe_daily.is_trading_day", return_value=True):
                    with patch("update_universe_daily.fetch_nse_bhavcopy_stream", side_effect=requests.exceptions.ConnectionError("Simulated network dropout")):
                        # Should complete cleanly without exception
                        res = update_universe_daily(target_date="2026-11-12", force_validation=False)
                        self.assertTrue(res)

        # Confirm canonical tensors still exist and row count is unchanged (5,665 sessions)
        c_df = pd.read_parquet(config.TENSOR_FILES["close"])
        self.assertEqual(len(c_df), 5665)


if __name__ == "__main__":
    unittest.main()
