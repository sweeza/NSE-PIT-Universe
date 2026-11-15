"""API contract tests on a tiny synthetic build, so they run offline and fast."""
import pandas as pd
import pytest

from nseuniverse import adjust, api, paths


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
