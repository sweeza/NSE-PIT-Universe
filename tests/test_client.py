"""
Tests for nseuniverse client package (Ticker, Index & Universe functions).
"""

import unittest
import pandas as pd
import numpy as np
import nseuniverse as nse


class TestNseUniverseClient(unittest.TestCase):

    def test_ticker_init_and_info(self):
        """Test Ticker metadata retrieval."""
        t = nse.Ticker("TCS")
        self.assertEqual(t.symbol, "TCS")
        self.assertEqual(t.ticker, "TCS.NS")
        info = t.info
        self.assertEqual(info["asset_class"], "EQUITY")
        self.assertIn("Information Technology", info["sector"])
        self.assertTrue(t.is_active)
        self.assertIn("nifty50", info["current_indices"])

    def test_ticker_corporate_actions(self):
        """Test Ticker actions, splits, and bonuses."""
        rel = nse.Ticker("RELIANCE")
        actions = rel.actions
        self.assertFalse(actions.empty)
        bonuses = rel.bonuses
        self.assertFalse(bonuses.empty)
        # Check that 2017-09-07 bonus is present
        self.assertIn(pd.to_datetime("2017-09-07"), bonuses.index)
        self.assertEqual(bonuses.loc["2017-09-07"], 2.0)

    def test_ticker_history_adjusted(self):
        """Test ticker history with adjustment enabled."""
        rel = nse.Ticker("RELIANCE")
        hist = rel.history(start="2017-09-01", end="2017-09-15", adjusted=True)
        self.assertIn("Close", hist.columns)
        self.assertIn("Volume", hist.columns)
        self.assertIn("Trades", hist.columns)
        
        # Verify return over 2017-09-06 to 2017-09-07 is smooth
        ret = hist["Close"].loc["2017-09-06":"2017-09-07"].pct_change().iloc[-1]
        self.assertGreater(ret, -0.05)
        self.assertLess(ret, 0.05)

    def test_delisted_ticker_survivorship(self):
        """Test that inactive/delisted tickers can still be retrieved with full history."""
        t = nse.Ticker("3IINFOTECH")
        self.assertFalse(t.is_active)
        hist = t.history(start="2021-08-01", end="2021-08-30")
        self.assertFalse(hist.empty)
        self.assertIn("Close", hist.columns)

    def test_index_levels_and_ratios(self):
        """Test official index time series and valuation ratios."""
        nifty = nse.Index("NIFTY 50")
        self.assertEqual(nifty.symbol, "NIFTY 50")
        hist = nifty.history(start="2024-01-01", end="2024-01-10")
        self.assertIn("Close", hist.columns)
        self.assertIn("Pe", hist.columns)
        self.assertIn("Pb", hist.columns)
        self.assertIn("Div_yield", hist.columns)
        self.assertGreater(hist["Close"].iloc[-1], 20000.0)
        self.assertGreater(hist["Pe"].iloc[-1], 15.0)

    def test_index_aliases(self):
        """Test aliases like ^NSEI and BANKNIFTY."""
        idx1 = nse.Index("^NSEI")
        self.assertEqual(idx1.symbol, "NIFTY 50")
        idx2 = nse.Index("BANKNIFTY")
        self.assertEqual(idx2.symbol, "NIFTY BANK")
        vix = nse.Index("INDIA VIX")
        self.assertEqual(vix.symbol, "INDIA VIX")

    def test_load_index_matrix(self):
        """Test loading full cross-sectional tensor for an index."""
        n50_close = nse.load("close", universe="nifty50", start="2024-01-01", end="2024-01-31")
        self.assertIsInstance(n50_close, pd.DataFrame)
        self.assertIn("RELIANCE.NS", n50_close.columns)
        self.assertIn("INFY.NS", n50_close.columns)
        # Check active constituents
        self.assertAlmostEqual(n50_close.iloc[-1].notna().sum(), 50, delta=2)

    def test_load_universe_panel(self):
        """Test multi-field load_universe call."""
        panel = nse.load_universe(
            fields=["open", "high", "low", "close", "volume"],
            universe="niftybank",
            start="2024-01-01",
            end="2024-01-10",
            adjusted=True,
        )
        self.assertIn("open", panel)
        self.assertIn("close", panel)
        self.assertIn("HDFCBANK.NS", panel["close"].columns)


if __name__ == "__main__":
    unittest.main()
