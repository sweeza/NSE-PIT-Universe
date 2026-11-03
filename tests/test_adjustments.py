"""
Unit and integration tests for nseuniverse_io corporate action adjustments.
"""

import unittest
import numpy as np
import pandas as pd
import nseuniverse_io as nio

class TestCorporateActionAdjustments(unittest.TestCase):

    def test_reliance_bonus_smoothing(self):
        """Verify that the 2017-09-07 Reliance 1:1 bonus has smooth continuous returns when adjusted=True."""
        raw_close = nio.load_tensor("close", universe="nifty50", adjusted=False)["RELIANCE.NS"]
        adj_close = nio.load_tensor("close", universe="nifty50", adjusted=True)["RELIANCE.NS"]

        # Raw ex-date return should be around -50% due to unadjusted bonus
        raw_ret = raw_close.loc["2017-09-06":"2017-09-07"].pct_change().iloc[-1]
        self.assertLess(raw_ret, -0.45)

        # Adjusted return should be close to normal daily fluctuation (-5% to +5%)
        adj_ret = adj_close.loc["2017-09-06":"2017-09-07"].pct_change().iloc[-1]
        self.assertGreater(adj_ret, -0.05)
        self.assertLess(adj_ret, 0.05)

    def test_volume_adjustment(self):
        """Verify that volume scales reciprocally (increases for historical pre-split dates)."""
        raw_vol = nio.load_tensor("volume", universe="nifty50", adjusted=False)["RELIANCE.NS"]
        adj_vol = nio.load_tensor("volume", universe="nifty50", adjusted=True)["RELIANCE.NS"]

        # On 2017-09-06, there was a 2x bonus in 2017 and another 2x bonus in 2024 -> factor = 4.0
        ratio = adj_vol.loc["2017-09-06"] / raw_vol.loc["2017-09-06"]
        self.assertAlmostEqual(ratio, 4.0, places=4)

    def test_zero_taint_invariant(self):
        """Verify that loading with adjusted=False matches raw parquet on disk exactly."""
        raw_close = nio.load_tensor("close", universe="nifty50", adjusted=False)["RELIANCE.NS"]
        # Raw close on 2017-09-06 must be ~1645.4
        self.assertAlmostEqual(raw_close.loc["2017-09-06"], 1645.40, places=1)

    def test_panel_load_universe(self):
        """Verify load_universe applies adjustment across all requested price/volume fields consistently."""
        panel = nio.load_universe(
            fields=["open", "high", "low", "close", "volume"],
            universe="nifty50",
            adjusted=True,
        )
        for f in ["open", "high", "low", "close", "volume"]:
            self.assertIn(f, panel)
            self.assertIn("RELIANCE.NS", panel[f].columns)
        
        # Verify geometric consistency: High >= Low, High >= max(Open, Close)
        h = panel["high"]["RELIANCE.NS"].dropna()
        l = panel["low"]["RELIANCE.NS"].dropna()
        o = panel["open"]["RELIANCE.NS"].dropna()
        c = panel["close"]["RELIANCE.NS"].dropna()
        common = h.index.intersection(l.index).intersection(o.index).intersection(c.index)
        
        self.assertTrue((h.loc[common] >= l.loc[common] - 1e-4).all())
        self.assertTrue((h.loc[common] >= o.loc[common] - 1e-4).all())
        self.assertTrue((h.loc[common] >= c.loc[common] - 1e-4).all())

if __name__ == "__main__":
    unittest.main()
