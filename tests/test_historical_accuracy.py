"""
Institutional Automated Regression Test Suite for Historical Accuracy & Point-in-Time Integrity.

Verifies the 5 non-negotiable historical validation requirements of Phase 5:
1. Historical index entries/exits (Satyam exit on 2009-01-09/12, Axis Bank hiatus in Nifty Bank, Yes Bank exit, Suzlon exit).
2. Zero look-ahead bias on newly listed IPO winners (e.g., Eternal, Jio Financial).
3. Proper delisting handling (DHFL zero trades post-June 2021).
4. Exact split adjustments across historical dates (Cipla 1:5, 360ONE 1:2+1:1, Eicher Motors 1:10).
5. Clean snapshot retrieval across randomly sampled historical dates (GFC 2008, Election 2014, COVID 2020, Election 2024).
"""

import unittest
import numpy as np
import pandas as pd
import exchange_calendar as ec
import nseuniverse as nse
import nseuniverse_io as nio


class TestHistoricalAccuracy(unittest.TestCase):
    """Rigorous institutional verification of Point-in-Time universe and historical events."""

    @classmethod
    def setUpClass(cls):
        cls.sec_master = nse.get_security_master()
        cls.close_master = nio.load_tensor("close", universe="master", adjusted=False)
        cls.adj_close_master = nio.load_tensor("close", universe="master", adjusted=True)
        cls.ca_df = nse.get_corporate_actions()

    # =========================================================================
    # Requirement 1: Historical Index Entries and Exits
    # =========================================================================

    def test_satyam_collapse_and_exit(self):
        """
        Verify Satyam Computer Services (SATYAMCOMP.NS) exit in January 2009.
        Satyam was active through Friday 2009-01-09. Following the weekend emergency
        exclusion announcement, it was officially excluded on Monday 2009-01-12.
        """
        dt_in = "2009-01-09"
        dt_out = "2009-01-12"

        # Check in Nifty 50
        n50_before = nse.get_universe(dt_in, universe="nifty50", as_list=True)
        n50_after = nse.get_universe(dt_out, universe="nifty50", as_list=True)
        self.assertIn("SATYAMCOMP.NS", n50_before, f"SATYAMCOMP.NS must be in Nifty 50 on {dt_in}")
        self.assertNotIn("SATYAMCOMP.NS", n50_after, f"SATYAMCOMP.NS must NOT be in Nifty 50 on {dt_out}")

        # Check in Nifty IT
        nit_before = nse.get_universe(dt_in, universe="niftyit", as_list=True)
        nit_after = nse.get_universe(dt_out, universe="niftyit", as_list=True)
        self.assertIn("SATYAMCOMP.NS", nit_before, f"SATYAMCOMP.NS must be in Nifty IT on {dt_in}")
        self.assertNotIn("SATYAMCOMP.NS", nit_after, f"SATYAMCOMP.NS must NOT be in Nifty IT on {dt_out}")

    def test_axis_bank_nifty_bank_hiatus(self):
        """
        Verify Axis Bank (AXISBANK.NS) hiatus in Nifty Bank.
        Axis Bank was excluded from Nifty Bank between 2002-11-01 and 2006-03-15.
        It was officially re-included on 2006-03-16.
        """
        # During hiatus: must be False
        for dt in ["2004-01-01", "2005-06-01", "2006-03-14"]:
            bank_univ = nse.get_universe(dt, universe="niftybank", as_list=True)
            self.assertNotIn("AXISBANK.NS", bank_univ, f"AXISBANK.NS must NOT be in Nifty Bank on {dt} during hiatus")

        # Upon and after re-inclusion: must be True
        for dt in ["2006-03-16", "2006-03-20", "2024-01-05"]:
            bank_univ = nse.get_universe(dt, universe="niftybank", as_list=True)
            self.assertIn("AXISBANK.NS", bank_univ, f"AXISBANK.NS must be in Nifty Bank on {dt} post re-inclusion")

    def test_yes_bank_reconstitution_exit(self):
        """
        Verify Yes Bank (YESBANK.NS) exit in March 2020.
        Yes Bank was officially excluded from Nifty 50 and Nifty Bank on 2020-03-19.
        """
        dt_in = "2020-03-18"
        dt_out = "2020-03-19"

        # Nifty 50
        n50_before = nse.get_universe(dt_in, universe="nifty50", as_list=True)
        n50_after = nse.get_universe(dt_out, universe="nifty50", as_list=True)
        self.assertIn("YESBANK.NS", n50_before, f"YESBANK.NS must be in Nifty 50 on {dt_in}")
        self.assertNotIn("YESBANK.NS", n50_after, f"YESBANK.NS must NOT be in Nifty 50 on {dt_out}")

        # Nifty Bank
        nb_before = nse.get_universe(dt_in, universe="niftybank", as_list=True)
        nb_after = nse.get_universe(dt_out, universe="niftybank", as_list=True)
        self.assertIn("YESBANK.NS", nb_before, f"YESBANK.NS must be in Nifty Bank on {dt_in}")
        self.assertNotIn("YESBANK.NS", nb_after, f"YESBANK.NS must NOT be in Nifty Bank on {dt_out}")

    def test_suzlon_nifty_50_exit(self):
        """
        Verify Suzlon Energy (SUZLON.NS) exit from Nifty 50 in March 2011.
        Suzlon was active through 2011-03-24 and officially excluded on 2011-03-25.
        """
        dt_in = "2011-03-24"
        dt_out = "2011-03-25"

        n50_before = nse.get_universe(dt_in, universe="nifty50", as_list=True)
        n50_after = nse.get_universe(dt_out, universe="nifty50", as_list=True)
        self.assertIn("SUZLON.NS", n50_before, f"SUZLON.NS must be in Nifty 50 on {dt_in}")
        self.assertNotIn("SUZLON.NS", n50_after, f"SUZLON.NS must NOT be in Nifty 50 on {dt_out}")

    # =========================================================================
    # Requirement 2: Zero Look-Ahead Bias on Newly Listed IPO Winners
    # =========================================================================

    def test_zero_lookahead_eternal_zomato(self):
        """
        Verify zero look-ahead bias on Eternal / Zomato (ETERNAL.NS).
        First traded on 2021-07-23. Prior to this date, ETERNAL.NS must have:
        1. 100% natural NaNs in unadjusted close and volume tensors.
        2. Total absence from get_universe queries across broad market indices and master.
        3. Clean presence upon official Nifty 500 inclusion (2022-03-31).
        """
        # Pre-listing checks
        pre_dates = ["2020-01-06", "2021-01-04", "2021-07-22"]
        for dt in pre_dates:
            univ_500 = nse.get_universe(dt, universe="nifty500", as_list=True)
            self.assertNotIn("ETERNAL.NS", univ_500, f"ETERNAL.NS lookahead leak in Nifty 500 on {dt}")
            
            univ_master = nse.get_universe(dt, universe="master", as_list=True)
            self.assertNotIn("ETERNAL.NS", univ_master, f"ETERNAL.NS lookahead leak in master universe on {dt}")

        # Disk tensor check: strictly NaN prior to listing
        pre_close = self.close_master.loc[:"2021-07-22", "ETERNAL.NS"]
        self.assertTrue(pre_close.isna().all(), "ETERNAL.NS has non-NaN prices prior to listing date 2021-07-23!")

        # Post-inclusion check
        post_univ = nse.get_universe("2022-03-31", universe="nifty500", as_list=True)
        self.assertIn("ETERNAL.NS", post_univ, "ETERNAL.NS must be present in Nifty 500 on inclusion date 2022-03-31")

    def test_zero_lookahead_jio_financial(self):
        """
        Verify zero look-ahead bias on Jio Financial Services (JIOFIN.NS).
        First traded on 2023-08-21. Prior to this date, JIOFIN.NS must be absent
        from all indices and strictly NaN on disk.
        """
        pre_dates = ["2022-01-03", "2023-01-02", "2023-08-18"]
        for dt in pre_dates:
            univ_500 = nse.get_universe(dt, universe="nifty500", as_list=True)
            self.assertNotIn("JIOFIN.NS", univ_500, f"JIOFIN.NS lookahead leak in Nifty 500 on {dt}")

            univ_master = nse.get_universe(dt, universe="master", as_list=True)
            self.assertNotIn("JIOFIN.NS", univ_master, f"JIOFIN.NS lookahead leak in master on {dt}")

        pre_close = self.close_master.loc[:"2023-08-18", "JIOFIN.NS"]
        self.assertTrue(pre_close.isna().all(), "JIOFIN.NS has non-NaN prices prior to listing date 2023-08-21!")

        post_univ = nse.get_universe("2023-09-29", universe="nifty500", as_list=True)
        self.assertIn("JIOFIN.NS", post_univ, "JIOFIN.NS must be present in Nifty 500 on inclusion date 2023-09-29")

    # =========================================================================
    # Requirement 3: Proper Delisting Handling (DHFL Zero Trades Post-June 2021)
    # =========================================================================

    def test_dhfl_delisting_and_inactivity(self):
        """
        Verify authentic delisting handling for Dewan Housing Finance Corp (DHFL.NS).
        Last traded on 2021-06-11.
        1. is_active_currently must be False in security_master.
        2. Post-June 2021 (e.g. 2021-07-01 onwards), DHFL must have exactly 0 trades/volume (pure NaNs).
        3. get_universe for Nifty 500 in 2022 must exclude DHFL.
        4. get_universe for Nifty 500 in 2018 (when active) must include DHFL.
        """
        # Security Master
        self.assertFalse(
            bool(self.sec_master.loc["DHFL.NS", "is_active_currently"]),
            "DHFL.NS is_active_currently must be False"
        )
        self.assertEqual(
            str(self.sec_master.loc["DHFL.NS", "last_traded_date"]),
            "2021-06-11",
            "DHFL.NS last_traded_date must be 2021-06-11"
        )

        # Zero trades post-June 2021
        post_close = self.close_master.loc["2021-07-01":, "DHFL.NS"]
        self.assertEqual(post_close.notna().sum(), 0, "DHFL.NS has phantom traded prices post-June 2021!")

        # Universe membership
        univ_2018 = nse.get_universe("2018-01-01", universe="nifty500", as_list=True)
        self.assertIn("DHFL.NS", univ_2018, "DHFL.NS was an active Nifty 500 constituent in 2018!")

        univ_2022 = nse.get_universe("2022-01-03", universe="nifty500", as_list=True)
        self.assertNotIn("DHFL.NS", univ_2022, "DHFL.NS must NOT be in Nifty 500 in 2022 post-delisting!")

        univ_master_req = nse.get_universe("2022-01-03", universe="master", require_traded=True, as_list=True)
        self.assertNotIn("DHFL.NS", univ_master_req, "DHFL.NS must NOT be returned when require_traded=True in 2022!")

    # =========================================================================
    # Requirement 4: Exact Split & Bonus Adjustments Across Historical Dates
    # =========================================================================

    def test_cipla_split_5_to_1(self):
        """
        Verify Cipla (CIPLA.NS) 1:5 stock split on 2004-05-12 (face value Rs 10 to Rs 2).
        Unadjusted close drops ~80% (1,274.55 to 260.95).
        Adjusted close must have smooth continuous return (-5% to +5%).
        """
        raw_close = self.close_master["CIPLA.NS"]
        adj_close = self.adj_close_master["CIPLA.NS"]

        p_pre_raw = raw_close.loc["2004-05-11"]
        p_post_raw = raw_close.loc["2004-05-12"]
        raw_ratio = p_pre_raw / p_post_raw
        self.assertAlmostEqual(raw_ratio, 5.0, delta=0.25, msg="Cipla raw price drop must reflect 1:5 split")

        p_pre_adj = adj_close.loc["2004-05-11"]
        p_post_adj = adj_close.loc["2004-05-12"]
        adj_ret = (p_post_adj - p_pre_adj) / p_pre_adj
        self.assertGreater(adj_ret, -0.05, "Cipla adjusted return shows excessive drop across split date")
        self.assertLess(adj_ret, 0.05, "Cipla adjusted return shows excessive surge across split date")

        # Verify get_universe snapshot returns exact adjusted_close
        snap_pre = nse.get_universe("2004-05-11", universe="master", fields=["close", "adjusted_close"])
        snap_post = nse.get_universe("2004-05-12", universe="master", fields=["close", "adjusted_close"])
        snap_ret = (snap_post.loc["CIPLA.NS", "adjusted_close"] - snap_pre.loc["CIPLA.NS", "adjusted_close"]) / snap_pre.loc["CIPLA.NS", "adjusted_close"]
        self.assertGreater(snap_ret, -0.05)
        self.assertLess(snap_ret, 0.05)

    def test_360one_bonus_and_split_combined(self):
        """
        Verify 360 ONE WAM (360ONE.NS) on 2023-03-02.
        Underwent simultaneous 1:2 face value split (Rs 2 to Re 1) and 1:1 bonus,
        yielding combined multiplier of 4.0.
        Unadjusted close drops ~75% (1,773.30 to 441.05).
        Adjusted close must have smooth return (~-0.51%).
        """
        raw_close = self.close_master["360ONE.NS"]
        adj_close = self.adj_close_master["360ONE.NS"]

        p_pre_raw = raw_close.loc["2023-03-01"]
        p_post_raw = raw_close.loc["2023-03-02"]
        raw_ratio = p_pre_raw / p_post_raw
        self.assertAlmostEqual(raw_ratio, 4.0, delta=0.2, msg="360ONE raw price drop must reflect 4.0x combined multiplier")

        p_pre_adj = adj_close.loc["2023-03-01"]
        p_post_adj = adj_close.loc["2023-03-02"]
        adj_ret = (p_post_adj - p_pre_adj) / p_pre_adj
        self.assertGreater(adj_ret, -0.05, "360ONE adjusted return shows discontinuity on corporate action date")
        self.assertLess(adj_ret, 0.05, "360ONE adjusted return shows discontinuity on corporate action date")

        # Verify get_universe snapshot returns exact adjusted_close
        snap_pre = nse.get_universe("2023-03-01", universe="master", fields=["close", "adjusted_close"])
        snap_post = nse.get_universe("2023-03-02", universe="master", fields=["close", "adjusted_close"])
        snap_ret = (snap_post.loc["360ONE.NS", "adjusted_close"] - snap_pre.loc["360ONE.NS", "adjusted_close"]) / snap_pre.loc["360ONE.NS", "adjusted_close"]
        self.assertGreater(snap_ret, -0.05)
        self.assertLess(snap_ret, 0.05)

    def test_eicher_motors_split_10_to_1(self):
        """
        Verify Eicher Motors (EICHERMOT.NS) 1:10 stock split on 2020-08-24.
        Unadjusted close drops ~90% (21,720 to 2,175).
        Adjusted close must have smooth return (-5% to +5%).
        """
        raw_close = self.close_master["EICHERMOT.NS"]
        adj_close = self.adj_close_master["EICHERMOT.NS"]

        p_pre_raw = raw_close.loc["2020-08-21"]
        p_post_raw = raw_close.loc["2020-08-24"]
        raw_ratio = p_pre_raw / p_post_raw
        self.assertAlmostEqual(raw_ratio, 10.0, delta=0.5, msg="Eicher Motors raw price drop must reflect 10:1 split")

        p_pre_adj = adj_close.loc["2020-08-21"]
        p_post_adj = adj_close.loc["2020-08-24"]
        adj_ret = (p_post_adj - p_pre_adj) / p_pre_adj
        self.assertGreater(adj_ret, -0.05, "Eicher Motors adjusted return shows discontinuity across 10:1 split")
        self.assertLess(adj_ret, 0.05, "Eicher Motors adjusted return shows discontinuity across 10:1 split")

        # Verify get_universe snapshot returns exact adjusted_close
        snap_pre = nse.get_universe("2020-08-21", universe="master", fields=["close", "adjusted_close"])
        snap_post = nse.get_universe("2020-08-24", universe="master", fields=["close", "adjusted_close"])
        snap_ret = (snap_post.loc["EICHERMOT.NS", "adjusted_close"] - snap_pre.loc["EICHERMOT.NS", "adjusted_close"]) / snap_pre.loc["EICHERMOT.NS", "adjusted_close"]
        self.assertGreater(snap_ret, -0.05)
        self.assertLess(snap_ret, 0.05)

    # =========================================================================
    # Requirement 5: Clean Snapshot Retrieval Across Random Sampled Dates
    # =========================================================================

    def test_get_universe_snapshot_sampled_dates(self):
        """
        Verify get_universe across critical historical market regimes:
        1. 2008-10-24 (Global Financial Crisis crash)
        2. 2014-05-16 (General Election 2014 results)
        3. 2020-03-23 (COVID Circuit Breaker plunge)
        4. 2024-06-04 (General Election 2024 results)
        5. 2026-01-15 (Recent historical regime)
        """
        sample_dates = [
            "2008-10-24",
            "2014-05-16",
            "2020-03-23",
            "2024-06-04",
            "2026-01-15",
        ]

        expected_cols = [
            "sec_id", "symbol", "company_name", "asset_class", "sector", "series", "isin",
            "listing_date", "close", "adjusted_close", "open", "high", "low", "volume",
            "turnover", "vwap", "trades", "prevclose", "return_1d", "adtv"
        ]

        for dt in sample_dates:
            # Query Nifty 50 snapshot
            df_n50 = nse.get_universe(dt, universe="nifty50")
            self.assertEqual(len(df_n50), 50, f"Nifty 50 on {dt} must contain exactly 50 constituents, got {len(df_n50)}")
            self.assertEqual(df_n50.index.name, "ticker")

            # Verify schema columns
            for col in expected_cols:
                self.assertIn(col, df_n50.columns, f"Column '{col}' missing from get_universe snapshot on {dt}")

            # Verify OHLCV geometric invariants on valid rows
            valid = df_n50.dropna(subset=["open", "high", "low", "close"])
            self.assertGreater(len(valid), 45, f"Too many untraded stocks in Nifty 50 on {dt}")

            self.assertTrue(
                (valid["high"] >= valid["low"] - 1e-4).all(),
                f"High < Low violation in snapshot on {dt}"
            )
            self.assertTrue(
                (valid["high"] >= valid["open"] - 1e-4).all(),
                f"High < Open violation in snapshot on {dt}"
            )
            self.assertTrue(
                (valid["high"] >= valid["close"] - 1e-4).all(),
                f"High < Close violation in snapshot on {dt}"
            )
            self.assertTrue(
                (valid["low"] <= valid["open"] + 1e-4).all(),
                f"Low > Open violation in snapshot on {dt}"
            )
            self.assertTrue(
                (valid["low"] <= valid["close"] + 1e-4).all(),
                f"Low > Close violation in snapshot on {dt}"
            )

            # ADTV must be strictly positive for active stalwarts
            self.assertTrue((valid["adtv"] > 0).all(), f"ADTV must be strictly positive on {dt}")

            # Verify as_list parity
            list_n50 = nse.get_universe(dt, universe="nifty50", as_list=True)
            self.assertEqual(list(df_n50.index), list_n50, f"as_list=True mismatch on {dt}")

    def test_get_universe_weekend_and_holiday_resolution(self):
        """Verify that get_universe on weekends or holidays resolves to the latest preceding trading session."""
        # Saturday 2024-01-06 -> should resolve cleanly to Friday 2024-01-05
        df_sat = nse.get_universe("2024-01-06", universe="nifty50")
        self.assertEqual(df_sat.attrs["effective_date"], "2024-01-05")
        self.assertEqual(len(df_sat), 50)

        # Sunday 2024-01-07 -> should also resolve to Friday 2024-01-05
        df_sun = nse.get_universe("2024-01-07", universe="nifty50")
        self.assertEqual(df_sun.attrs["effective_date"], "2024-01-05")
        self.assertEqual(len(df_sun), 50)

    def test_get_universe_liquidity_and_price_corridors(self):
        """Verify min_adtv, min_price, and max_price filters."""
        dt = "2024-01-05"

        # Baseline count
        all_n500 = nse.get_universe(dt, universe="nifty500", as_list=True)
        self.assertEqual(len(all_n500), 500)

        # High liquidity filter: min_adtv = 100M (₹10 Cr)
        liquid_n500 = nse.get_universe(dt, universe="nifty500", min_adtv=100_000_000, as_list=True)
        self.assertGreater(len(liquid_n500), 100)
        self.assertLess(len(liquid_n500), len(all_n500))

        # Price corridor: ₹100 to ₹5,000
        corridor = nse.get_universe(dt, universe="nifty500", min_price=100.0, max_price=5000.0)
        self.assertTrue((corridor["close"] >= 100.0).all())
        self.assertTrue((corridor["close"] <= 5000.0).all())

    def test_get_universe_boundary_and_error_handling(self):
        """Verify boundary validations and error raising."""
        # Date earlier than dataset start
        with self.assertRaises(ValueError):
            nse.get_universe("1990-01-01", universe="nifty50")

        # Future date
        with self.assertRaises(ValueError):
            nse.get_universe("2030-01-01", universe="nifty50")

        # Unknown universe
        with self.assertRaises(ValueError):
            nse.get_universe("2024-01-05", universe="nonexistent_universe_123")

    def test_get_universe_timestamp_robustness(self):
        """Verify handling of timestamps with time, timezone, and datetime.date."""
        # Intraday timestamp
        df_time = nse.get_universe("2024-01-05 15:30:00", universe="nifty50")
        self.assertEqual(df_time.attrs["effective_date"], "2024-01-05")
        self.assertEqual(len(df_time), 50)

        # Timezone-aware timestamp
        ts_tz = pd.Timestamp("2024-01-05", tz="Asia/Kolkata")
        df_tz = nse.get_universe(ts_tz, universe="nifty50")
        self.assertEqual(df_tz.attrs["effective_date"], "2024-01-05")
        self.assertEqual(len(df_tz), 50)

        # Datetime.date object
        import datetime
        d_obj = datetime.date(2024, 1, 5)
        df_date = nse.get_universe(d_obj, universe="nifty50")
        self.assertEqual(df_date.attrs["effective_date"], "2024-01-05")
        self.assertEqual(len(df_date), 50)

        # Latest session with intraday timestamp
        df_latest = nse.get_universe("2026-11-09 15:30:00", universe="nifty50")
        self.assertEqual(df_latest.attrs["effective_date"], "2026-11-09")
        self.assertEqual(len(df_latest), 50)

    def test_get_universe_horizon_holiday_resolution(self):
        """Verify holiday on data horizon resolves cleanly to the latest trading session."""
        # 2026-11-10 is official Diwali-Balipratipada holiday immediately following 2026-11-09
        df_hol = nse.get_universe("2026-11-10", universe="nifty50")
        self.assertEqual(df_hol.attrs["effective_date"], "2026-11-09")
        self.assertEqual(len(df_hol), 50)

        # Querying beyond the canonical dataset horizon (next trading day not yet ingested) must raise ValueError
        canonical_dates = nse.get_canonical_dates()
        next_uncommitted = ec.get_next_trading_day(canonical_dates[-1])
        with self.assertRaises(ValueError):
            nse.get_universe(next_uncommitted, universe="nifty50")

    def test_get_universe_universe_name_variants(self):
        """Verify universe name normalization across formats (casing, spaces, hyphens, underscores)."""
        variants = ["Nifty 50", "nifty-50", "NIFTY_BANK", "nifty bank", "Total Market", "Nifty IT", "Master"]
        for u in variants:
            lst = nse.get_universe("2024-01-05", universe=u, as_list=True)
            self.assertGreater(len(lst), 0, f"Variant '{u}' returned empty constituent list")

    def test_get_universe_fields_selection_and_validation(self):
        """Verify custom fields subsetting and strict validation."""
        # Exact requested subset of columns
        df_custom = nse.get_universe("2024-01-05", universe="nifty50", fields=["symbol", "close", "volume"])
        self.assertEqual(list(df_custom.columns), ["symbol", "close", "volume"])
        self.assertEqual(len(df_custom), 50)

        # Custom metrics with adjusted close and 1d return
        df_metrics = nse.get_universe("2024-01-05", universe="nifty50", fields=["sec_id", "adjusted_close", "return_1d"])
        self.assertEqual(list(df_metrics.columns), ["sec_id", "adjusted_close", "return_1d"])
        self.assertFalse(df_metrics["adjusted_close"].isna().all())

        # Invalid field name raises ValueError
        with self.assertRaises(ValueError):
            nse.get_universe("2024-01-05", universe="nifty50", fields=["close", "nonexistent_field_xyz"])

        # Float adtv_window works seamlessly
        df_float_w = nse.get_universe("2024-01-05", universe="nifty50", min_adtv=1e6, adtv_window=20.0)
        self.assertEqual(len(df_float_w), 50)

        # min_price > max_price raises ValueError
        with self.assertRaises(ValueError):
            nse.get_universe("2024-01-05", universe="nifty50", min_price=500.0, max_price=100.0)

    def test_get_universe_require_traded_and_empty_result(self):
        """Verify require_traded filtering and graceful empty DataFrame structure."""
        # 2020-03-23 had 1 untraded constituent in Nifty 500
        u_all = nse.get_universe("2020-03-23", universe="nifty500", require_traded=False, as_list=True)
        u_trd = nse.get_universe("2020-03-23", universe="nifty500", require_traded=True, as_list=True)
        self.assertGreater(len(u_all), len(u_trd))

        # Impossible filter -> empty DataFrame
        empty_df = nse.get_universe("2024-01-05", universe="nifty50", min_adtv=1e15)
        self.assertEqual(len(empty_df), 0)
        self.assertEqual(empty_df.attrs["as_of_date"], "2024-01-05")
        self.assertEqual(empty_df.attrs["effective_date"], "2024-01-05")
        self.assertEqual(empty_df.attrs["universe"], "nifty50")
        self.assertIn("close", empty_df.columns)


if __name__ == "__main__":
    unittest.main()
