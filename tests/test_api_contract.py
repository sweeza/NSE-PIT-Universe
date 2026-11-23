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
    api.prices("AAA", "2005-01-03", "2007-01-08", "splits", allow_unverified=True)


def test_unknown_symbol_and_missing_day_are_errors_not_empty_frames(tiny_build):
    with pytest.raises(api.CoverageError):
        api.resolve("ZZZ", "2007-01-02")
    with pytest.raises(api.CoverageError):
        api.bhavcopy_day("2007-01-06")          # a Saturday


def test_membership_outside_verified_windows_is_refused(tiny_build):
    with pytest.raises(api.CoverageError):
        api.index_members("Nifty 50", "2007-01-02")


def test_mask_gaps_nulls_the_return_on_a_flagged_day_only(tiny_build):
    d = tiny_build
    pd.DataFrame({"sec_id": ["S00001"], "symbol": "AAA", "date": [d[4]], "series": "EQ", "r": 0.3, "class": "UNEXPLAINED"}
                 ).to_csv(paths.BUILD / "adjustment_gaps.csv", index=False)
    p = api.prices("AAA", "2007-01-01", "2007-01-08", "splits")
    assert p.adj_gap.tolist() == [False, False, False, False, True, False]
    m = api.prices("AAA", "2007-01-01", "2007-01-08", "splits", mask_gaps=True)
    assert m.adj_return.isna().tolist() == [True, False, False, False, True, False]    # day 0 has no prior day


def test_mask_gaps_needs_the_gap_table_and_an_adjust_mode(tiny_build):
    with pytest.raises(api.CoverageError):
        api.prices("AAA", "2007-01-01", "2007-01-08", "splits", mask_gaps=True)       # no adjustment_gaps.csv yet
    with pytest.raises(ValueError):
        api.prices("AAA", "2007-01-01", "2007-01-08", None, mask_gaps=True)


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


def test_flagged_prices_warn_and_list_the_days_with_their_class(tiny_build):
    d = tiny_build
    pd.DataFrame({"sec_id": ["S00001"], "symbol": "AAA", "date": [d[4]], "series": "EQ", "r": 0.3, "class": "UNEXPLAINED"}
                 ).to_csv(paths.BUILD / "adjustment_gaps.csv", index=False)
    with pytest.warns(api.DataQualityWarning, match="NOT masked"):
        p = api.prices("AAA", "2007-01-01", "2007-01-08", "splits")
    assert p.adj_gap_class.tolist()[4] == "UNEXPLAINED"
    assert p.attrs["flagged"]["class"].tolist() == ["UNEXPLAINED"]
    with pytest.warns(api.DataQualityWarning, match="set to NaN"):
        api.prices("AAA", "2007-01-01", "2007-01-08", "splits", mask_gaps=True)


def test_index_returns_are_flagged_and_masked_around_source_conflicts(tiny_build, monkeypatch):
    days = pd.bdate_range("2017-01-02", periods=6)
    v = pd.DataFrame({"index_key": "X", "date": days, "close": [100, 101, 90, 91, 92, 120.0],
                      "alt_close": [100, 101, 102, 103, 104, 120.0],
                      "conflict": [False, False, True, True, True, False]})
    monkeypatch.setattr(indices, "values", lambda k: v)
    with pytest.warns(api.DataQualityWarning, match="4 X source-conflict"):
        r = api.index_values("X")
    assert r.ret_unreliable.tolist() == [False, False, True, True, True, True]
    assert r.ret.notna().sum() == 5                         # unmasked by default
    with pytest.warns(api.DataQualityWarning, match="set to NaN"):
        m = api.index_values("X", mask_conflicts=True)
    assert m.ret.isna().tolist() == [True, False, True, True, True, True]
    clean = api.index_values("X", start=days[0], end=days[1])
    assert clean.attrs["flagged"].empty


def test_explicit_source_choice_replaces_the_close_and_blanks_mixed_columns(tiny_build, monkeypatch):
    days = pd.bdate_range("2017-01-02", periods=5)
    v = pd.DataFrame({"index_key": "X", "date": days, "close": [100, 90, 91, 92, 120.0],
                      "alt_close": [100, 102, 103, 104, 120.0], "open": [1.0] * 5, "tri": [5.0] * 5, "src": "daily",
                      "conflict": [False, True, True, True, False]})
    monkeypatch.setattr(indices, "values", lambda k: v)
    with pytest.warns(api.DataQualityWarning, match="by your choice"):
        r = api.index_values("X", source="history")
    assert r.close.tolist() == [100, 102, 103, 104, 120]
    assert r.src.tolist() == ["daily", "history", "history", "history", "daily"]
    assert r.open.isna().tolist() == [False, True, True, True, False]
    assert r.ret.round(4).tolist()[1:3] == [0.02, 0.0098]
    with pytest.raises(ValueError):
        api.index_values("X", source="history", mask_conflicts=True)
    with pytest.raises(ValueError):
        api.index_values("X", source="bogus")


