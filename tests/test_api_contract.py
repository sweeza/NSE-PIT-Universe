"""API contract tests on a tiny synthetic build, so they run offline and fast."""
import pandas as pd
import pytest

from nseuniverse import adjust, api, indices, paths


@pytest.fixture()
def tiny_build(tmp_path, monkeypatch):
    b = tmp_path / "build"
    (b / "bhavcopy").mkdir(parents=True); (b / "identity").mkdir(); (b / "actions").mkdir(); (b / "membership").mkdir()
    d = pd.bdate_range("2007-01-01", periods=6)
    t = pd.DataFrame({"date": d, "symbol": "AAA", "series": "EQ", "isin": None, "open": 100.0, "high": 100.0, "low": 100.0,
                      "close": [100, 100, 100, 50, 50, 50], "last": 100.0, "prev_close": 100.0, "volume": 10.0, "turnover": 1.0,
                      "trades": 1.0, "name": None, "instrument_id": None, "settle_price": None, "src": "legacy", "sec_id": "S00001"})
    t.to_parquet(b / "bhavcopy" / "bhavcopy_2007.parquet")
    pd.DataFrame({"sec_id": ["S00001"], "first_symbol": "AAA", "last_symbol": "AAA", "first_date": d[0], "last_date": d[-1],
                  "n_days": 6, "isin_last": None, "is_equity": True}).to_parquet(b / "identity" / "securities.parquet")
    pd.DataFrame({"sec_id": ["S00001"], "symbol": "AAA", "from_date": d[0], "to_date": d[-1], "isins": ""}).to_parquet(b / "identity" / "symbol_history.parquet")
    pd.DataFrame({"sec_id": ["S00001"], "eff_date": [d[3]], "kind": "BONUS", "price_mult": 0.5, "vol_mult": 2.0, "detail": "1:1", "rec_id": 0}
                 ).to_parquet(b / "actions" / "adjustments.parquet")
    pd.DataFrame(columns=["sec_id", "symbol", "date", "series", "r", "class"]).to_csv(b / "adjustment_gaps.csv", index=False)
    monkeypatch.setattr(paths, "BUILD", b)
    monkeypatch.setattr(indices, "name_map", lambda: {})      # tests must not need downloaded raw files
    api.clear_cache()
    yield d
    api.clear_cache()


def test_adjusted_series_is_continuous_and_raw_is_untouched(tiny_build):
    p = api.prices("AAA", "2007-01-01", "2007-01-08", "splits")
    assert p.adj_close.tolist() == pytest.approx([50] * 6)
    raw = api.prices("AAA", "2007-01-01", "2007-01-08", None)
    assert raw.close.tolist() == [100, 100, 100, 50, 50, 50]


def test_point_in_time_as_of_ignores_later_actions(tiny_build):
    p = api.prices("AAA", "2007-01-01", "2007-01-08", "splits", as_of=tiny_build[2])
    assert p.adj_close.tolist() == pytest.approx([100, 100, 100, 50, 50, 50])


def test_adjusted_request_before_feed_coverage_is_refused(tiny_build):
    with pytest.raises(api.CoverageError):
        api.prices("AAA", "2005-01-03", "2007-01-08", "splits")
    assert len(api.prices("AAA", "2005-01-03", "2007-01-08", None)) == 6          # as-published prices need no adjustment coverage


def test_unknown_symbol_and_missing_day_are_errors_not_empty_frames(tiny_build):
    with pytest.raises(api.CoverageError):
        api.resolve("ZZZ", "2007-01-02")
    with pytest.raises(api.CoverageError):
        api.bhavcopy_day("2007-01-06")          # a Saturday


def test_membership_outside_verified_windows_is_refused(tiny_build):
    with pytest.raises(api.CoverageError):
        api.index_members("Nifty 50", "2007-01-02")


def _gaps(d, cls):
    pd.DataFrame({"sec_id": ["S00001"], "symbol": "AAA", "date": [d[4]], "series": "EQ", "r": 0.3, "class": cls}
                 ).to_csv(paths.BUILD / "adjustment_gaps.csv", index=False)


def test_default_masks_documented_event_days_but_not_unexplained_moves(tiny_build):
    d = tiny_build
    _gaps(d, "ON_ACTION_DAY")
    with pytest.warns(api.DataQualityWarning, match="1 of them were set to NaN"):
        m = api.prices("AAA", "2007-01-01", "2007-01-08", "splits")                        # default: events
    assert m.adj_gap.tolist() == [False, False, False, False, True, False]
    assert m.adj_return.isna().tolist() == [True, False, False, False, True, False]       # day 0 has no prior day
    _gaps(d, "UNEXPLAINED")                                                                # can be a real crash
    with pytest.warns(api.DataQualityWarning, match="0 of them were set to NaN"):
        u = api.prices("AAA", "2007-01-01", "2007-01-08", "splits")
    assert u.adj_return.notna().sum() == 5
    with pytest.warns(api.DataQualityWarning, match="1 of them were set to NaN"):
        a = api.prices("AAA", "2007-01-01", "2007-01-08", "splits", mask_gaps="all")      # True is the same
    assert a.adj_return.isna().tolist() == [True, False, False, False, True, False]
    with pytest.warns(api.DataQualityWarning):
        n = api.prices("AAA", "2007-01-01", "2007-01-08", "splits", mask_gaps="none")
    assert n.adj_return.notna().sum() == 5
    with pytest.raises(ValueError):
        api.prices("AAA", "2007-01-01", "2007-01-08", "splits", mask_gaps="some")


