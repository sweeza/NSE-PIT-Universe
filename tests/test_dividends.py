"""
Unit and integration tests for Phase 3: Comprehensive Corporate Actions Ledger (Dividends & TRI).
"""

import unittest
import numpy as np
import pandas as pd
import config
import nseuniverse_io as nio
import nseuniverse as nse


class TestDividendsAndTotalReturns(unittest.TestCase):

    def setUp(self):
        self.div_df = nio.get_dividends()

    def test_dividend_ledger_schema_and_invariants(self):
        """Verify dividends.parquet exists, is fully populated, and has zero nulls across critical fields."""
        self.assertFalse(self.div_df.empty, "Dividends DataFrame should not be empty")
        self.assertGreater(len(self.div_df), 20_000, "Should have >20,000 historical dividend records")

        expected_cols = [
            "symbol", "ticker", "company_name", "isin", "series", "ex_date", "ex_date_dt",
            "amount", "regular_amount", "special_amount", "dividend_type",
            "is_interim", "is_final", "is_special", "face_value", "subject"
        ]
        for col in expected_cols:
            self.assertIn(col, self.div_df.columns)
            self.assertEqual(
                self.div_df[col].isna().sum(), 0,
                f"Column '{col}' must have zero null values"
            )

        # Invariant: amount == regular_amount + special_amount
        diff = (self.div_df["amount"] - (self.div_df["regular_amount"] + self.div_df["special_amount"])).abs()
        self.assertTrue((diff < 1e-4).all(), "Every dividend record must satisfy amount == regular + special")

        # Invariant: all amounts > 0
        self.assertTrue((self.div_df["amount"] > 0).all(), "Every dividend amount must be strictly positive")

        # Invariant: historical coverage spans Era 1 (1995) to present (2026)
        min_yr = self.div_df["ex_date_dt"].min().year
        max_yr = self.div_df["ex_date_dt"].max().year
        self.assertLessEqual(min_yr, 1995)
        self.assertGreaterEqual(max_yr, 2026)

    def test_ticker_dividends_property(self):
        """Verify Ticker.dividends returns a rich pandas Series of dividend amounts indexed by ex-date."""
        tcs = nse.Ticker("TCS")
        tcs_div = tcs.dividends
        self.assertIsInstance(tcs_div, pd.Series)
        self.assertFalse(tcs_div.empty)
        self.assertGreater(len(tcs_div), 50, "TCS should have >50 dividend payments")
        self.assertGreater(tcs_div.sum(), 500.0, "TCS cumulative cash dividends should exceed Rs 500")

        # Spot-check specific TCS special dividend (e.g. 2010 or 2026)
        special_divs = self.div_df[(self.div_df["ticker"] == "TCS.NS") & (self.div_df["is_special"])]
        self.assertFalse(special_divs.empty, "TCS should have special dividend records")

        # Inactive/delisted ticker check
        patni = nse.Ticker("PATNI")
        patni_div = patni.dividends
        self.assertFalse(patni_div.empty, "Delisted ticker Patni should retain historical dividend records")

    def test_ticker_actions_combined(self):
        """Verify Ticker.actions returns full corporate actions (splits, bonuses, dividends)."""
        rel = nse.Ticker("RELIANCE")
        actions = rel.actions
        self.assertIn("action_type", actions.columns)
        self.assertIn("multiplier", actions.columns)
        self.assertIn("amount", actions.columns)

        # Bonuses property remains backward-compatible
        bonuses = rel.bonuses
        self.assertIn(pd.to_datetime("2017-09-07"), bonuses.index)
        self.assertEqual(bonuses.loc["2017-09-07"], 2.0)

        # Dividends present in actions
        div_actions = actions[actions["action_type"].str.contains("DIVIDEND", na=False)]
        self.assertFalse(div_actions.empty)

    def test_total_return_series_computation(self):
        """Verify Total Return Index compounds reinvested dividends and strictly outperforms price return."""
        infy_adj_close = nio.load_tensor("close", universe="nifty50", adjusted=True)["INFY.NS"].dropna()
        infy_tri = nio.compute_total_return_series(infy_adj_close, "INFY.NS").dropna()

        # Initial parity: TRI starts at initial split-adjusted price
        self.assertAlmostEqual(infy_tri.iloc[0], infy_adj_close.iloc[0], places=2)

        # Terminal superiority: Due to >Rs 700 dividends, terminal TRI must be significantly higher
        terminal_price = infy_adj_close.iloc[-1]
        terminal_tri = infy_tri.iloc[-1]
        self.assertGreater(terminal_tri, terminal_price * 1.3, "INFY TRI should exceed price by >30% due to dividends")

        # Spot check on ex-dividend return
        # On 2024-10-29, Infosys paid Rs 21 dividend
        if "2024-10-28" in infy_adj_close.index and "2024-10-29" in infy_adj_close.index:
            p_ret = infy_adj_close.loc["2024-10-28":"2024-10-29"].pct_change().iloc[-1]
            tri_ret = infy_tri.loc["2024-10-28":"2024-10-29"].pct_change().iloc[-1]
            # TRI return must strictly exceed price return on ex-dividend day
            self.assertGreater(tri_ret, p_ret)

    def test_ticker_history_tri_mode(self):
        """Verify Ticker.history(adjusted='tri') returns Total Return Index."""
        tcs = nse.Ticker("TCS")
        hist_adj = tcs.history(start="2020-01-01", end="2024-12-31", adjusted=True)
        hist_tri = tcs.history(start="2020-01-01", end="2024-12-31", adjusted="tri")

        self.assertIn("Tri", hist_tri.columns)
        self.assertAlmostEqual(hist_tri["Close"].iloc[0], hist_adj["Close"].iloc[0], places=1)
        self.assertGreater(hist_tri["Close"].iloc[-1], hist_adj["Close"].iloc[-1])

    def test_tensor_loading_tri_and_yield(self):
        """Verify load_tensor supports 'tri', 'dividends', and 'dividend_yield'."""
        tri_mat = nio.load_tensor("tri", universe="nifty50")
        adj_close = nio.load_tensor("close", universe="nifty50", adjusted=True)
        self.assertEqual(tri_mat.shape, adj_close.shape)

        div_mat = nio.load_tensor("dividends", universe="nifty50")
        self.assertEqual(div_mat.shape, adj_close.shape)
        # INFY must have positive dividend entries
        self.assertGreater(div_mat["INFY.NS"].sum(), 0)

        yield_mat = nio.load_tensor("dividend_yield", universe="nifty50")
        self.assertEqual(yield_mat.shape, adj_close.shape)
        # Yield should be in sensible economic bounds [0, 15%] for normal blue-chips
        infy_yield = yield_mat.loc["2024-01-02", "INFY.NS"]
        self.assertGreater(infy_yield, 0.01)
        self.assertLess(infy_yield, 0.05)

    def test_multicomponent_and_complex_announcements_accuracy(self):
        """Verify that multi-component, inclusive, and abbreviated dividend announcements are accurately parsed without dropouts or double counting."""
        # 1. TCS Multi-Component Announcements (Regular + Special on same day)
        tcs_2023 = self.div_df[(self.div_df["ticker"] == "TCS.NS") & (self.div_df["ex_date"] == "16-Jan-2023")].iloc[0]
        self.assertEqual(tcs_2023["amount"], 75.0)
        self.assertEqual(tcs_2023["regular_amount"], 8.0)
        self.assertEqual(tcs_2023["special_amount"], 67.0)

        tcs_2024 = self.div_df[(self.div_df["ticker"] == "TCS.NS") & (self.div_df["ex_date"] == "19-Jan-2024")].iloc[0]
        self.assertEqual(tcs_2024["amount"], 27.0)
        self.assertEqual(tcs_2024["regular_amount"], 9.0)
        self.assertEqual(tcs_2024["special_amount"], 18.0)

        tcs_2025 = self.div_df[(self.div_df["ticker"] == "TCS.NS") & (self.div_df["ex_date"] == "17-Jan-2025")].iloc[0]
        self.assertEqual(tcs_2025["amount"], 76.0)
        self.assertEqual(tcs_2025["regular_amount"], 10.0)
        self.assertEqual(tcs_2025["special_amount"], 66.0)

        # 2. ITC Centenary / Inclusive Special Dividend (Verify NO double counting)
        itc_2016 = self.div_df[(self.div_df["ticker"] == "ITC.NS") & (self.div_df["ex_date"] == "30-May-2016")].iloc[0]
        self.assertEqual(itc_2016["amount"], 8.5)
        self.assertEqual(itc_2016["regular_amount"], 6.5)
        self.assertEqual(itc_2016["special_amount"], 2.0)

        # 3. GSKCONS Parenthetical Breakdown (Verify NO doubling from 50 to 100)
        gsk_2011 = self.div_df[(self.div_df["ticker"] == "GSKCONS.NS") & (self.div_df["ex_date"] == "11-Mar-2011")].iloc[0]
        self.assertEqual(gsk_2011["amount"], 50.0)
        self.assertEqual(gsk_2011["regular_amount"], 25.0)
        self.assertEqual(gsk_2011["special_amount"], 25.0)

        # 4. Abbreviated Special Dividends (Spl- / Sp-)
        ap_2006 = self.div_df[(self.div_df["ticker"] == "ASIANPAINT.NS") & (self.div_df["ex_date"] == "15-Jun-2006")].iloc[0]
        self.assertEqual(ap_2006["amount"], 0.80)
        self.assertEqual(ap_2006["regular_amount"], 0.55)
        self.assertEqual(ap_2006["special_amount"], 0.25)

        ts_2007 = self.div_df[(self.div_df["ticker"] == "TATASTEEL.NS") & (self.div_df["ex_date"] == "08-Jun-2007")].iloc[0]
        self.assertEqual(ts_2007["amount"], 1.55)
        self.assertEqual(ts_2007["regular_amount"], 1.30)
        self.assertEqual(ts_2007["special_amount"], 0.25)

        eicher_2007 = self.div_df[(self.div_df["ticker"] == "EICHERMOT.NS") & (self.div_df["ex_date"] == "16-Mar-2007")].iloc[0]
        self.assertEqual(eicher_2007["amount"], 2.90)
        self.assertEqual(eicher_2007["regular_amount"], 0.40)
        self.assertEqual(eicher_2007["special_amount"], 2.50)

        # 5. Scrips with attached currency symbols (e.g. Rs13, Rs50, Rs1.2, Rs4.5)
        mon = self.div_df[(self.div_df["ticker"] == "MONSANTO.NS") & (self.div_df["ex_date"] == "12-Aug-2005")]
        self.assertFalse(mon.empty, "MONSANTO.NS dividend on 12-Aug-2005 should be recovered")
        self.assertEqual(mon.iloc[0]["amount"], 13.0)

        zan = self.div_df[(self.div_df["ticker"] == "ZANDUREALT.NS") & (self.div_df["ex_date"] == "04-Aug-2005")]
        self.assertFalse(zan.empty, "ZANDUREALT.NS dividend on 04-Aug-2005 should be recovered")
        self.assertEqual(zan.iloc[0]["amount"], 50.0)

        aeg = self.div_df[(self.div_df["ticker"] == "AEGISLOG.NS") & (self.div_df["ex_date"] == "13-Sep-2005")]
        self.assertFalse(aeg.empty, "AEGISLOG.NS dividend on 13-Sep-2005 should be recovered")
        self.assertEqual(aeg.iloc[0]["amount"], 1.2)

        tc = self.div_df[(self.div_df["ticker"] == "TATACOMM.NS") & (self.div_df["ex_date"] == "30-Aug-2005")]
        self.assertFalse(tc.empty, "TATACOMM.NS dividend on 30-Aug-2005 should be recovered")
        self.assertEqual(tc.iloc[0]["amount"], 6.0)
        self.assertEqual(tc.iloc[0]["regular_amount"], 4.5)
        self.assertEqual(tc.iloc[0]["special_amount"], 1.5)

    def test_zero_prehistory_dividend_leak(self):
        """Verify that pre-2004 dividends are never dumped onto 2004-01-01 in dividend matrices."""
        close = nio.load_tensor("close", universe="nifty500")
        div_mat = nio.get_dividend_matrix(close.index, close.columns.tolist(), adjusted=False)
        # 2004-01-01 must have exactly 0 dividends across all Nifty 500 constituents
        d0 = div_mat.loc["2004-01-01"]
        self.assertEqual((d0 > 0).sum(), 0, "No pre-2004 dividends should leak onto 2004-01-01")

        # Specific spot check on DIGITAL EQUIPMENT, BANCO INDIA, ASHOK LEYLAND FINANCE
        for t in ["DIGITALEQP.NS", "BANCOINDIA.NS", "ASHKLEYFIN.NS"]:
            if t in div_mat.columns:
                self.assertEqual(div_mat.loc["2004-01-01", t], 0.0)

    def test_master_universe_tensor_loading_and_tri_alignment(self):
        """Verify load_tensor returns consistent matrix shapes for dividends and aligned TRI."""
        # load_tensor('dividends', universe='master') must return a matrix matching close
        close_master = nio.load_tensor("close", universe="master")
        div_master = nio.load_tensor("dividends", universe="master")
        self.assertEqual(div_master.shape, close_master.shape)

        # load_tensor('dividends_ledger') returns the metadata table
        ledger = nio.load_tensor("dividends_ledger")
        self.assertIn("regular_amount", ledger.columns)
        self.assertGreater(len(ledger), 25_000)

        # load('close', adjusted='tri', start='2020-01-01') must match load('tri', start='2020-01-01')
        tri_via_key = nse.load("tri", universe="nifty50", start="2020-01-01")
        tri_via_adj = nse.load("close", universe="nifty50", adjusted="tri", start="2020-01-01")
        self.assertAlmostEqual(tri_via_key.loc["2020-01-01", "INFY.NS"], tri_via_adj.loc["2020-01-01", "INFY.NS"], places=2)

    def test_zero_disk_taint_invariant(self):
        """Verify that disk parquets remain 100% pure unadjusted exchange data."""
        raw_close = nio.load_tensor("close", universe="nifty50", adjusted=False)
        disk_raw = pd.read_parquet(config.TENSOR_FILES["close"])["RELIANCE.NS"]
        # Raw close on 2017-09-06 must match disk exactly
        self.assertEqual(raw_close.loc["2017-09-06", "RELIANCE.NS"], disk_raw.loc["2017-09-06"])


if __name__ == "__main__":
    unittest.main()