def test_range_with_no_trading_day_is_an_error_not_an_empty_frame(tiny_build):
    # audit 8.2: prices('RELIANCE', Saturday, Sunday) used to return 0 rows silently
    with pytest.raises(api.CoverageError):
        api.prices("AAA", "2007-01-06", "2007-01-07", None)
    with pytest.raises(api.CoverageError):
        api.prices("AAA", "2007-01-06", "2007-01-07", "splits")


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


def test_backfill_never_reaches_before_2007_or_into_an_unverified_index(tiny_build):
    d = tiny_build
    _verified_from_third_day(d)
    with pytest.raises(api.CoverageError, match="backfill only covers"):
        api.index_members("NIFTY50", "2006-12-29", backfill=True)
    with pytest.raises(api.CoverageError):
        api.index_members("NIFTYBANK", d[0], backfill=True)                  # no verified window to copy from


def test_sme_securities_are_marked_unreliable_for_adjusted_prices(tiny_build):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")                           # a main-board security must not warn
        p = api.prices("AAA", "2007-01-01", "2007-01-08", "splits")
    assert p.adj_reliable.all() and api.sme_securities().empty
    f = paths.BUILD / "bhavcopy" / "bhavcopy_2007.parquet"
    t = pd.read_parquet(f); t["series"] = "SM"; t.to_parquet(f)
    api.clear_cache()
    with pytest.warns(api.DataQualityWarning, match="unreliable adjusted prices"):
        q = api.prices("AAA", "2007-01-01", "2007-01-08", "splits")
    assert not q.adj_reliable.any() and api.sme_securities().sec_id.tolist() == ["S00001"]
    raw = api.prices("AAA", "2007-01-01", "2007-01-08", None)    # raw prices are exact: no flag, no warning
    assert "adj_reliable" not in raw.columns


def test_curated_unreliable_list_marks_a_main_board_security_too(tiny_build, tmp_path, monkeypatch):
    cur = tmp_path / "curated"; cur.mkdir()
    (cur / "adjustment_unreliable.csv").write_text("symbol,reason,source" + chr(10) + "AAA,ETF unit change not applied,x" + chr(10), encoding="utf-8")
    monkeypatch.setattr(paths, "CURATED", cur)
    api.clear_cache()
    with pytest.warns(api.DataQualityWarning, match="ETF unit change"):
        p = api.prices("AAA", "2007-01-01", "2007-01-08", "splits")
    assert not p.adj_reliable.any()
    u = api.unreliable_adjusted()
    assert u.symbol.tolist() == ["AAA"] and "ETF unit change" in u.reason.iloc[0]


def test_caveats_catalogue_and_explain_list_the_flags_that_apply(tiny_build):
    d = tiny_build
    c = api.caveats()
    assert {"id", "category", "severity", "backtest_impact", "handling", "shown_by", "affected"} <= set(c.columns)
    assert c.id.is_unique and set(c.severity) <= {"HIGH", "MEDIUM", "LOW"}
    assert set(api.caveats("prices").category) == {"PRICES"}
    # a clean main-board security: only the always-on flags
    e = api.explain("AAA", "2007-01-01", "2007-01-08")
    assert set(e.id) == {"EX_DATE_NOT_ANNOUNCEMENT_DATE", "SEC_ID_NOT_STABLE"}
    # mark it as SME-platform and ask about an index that is verified only from the third day
    f = paths.BUILD / "bhavcopy" / "bhavcopy_2007.parquet"
    t = pd.read_parquet(f); t["series"] = "SM"; t.to_parquet(f)
    pd.DataFrame([{"index_key": "NIFTY50", "from_date": d[2], "to_date": d[-1], "status": "VERIFIED", "reason": ""}]
                 ).to_parquet(paths.BUILD / "membership" / "coverage.parquet")
    api.clear_cache()
    e = api.explain("AAA", d[0], d[-1], index="NIFTY50")
    assert {"SME_ADJUSTED_PRICES", "MEMBERSHIP_BACKFILLED"} <= set(e.id)
    assert e.severity.iloc[0] == "HIGH" and "adj_reliable" in e[e.id == "SME_ADJUSTED_PRICES"].handling.iloc[0]
    assert "2007-01-01" in e[e.id == "MEMBERSHIP_BACKFILLED"].applies_to.iloc[0]
    assert "ADJUSTED_BEFORE_2007" not in set(e.id)