def test_index_members_includes_pit_symbol_and_prices_resolves_past_end(tiny_build):
    d = tiny_build
    b = paths.BUILD
    # Add a symbol rename in symbol_history and a verified membership window
    pd.DataFrame([
        {"sec_id": "S00001", "symbol": "AAA_OLD", "from_date": d[0], "to_date": d[2], "isins": ""},
        {"sec_id": "S00001", "symbol": "AAA", "from_date": d[3], "to_date": d[-1], "isins": ""},
    ]).to_parquet(b / "identity" / "symbol_history.parquet")
    pd.DataFrame([
        {"index_key": "NIFTY50", "sec_id": "S00001", "from_date": d[0], "to_date": d[-1]},
    ]).to_parquet(b / "membership" / "intervals.parquet")
    pd.DataFrame([
        {"index_key": "NIFTY50", "from_date": d[0], "to_date": d[-1], "status": "VERIFIED", "reason": ""},
    ]).to_parquet(b / "membership" / "coverage.parquet")
    api.clear_cache()

    m_early = api.index_members("NIFTY50", d[1])
    assert m_early["symbol"].tolist() == ["AAA_OLD"]
    m_late = api.index_members("NIFTY50", d[4])
    assert m_late["symbol"].tolist() == ["AAA"]

    # Querying past last available date resolves cleanly to AAA
    p = api.prices("AAA", d[0], "2007-01-15", "splits")
    assert len(p) == 6
    # Querying delisted symbol AAA_OLD over [d[0], d[-1]] resolves uniquely
    p_old = api.prices("AAA_OLD", d[0], d[-1], "splits")
    assert len(p_old) == 6


def _verified_from_third_day(d):
    b = paths.BUILD
    sec = pd.read_parquet(b / "identity" / "securities.parquet")
    sec = pd.concat([sec, pd.DataFrame({"sec_id": ["S00002"], "first_symbol": "BBB", "last_symbol": "BBB", "first_date": d[4],
                                        "last_date": d[-1], "n_days": 2, "isin_last": None, "is_equity": True})], ignore_index=True)
    sec.to_parquet(b / "identity" / "securities.parquet")
    pd.DataFrame({"sec_id": ["S00001", "S00002"], "symbol": ["AAA", "BBB"], "from_date": [d[0], d[4]], "to_date": [d[-1], d[-1]],
                  "isins": ""}).to_parquet(b / "identity" / "symbol_history.parquet")
    pd.DataFrame([{"index_key": "NIFTY50", "sec_id": s, "from_date": d[2], "to_date": d[-1]} for s in ("S00001", "S00002")]
                 ).to_parquet(b / "membership" / "intervals.parquet")
    pd.DataFrame([{"index_key": "NIFTY50", "from_date": d[2], "to_date": d[-1], "status": "VERIFIED", "reason": ""}]
                 ).to_parquet(b / "membership" / "coverage.parquet")
    api.clear_cache()


def test_backfill_is_opt_in_flagged_and_limited_to_securities_already_trading(tiny_build):
    d = tiny_build
    _verified_from_third_day(d)
    with pytest.raises(api.CoverageError):
        api.index_members("NIFTY50", d[0])                                   # default: refused
    with pytest.warns(api.DataQualityWarning, match="not the published membership"):
        m = api.index_members("NIFTY50", d[0], backfill=True)
    assert m.symbol.tolist() == ["AAA"]                                      # BBB lists only on d[4]: not carried back
    assert set(m.membership_status) == {"BACKFILLED_UNVERIFIED"} and (m.backfilled_from == d[2]).all()
    v = api.index_members("NIFTY50", d[3], backfill=True)                    # inside a verified window: the real list
    assert set(v.membership_status) == {"VERIFIED"} and sorted(v.symbol) == ["AAA", "BBB"]


def test_sme_securities_are_refused_an_adjusted_series_but_raw_prices_are_served(tiny_build):
    p = api.prices("AAA", "2007-01-01", "2007-01-08", "splits")
    assert len(p) == 6 and api.sme_securities().empty
    f = paths.BUILD / "bhavcopy" / "bhavcopy_2007.parquet"
    t = pd.read_parquet(f); t["series"] = "SM"; t.to_parquet(f)
    api.clear_cache()
    with pytest.raises(api.CoverageError, match="not offered"):
        api.prices("AAA", "2007-01-01", "2007-01-08", "splits")
    assert api.sme_securities().sec_id.tolist() == ["S00001"]
    assert len(api.prices("AAA", "2007-01-01", "2007-01-08", None)) == 6         # raw prices are exact
