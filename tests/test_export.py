import numpy as np
import pandas as pd

from nseuniverse import export, membership

T = pd.Timestamp


def test_membership_file_holds_verified_days_only():
    iv = pd.DataFrame({"index_key": ["X"], "sec_id": ["S1"], "from_date": [pd.NaT], "to_date": [T("2020-03-01")]})
    cov = pd.DataFrame({"index_key": ["X", "X"], "status": ["VERIFIED", "PARTIAL"],
                        "from_date": [T("2020-01-01"), T("2019-01-01")], "to_date": [T("2020-06-30"), T("2020-06-30")]})
    sh = pd.DataFrame({"sec_id": ["S1", "S1"], "symbol": ["OLD", "NEW"], "from_date": [T("2019-01-01"), T("2020-02-01")],
                       "to_date": [T("2020-01-31"), T("2020-06-30")], "isins": ["INE1", "INE2"]})
    out = export.verified_membership(iv, cov, sh, "2020-06-30")
    assert out[["symbol", "isin", "from_date", "to_date"]].values.tolist() == [["NEW", "INE2", T("2020-01-01"), T("2020-02-29")]]


def test_price_table_joins_delivery_adjusts_and_blanks_refused_securities():
    bhav = pd.DataFrame({"date": [T("2020-01-01")] * 2, "sec_id": ["S1", "S2"], "symbol": ["A", "B"], "series": ["EQ", "EQ"],
                         "close": [100.0, 50.0], "volume": [10, 20]})
    dlv = pd.DataFrame({"date": [T("2020-01-01")], "symbol": ["A"], "series": ["EQ"], "deliv_qty": [5], "deliv_pct": [50.0]})
    adj = pd.DataFrame({"sec_id": ["S1"], "eff_date": [T("2020-02-01")], "kind": ["SPLIT"], "price_mult": [0.5], "vol_mult": [2.0]})
    gaps = pd.DataFrame({"sec_id": ["S1"], "date": [T("2020-01-01")], "class": ["ON_ACTION_DAY"]})
    out = export.price_table(bhav, dlv, adj, {"S2"}, gaps).set_index("symbol")
    assert (out.loc["A", "price_factor"], out.loc["A", "volume_factor"], out.loc["A", "deliv_qty"]) == (0.5, 2.0, 5)
    assert np.isnan(out.loc["B", "price_factor"]) and np.isnan(out.loc["B", "deliv_qty"])
    assert out.adj_gap.tolist() == ["ON_ACTION_DAY", ""]


def test_size_exception_can_lower_an_index_below_its_official_size():
    days = pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-03"])
    exc = pd.DataFrame({"index_key": ["X"], "from_date": ["2020-01-02"], "to_date": ["2020-01-02"], "extra_members": [-2]})
    assert membership.extra_members(days, exc, "X").tolist() == [0, -2, 0]


def test_nothing_is_verified_before_an_index_launched():
    cov = pd.DataFrame({"index_key": ["NIFTYLARGEMIDCAP250"] * 2 + ["NIFTY50"], "status": ["VERIFIED"] * 3,
                        "from_date": [T("2016-09-30"), T("2010-01-04"), T("2010-01-04")],
                        "to_date": [T("2026-01-01"), T("2012-01-01"), T("2026-01-01")]})
    out = membership.clip_to_launch(cov)
    assert out.index_key.tolist() == ["NIFTYLARGEMIDCAP250", "NIFTY50"]
    assert out.from_date.tolist() == [T("2017-11-30"), T("2010-01-04")]
