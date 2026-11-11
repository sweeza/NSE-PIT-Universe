"""
Unit and integration tests for Point-in-Time (PIT) Index Universes,
Strict Subset Hierarchy Invariants, Listing Gatekeeper, and Dynamic Tradable Mask.
"""

import unittest
import json
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
        ]
        for idx_name, min_c, max_c in bounds:
            mask = pd.read_parquet(config.PIT_INDEX_FILES[idx_name])
            daily_c = mask.sum(axis=1)
            for yr, grp in daily_c.groupby(daily_c.index.year):
                yr_med = grp.median()
                self.assertGreaterEqual(yr_med, min_c, f"{idx_name} year {yr} underflow: median={yr_med}")
                self.assertLessEqual(yr_med, max_c, f"{idx_name} year {yr} overflow: median={yr_med}")

        # Nifty IT structural regime shift: 20 constituents from 1999 to May 2015,
        # downsized to 10 constituents thereafter. Bounds are strictly enforced per regime.
        it_mask = pd.read_parquet(config.PIT_INDEX_FILES["niftyit"])
        it_c = it_mask.sum(axis=1)
        for yr, grp in it_c.groupby(it_c.index.year):
            yr_med = grp.median()
            if yr < 2015:
                self.assertGreaterEqual(yr_med, 18, f"niftyit pre-2015 year {yr} underflow: median={yr_med}")
                self.assertLessEqual(yr_med, 20, f"niftyit pre-2015 year {yr} overflow: median={yr_med}")
            else:
                self.assertEqual(yr_med, 10.0, f"niftyit post-2015 year {yr} median must be exactly 10: got {yr_med}")
                if yr >= 2016:
                    self.assertEqual(grp.min(), 10, f"niftyit year {yr} daily count underflow: min={grp.min()}")
                    self.assertEqual(grp.max(), 10, f"niftyit year {yr} daily count overflow: max={grp.max()}")

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

    def test_sectoral_official_reconstitution_accuracy(self):
        """Assert historical sectoral index memberships reflect official NSE reconstitution events."""
        # 1. Axis Bank hiatus in Nifty Bank (Excluded 2002-11-01, Re-included 2006-03-16)
        bank_mask = pd.read_parquet(config.PIT_INDEX_FILES["niftybank"])
        self.assertFalse(
            bank_mask.loc["2004-01-01", "AXISBANK.NS"],
            "AXISBANK.NS must be FALSE in Nifty Bank on 2004-01-01 during verified hiatus!"
        )
        self.assertFalse(
            bank_mask.loc["2005-06-01", "AXISBANK.NS"],
            "AXISBANK.NS must be FALSE in Nifty Bank on 2005-06-01 during verified hiatus!"
        )
        self.assertFalse(
            bank_mask.loc["2006-03-14", "AXISBANK.NS"],
            "AXISBANK.NS must be FALSE in Nifty Bank on 2006-03-14 before re-inclusion!"
        )
        self.assertTrue(
            bank_mask.loc["2006-03-16", "AXISBANK.NS"],
            "AXISBANK.NS must be TRUE in Nifty Bank on 2006-03-16 on official re-inclusion date!"
        )
        self.assertTrue(
            bank_mask.loc["2006-03-20", "AXISBANK.NS"],
            "AXISBANK.NS must be TRUE in Nifty Bank on 2006-03-20 after official re-inclusion!"
        )
        self.assertTrue(
            bank_mask.loc["2024-01-01", "AXISBANK.NS"],
            "AXISBANK.NS must be TRUE in Nifty Bank on 2024-01-01 as current stalwart!"
        )

        # 2. Yes Bank vs Bandhan Bank in Nifty Bank (Excluded / Included 2020-03-19)
        self.assertFalse(bank_mask.loc["2010-01-04", "YESBANK.NS"], "YESBANK.NS must be FALSE in Nifty Bank before 2012 inclusion")
        self.assertTrue(bank_mask.loc["2015-01-05", "YESBANK.NS"], "YESBANK.NS must be TRUE in Nifty Bank during active tenure")
        self.assertFalse(bank_mask.loc["2021-01-04", "YESBANK.NS"], "YESBANK.NS must be FALSE in Nifty Bank after 2020 exclusion")

        self.assertFalse(bank_mask.loc["2019-01-04", "BANDHANBNK.NS"], "BANDHANBNK.NS must be FALSE before 2020 inclusion")
        self.assertTrue(bank_mask.loc["2021-01-04", "BANDHANBNK.NS"], "BANDHANBNK.NS must be TRUE after 2020 inclusion")

        # 3. TCS and Satyam in Nifty IT (TCS included 2005-02-25)
        it_mask = pd.read_parquet(config.PIT_INDEX_FILES["niftyit"])
        self.assertFalse(it_mask.loc["2004-09-01", "TCS.NS"], "TCS.NS must be FALSE in Nifty IT prior to 2005 inclusion")
        self.assertTrue(it_mask.loc["2005-03-01", "TCS.NS"], "TCS.NS must be TRUE in Nifty IT after 2005 inclusion")
        self.assertTrue(it_mask.loc["2004-01-01", "SATYAMCOMP.NS"], "SATYAMCOMP.NS must be TRUE in Nifty IT in 2004")
        self.assertTrue(it_mask.loc["2008-01-01", "SATYAMCOMP.NS"], "SATYAMCOMP.NS must be TRUE in Nifty IT before 2009 collapse")

        # 4. Zero listing lookahead leaks across all 13 sectoral masks
        sectoral_names = [
            "niftyauto", "niftybank", "niftyenergy", "niftyfinance", "niftyfmcg",
            "niftyit", "niftymedia", "niftymetal", "niftypharma", "niftyrealty",
            "niftyhealthcare", "niftyoilgas", "niftyconsumerdurables"
        ]
        for sname in sectoral_names:
            m = pd.read_parquet(config.PIT_INDEX_FILES[sname])
            leaks = (m & ~self.has_traded).sum().sum()
            self.assertEqual(leaks, 0, f"Listing lookahead leaks in sectoral mask {sname}: {leaks}")

    def test_all_official_sheet_events_accuracy(self):
        """Assert zero omissions and zero lingering tenures across all post-2004 events in IndexInclExcl.xls."""
        excel_path = config.MOSHI_DIR / "IndexInclExcl.xls"
        if not excel_path.exists():
            self.skipTest("IndexInclExcl.xls not found")

        sheet_to_idx = {
            "Nifty Bank": "niftybank",
            "Nifty Auto": "niftyauto",
            "Nifty Energy": "niftyenergy",
            "Nifty Financial Services": "niftyfinance",
            "Nifty FMCG": "niftyfmcg",
            "Nifty IT": "niftyit",
            "Nifty Media": "niftymedia",
            "Nifty Metal": "niftymetal",
            "Nifty Pharma": "niftypharma",
            "Nifty Realty": "niftyrealty",
        }

        alias_map = json.loads((config.METADATA_DIR / "symbol_alias_map.json").read_text())
        def resolve_ticker(s):
            if not s:
                return None
            s_clean = s.replace(".NS", "").strip()
            c = alias_map.get(s_clean, s_clean)
            return f"{c}.NS"

        import build_pit_memberships as bpm
        name_overrides = bpm.NAME_OVERRIDES

        scrip_map = {}
        n500_recon_file = config.MOSHI_DIR / "Output" / "n500_mapped_reconstitutions_1995_2020.parquet"
        if n500_recon_file.exists():
            n500_recon = pd.read_parquet(n500_recon_file)
            scrip_map = n500_recon.drop_duplicates("scrip_name").set_index("scrip_name")["canonical_ticker"].to_dict()

        sec_master = pd.read_parquet(config.SECURITY_MASTER_FILE)
        for t, row in sec_master.iterrows():
            cn = str(row["company_name"]).strip()
            if cn and cn not in scrip_map:
                scrip_map[cn] = t
        scrip_map.update(name_overrides)

        masks = {k: pd.read_parquet(config.PIT_INDEX_FILES[k]) for k in sheet_to_idx.values()}
        xl = pd.ExcelFile(excel_path)

        inc_checked = 0
        exc_checked = 0

        for sheet_name, idx_key in sheet_to_idx.items():
            df = xl.parse(sheet_name)
            df.columns = [c.strip() for c in df.columns]
            mask = masks[idx_key]
            for _, row in df.iterrows():
                scrip = str(row["Scrip Name"]).strip()
                status = str(row["Description"]).strip()
                dt_val = pd.to_datetime(row["Event Date"], format="mixed", dayfirst=True)
                if dt_val < pd.Timestamp("2004-01-01"):
                    continue
                if scrip == "KPIT Technologies Ltd." and dt_val < pd.Timestamp("2019-01-01"):
                    ticker = "BSOFT.NS"
                else:
                    ticker = scrip_map.get(scrip)
                    if ticker:
                        ticker = resolve_ticker(ticker)
                self.assertIsNotNone(ticker, f"Unmapped scrip in official sheet {sheet_name}: {scrip} ({dt_val.date()})")
                self.assertIn(ticker, mask.columns, f"Ticker {ticker} for {scrip} missing from mask columns in {idx_key}")
                sessions = mask.index[mask.index >= dt_val]
                if sessions.empty:
                    continue
                check_dt = sessions[0]

                if "Inclusion" in status:
                    inc_checked += 1
                    # Inclusion must be genuinely traded on effective date and active in mask
                    self.assertTrue(
                        self.has_traded.loc[check_dt, ticker],
                        f"Inclusion scrip {ticker} was not actively traded on {check_dt.date()}!"
                    )
                    self.assertTrue(
                        mask.loc[check_dt, ticker],
                        f"Omitted inclusion: {ticker} must be TRUE in {idx_key} on effective date {check_dt.date()}"
                    )
                elif "Exclusion" in status:
                    # Special case: Sterlite merged into Sesa Goa (both VEDL.NS); Sesa Goa remained in index
                    if ticker == "VEDL.NS" and dt_val == pd.Timestamp("2012-09-28"):
                        continue
                    exc_checked += 1
                    self.assertFalse(
                        mask.loc[check_dt, ticker],
                        f"Lingering tenure: {ticker} must be FALSE in {idx_key} on effective exclusion date {check_dt.date()}"
                    )

        self.assertGreater(inc_checked, 180, "Expected >180 post-2004 official inclusions verified")
        self.assertGreater(exc_checked, 180, "Expected >180 post-2004 official exclusions verified")

        # Specific Hiatus checks:
        bank_mask = masks["niftybank"]
        auto_mask = masks["niftyauto"]
        fin_mask = masks["niftyfinance"]
        it_mask = masks["niftyit"]
        realty_mask = masks["niftyrealty"]

        # Canara Bank hiatus: 2018-04-02 to 2024-09-26
        canbk_hiatus = bank_mask.loc["2018-04-02":"2024-09-26", "CANBK.NS"]
        self.assertEqual(canbk_hiatus.sum(), 0, "CANBK.NS must have 0 active sessions during 2018-2024 hiatus!")
        self.assertGreater(bank_mask.loc[:"2018-03-28", "CANBK.NS"].sum(), 2000, "CANBK.NS must be active before 2018")
        self.assertGreater(bank_mask.loc["2024-09-27":, "CANBK.NS"].sum(), 200, "CANBK.NS must be active after 2024 re-inclusion")

        # Union Bank hiatus: 2014-03-28 to 2025-12-29
        union_hiatus = bank_mask.loc["2014-03-28":"2025-12-29", "UNIONBANK.NS"]
        self.assertEqual(union_hiatus.sum(), 0, "UNIONBANK.NS must have 0 active sessions during 2014-2025 hiatus!")
        self.assertGreater(bank_mask.loc[:"2014-03-27", "UNIONBANK.NS"].sum(), 2000, "UNIONBANK.NS must be active before 2014")
        self.assertGreater(bank_mask.loc["2025-12-30":, "UNIONBANK.NS"].sum(), 100, "UNIONBANK.NS must be active after 2025 re-inclusion")

        # TVS Motor hiatus: 2013-04-01 to 2015-03-25
        tvs_hiatus = auto_mask.loc["2013-04-01":"2015-03-25", "TVSMOTOR.NS"]
        self.assertEqual(tvs_hiatus.sum(), 0, "TVSMOTOR.NS must have 0 active sessions during 2013-2015 hiatus!")
        self.assertGreater(auto_mask.loc[:"2013-03-28", "TVSMOTOR.NS"].sum(), 1500, "TVSMOTOR.NS must be active before 2013")
        self.assertGreater(auto_mask.loc["2015-03-26":, "TVSMOTOR.NS"].sum(), 2000, "TVSMOTOR.NS must be active after 2015 re-inclusion")

        # Assert previously omitted inclusions are active (>0 sessions)
        self.assertGreater(bank_mask["RBLBANK.NS"].sum(), 500, "RBLBANK.NS must be active in Nifty Bank")
        self.assertGreater(auto_mask["ARE&M.NS"].sum(), 1000, "ARE&M.NS must be active in Nifty Auto")
        self.assertGreater(auto_mask["BALKRISIND.NS"].sum(), 500, "BALKRISIND.NS must be active in Nifty Auto")
        self.assertGreater(fin_mask["M&MFIN.NS"].sum(), 1000, "M&MFIN.NS must be active in Nifty Finance")
        self.assertGreater(fin_mask["PEL.NS"].sum(), 300, "PEL.NS must be active in Nifty Finance")
        self.assertGreater(fin_mask["HDFCAMC.NS"].sum(), 500, "HDFCAMC.NS must be active in Nifty Finance")
        self.assertGreater(it_mask["MINDTREE.NS"].sum(), 2000, "MINDTREE.NS must be active in Nifty IT")
        self.assertGreater(it_mask["SUBEX.NS"].sum(), 300, "SUBEX.NS must be active in Nifty IT during 2007-2008")
        self.assertGreater(it_mask["3IINFOTECH.NS"].sum(), 100, "3IINFOTECH.NS must be active in Nifty IT during 2011")
        self.assertGreater(it_mask["BSOFT.NS"].sum(), 1000, "BSOFT.NS (KPIT) must be active in Nifty IT during 2012-2015 and 2016-2018")
        self.assertGreater(realty_mask["SUNTECK.NS"].sum(), 500, "SUNTECK.NS must be active in Nifty Realty")
        self.assertGreater(realty_mask["OMAXE.NS"].sum(), 200, "OMAXE.NS must be active in Nifty Realty")

        # Assert APTECHT in Nifty 500: active from 2004 until 2014-09-19 official exclusion date
        n500_mask = pd.read_parquet(config.PIT_INDEX_FILES["nifty500"])
        self.assertGreater(n500_mask["APTECHT.NS"].sum(), 2500, "APTECHT.NS must be active in Nifty 500 from 2004 to 2014")
        self.assertFalse(n500_mask.loc["2014-09-22":, "APTECHT.NS"].any(), "APTECHT.NS must be inactive in Nifty 500 post-exclusion")


if __name__ == "__main__":
    unittest.main()
