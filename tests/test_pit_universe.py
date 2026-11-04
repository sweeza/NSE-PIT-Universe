"""
Unit and integration tests for Point-in-Time (PIT) Index Universes,
Strict Subset Hierarchy Invariants, Listing Gatekeeper, and Dynamic Tradable Mask.
"""

import unittest
import pandas as pd
import numpy as np
import config
import nseuniverse as nse
import nseuniverse_io as nio


class TestPointInTimeUniverse(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.close_df = pd.read_parquet(config.TENSOR_FILES["close"])
        cls.has_traded = cls.close_df.notna().cummax(axis=0)

        # Load broad market masks
        cls.n50 = pd.read_parquet(config.PIT_INDEX_FILES["nifty50"])
        cls.nn50 = pd.read_parquet(config.PIT_INDEX_FILES["niftynext50"])
        cls.n100 = pd.read_parquet(config.PIT_INDEX_FILES["nifty100"])
        cls.n200 = pd.read_parquet(config.PIT_INDEX_FILES["nifty200"])
        cls.lm250 = pd.read_parquet(config.PIT_INDEX_FILES["largemid250"])
        cls.m150 = pd.read_parquet(config.PIT_INDEX_FILES["midcap150"])
        cls.s250 = pd.read_parquet(config.PIT_INDEX_FILES["smallcap250"])
        cls.ms400 = pd.read_parquet(config.PIT_INDEX_FILES["midsmall400"])
        cls.n500 = pd.read_parquet(config.PIT_INDEX_FILES["nifty500"])
        cls.tm = pd.read_parquet(config.PIT_INDEX_FILES["totalmarket"])

    def test_strict_subset_hierarchy_all_sessions(self):
        """Assert all 8 subset hierarchy invariants have EXACTLY 0 daily violations across all 5,659 sessions."""
        # 1. Nifty 50 ⊆ Nifty 100
        viol_50_100 = (self.n50 & ~self.n100).sum().sum()
        self.assertEqual(viol_50_100, 0, f"Violations where Nifty 50 not in Nifty 100: {viol_50_100}")

        # 2. Nifty 100 ⊆ Nifty 200
        viol_100_200 = (self.n100 & ~self.n200).sum().sum()
        self.assertEqual(viol_100_200, 0, f"Violations where Nifty 100 not in Nifty 200: {viol_100_200}")

        # 3. Nifty 200 ⊆ Nifty 500
        viol_200_500 = (self.n200 & ~self.n500).sum().sum()
        self.assertEqual(viol_200_500, 0, f"Violations where Nifty 200 not in Nifty 500: {viol_200_500}")

        # 4. Nifty 100 | Midcap 150 == LargeMidcap 250
        diff_lm250 = ((self.n100 | self.m150) != self.lm250).sum().sum()
        self.assertEqual(diff_lm250, 0, f"Violations in N100 | M150 == LM250: {diff_lm250}")

        # 5. Midcap 150 | Smallcap 250 == MidSmallcap 400
        diff_ms400 = ((self.m150 | self.s250) != self.ms400).sum().sum()
        self.assertEqual(diff_ms400, 0, f"Violations in M150 | S250 == MS400: {diff_ms400}")

        # 6. Nifty 100 == Nifty 500 & ~MidSmallcap 400
        diff_n100 = ((self.n500 & ~self.ms400) != self.n100).sum().sum()
        self.assertEqual(diff_n100, 0, f"Violations in N500 & ~MS400 == N100: {diff_n100}")

        # 7. Nifty 50 | Nifty Next 50 == Nifty 100
        diff_n100_sum = ((self.n50 | self.nn50) != self.n100).sum().sum()
        self.assertEqual(diff_n100_sum, 0, f"Violations in N50 | NN50 == N100: {diff_n100_sum}")

        # 8. Nifty 500 ⊆ Total Market
        viol_n500_tm = (self.n500 & ~self.tm).sum().sum()
        self.assertEqual(viol_n500_tm, 0, f"Violations where N500 not in Total Market: {viol_n500_tm}")

    def test_zero_listing_lookahead_gatekeeper(self):
        """Assert zero lookahead listing leaks across all 23 PIT index masks."""
        for idx_name, fpath in config.PIT_INDEX_FILES.items():
            mask = pd.read_parquet(fpath)
            leaks = (mask & ~self.has_traded).sum().sum()
            self.assertEqual(leaks, 0, f"Lookahead listing leaks in {idx_name}: {leaks}")

    def test_future_ipo_winners_not_backfilled(self):
        """Spot-check that 2021+ IPOs (Zomato, Jio Financial) are strictly False on historical dates."""
        check_date = "2010-01-04"
        for idx_name in ["nifty50", "nifty100", "nifty200", "nifty500", "niftyfinance"]:
            mask = pd.read_parquet(config.PIT_INDEX_FILES[idx_name])
            if "ETERNAL.NS" in mask.columns and check_date in mask.index:
                self.assertFalse(mask.loc[check_date, "ETERNAL.NS"], f"ETERNAL.NS marked True on {check_date} in {idx_name}!")
            if "JIOFIN.NS" in mask.columns and check_date in mask.index:
                self.assertFalse(mask.loc[check_date, "JIOFIN.NS"], f"JIOFIN.NS marked True on {check_date} in {idx_name}!")

    def test_historical_constituent_bounds_all_years(self):
        """Assert that constituent counts are within institutional bounds for every year 2004-2026."""
        bounds = [
            ("nifty50", 45, 55),
            ("nifty100", 90, 105),
            ("nifty200", 190, 210),
            ("largemid250", 240, 255),
            ("midcap150", 140, 155),
            ("midsmall400", 340, 410),
            ("nifty500", 440, 510),
            ("totalmarket", 650, 760),
            ("niftybank", 10, 16),
            ("niftyit", 8, 12),
        ]
        for idx_name, min_c, max_c in bounds:
            mask = pd.read_parquet(config.PIT_INDEX_FILES[idx_name])
            daily_c = mask.sum(axis=1)
            for yr, grp in daily_c.groupby(daily_c.index.year):
                yr_med = grp.median()
                self.assertGreaterEqual(yr_med, min_c, f"{idx_name} year {yr} underflow: median={yr_med}")
                self.assertLessEqual(yr_med, max_c, f"{idx_name} year {yr} overflow: median={yr_med}")

    def test_dynamic_tradable_universe_mask(self):
        """Assert get_tradable_mask behaves correctly with liquidity and price floors."""
        # 1. Test via nseuniverse
        tradable_500 = nse.get_tradable_mask(
            universe="nifty500",
            min_adtv=20_000_000.0,
            min_price=20.0,
            start="2024-01-01",
            end="2024-01-10",
        )
        self.assertIsInstance(tradable_500, pd.DataFrame)
        self.assertEqual(len(tradable_500), 8)
        # All tradable stocks must be valid active constituents in N500
        n500_sub = self.n500.loc["2024-01-01":"2024-01-10", tradable_500.columns]
        viol = (tradable_500 & ~n500_sub).sum().sum()
        self.assertEqual(viol, 0, f"Tradable stocks not in N500: {viol}")

        # Active daily count should be institutional (> 300 stocks meeting ₹2 Cr ADTV)
        self.assertGreater(tradable_500.iloc[0].sum(), 300)

        # 2. Test via nseuniverse_io
        tradable_ms400 = nio.get_tradable_mask(
            universe="midsmall400",
            min_adtv=20_000_000.0,
            min_price=20.0,
            start="2024-01-01",
            end="2024-01-10",
        )
        self.assertIsInstance(tradable_ms400, pd.DataFrame)
        ms400_sub = self.ms400.loc["2024-01-01":"2024-01-10", tradable_ms400.columns]
        viol_ms = (tradable_ms400 & ~ms400_sub).sum().sum()
        self.assertEqual(viol_ms, 0, f"Tradable stocks not in MS400: {viol_ms}")
        self.assertGreater(tradable_ms400.iloc[0].sum(), 250)

    def test_symbol_alias_resolution(self):
        """Assert historical symbols properly resolve to canonical tickers."""
        test_pairs = [
            ("CADILAHC", "ZYDUSLIFE.NS"),
            ("MOTHERSUMI", "MOTHERSON.NS"),
            ("IIFLWAM", "360ONE.NS"),
            ("LTI", "LTM.NS"),
            ("BIRLASOFT", "BSOFT.NS"),
        ]
        for old_sym, exp_ticker in test_pairs:
            # Test nio.resolve_ticker
            res_nio = nio.resolve_ticker(old_sym)
            self.assertEqual(res_nio, exp_ticker)

            # Test nse.Ticker
            t = nse.Ticker(old_sym)
            self.assertEqual(t.ticker, exp_ticker)

    def test_nifty50_constituent_authenticity_and_underflow_prevention(self):
        """Assert genuine blue chips are present and speculative small-caps are excluded from Nifty 50."""
        dt = "2024-01-01"
        self.assertIn(dt, self.n50.index)
        row = self.n50.loc[dt]
        self.assertEqual(row.sum(), 50, f"Nifty 50 count on {dt} must be exactly 50, got {row.sum()}")

        # Genuine incumbents must be True
        for sym in ["ADANIENT.NS", "NESTLEIND.NS", "BRITANNIA.NS", "ULTRACEMCO.NS", "RELIANCE.NS", "TCS.NS", "INFY.NS"]:
            self.assertTrue(row[sym], f"Expected blue-chip stalwart {sym} to be present in Nifty 50 on {dt}")

        # Speculative / future IPO winners must be False
        for sym in ["MAZDOCK.NS", "SUZLON.NS", "COCHINSHIP.NS", "ETERNAL.NS", "JIOFIN.NS", "BSE.NS"]:
            self.assertFalse(row[sym], f"Speculative/future scrip {sym} must NOT be present in Nifty 50 on {dt}")

    def test_zero_entrant_latency(self):
        """Assert newly added index constituents are immediately tradable on inclusion day."""
        # 360ONE.NS was added to Nifty 500 on 2020-06-26
        dt = "2020-06-26"
        tradable = nio.get_tradable_mask(
            universe="nifty500",
            min_adtv=20_000_000.0,
            start=dt,
            end=dt,
        )
        self.assertTrue(
            tradable.loc[dt, "360ONE.NS"],
            f"360ONE.NS must be immediately tradable on {dt} without cold-start rolling window latency!"
        )

    def test_tradable_mask_edge_cases(self):
        """Assert get_tradable_mask handles extreme and boundary parameters robustly."""
        # Edge Case 1: min_adtv=0, min_price=None, max_price=None (should match full universe mask)
        mask_all = nio.get_tradable_mask(
            universe="nifty50",
            min_adtv=0.0,
            min_price=None,
            max_price=None,
            start="2024-01-01",
            end="2024-01-05",
        )
        self.assertEqual(mask_all.shape[0], 5)
        # Should have exactly 50 active stocks
        self.assertEqual(mask_all.iloc[0].sum(), 50)

        # Edge Case 2: Single-session date window
        single_day = nio.get_tradable_mask(
            universe="nifty100",
            start="2023-01-02",
            end="2023-01-02",
        )
        self.assertEqual(len(single_day), 1)
        self.assertGreater(single_day.iloc[0].sum(), 80)

        # Edge Case 3: Custom sector filtering with sector="Information Technology"
        tradable_it = nio.get_tradable_mask(
            universe="nifty500",
            sector="Information Technology",
            start="2024-01-01",
            end="2024-01-05",
        )
        self.assertFalse(tradable_it.empty)
        # Verify IT constituents like TCS and INFY are present
        self.assertTrue(tradable_it.loc["2024-01-01", "TCS.NS"])
        self.assertTrue(tradable_it.loc["2024-01-01", "INFY.NS"])
        # Verify non-IT constituents like RELIANCE are NOT present
        self.assertNotIn("RELIANCE.NS", tradable_it.columns)


if __name__ == "__main__":
    unittest.main()
