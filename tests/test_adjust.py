import numpy as np
import pandas as pd
import pytest

from nseuniverse import adjust


def px(closes, start="2020-01-01", sec="S00001"):
    d = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"sec_id": sec, "date": d, "open": closes, "high": closes, "low": closes,
                         "close": closes, "last": closes, "prev_close": closes,
                         "volume": [1000.0] * len(closes)})


def adj_table(rows):
    return pd.DataFrame(rows, columns=["sec_id", "eff_date", "kind", "price_mult", "vol_mult", "detail", "rec_id"])


def test_split_makes_series_continuous_and_preserves_turnover():
    p = px([100, 100, 20, 20])          # 5:1 split effective on 3rd day
    a = adj_table([("S00001", p.date[2], "SPLIT", 1 / 5, 5.0, "10->2", 0)])
    out = adjust.apply(p, a)
    assert out["adj_close"].tolist() == pytest.approx([20, 20, 20, 20])
    # traded value is unchanged by a share-structure adjustment
    assert (out["adj_close"] * out["adj_volume"]).tolist() == pytest.approx((out["close"] * out["volume"]).tolist())


def test_bonus_then_split_compound():
    p = px([200, 200, 100, 100, 10, 10])   # 1:1 bonus (S=2) then 10->1 split (S=10)
    a = adj_table([("S00001", p.date[2], "BONUS", 0.5, 2.0, "1:1", 0),
                   ("S00001", p.date[4], "SPLIT", 0.1, 10.0, "10->1", 1)])
    out = adjust.apply(p, a)
    assert out["adj_close"].tolist() == pytest.approx([10] * 6)
    assert out["price_factor"].tolist() == pytest.approx([0.05, 0.05, 0.1, 0.1, 1, 1])
    assert out["volume_factor"].tolist() == pytest.approx([20, 20, 10, 10, 1, 1])


def test_as_of_ignores_later_events():
    p = px([100, 100, 50, 50, 25, 25])
    a = adj_table([("S00001", p.date[2], "BONUS", 0.5, 2.0, "1:1", 0),
                   ("S00001", p.date[4], "BONUS", 0.5, 2.0, "1:1", 1)])
    early = adjust.apply(p, a, as_of=p.date[3])
    assert early["adj_close"].tolist() == pytest.approx([50, 50, 50, 50, 25, 25])   # 2nd bonus unseen
    full = adjust.apply(p, a)
    assert full["adj_close"].tolist() == pytest.approx([25] * 6)


def test_events_of_other_securities_do_not_leak():
    p = pd.concat([px([100, 100, 50], sec="S00001"), px([70, 70, 70], sec="S00002")], ignore_index=True)
    a = adj_table([("S00001", p.date[2], "BONUS", 0.5, 2.0, "1:1", 0)])
    out = adjust.apply(p, a)
    assert out[out.sec_id == "S00002"]["adj_close"].tolist() == [70, 70, 70]


def test_rights_terp_math():
    # P=100, rights 1 for 4 at 60: TERP = (100*4 + 60*1)/5 = 92
    d = pd.bdate_range("2020-01-01", periods=3)
    ev = pd.DataFrame([{"sec_id": "S00001", "eff_date": d[2], "kind": "RIGHTS", "status": "OK",
                        "rights_new": 1.0, "rights_held": 4.0, "issue_price": 60.0, "detail": "1:4",
                        "rec_id": 0, "share_factor": np.nan, "amount": np.nan}])
    close = {"S00001": pd.Series([100.0, 100.0, 92.0], index=d)}
    a = adjust.build_adjustments(ev, close)
    assert a.price_mult.iloc[0] == pytest.approx(0.92)
    assert a.vol_mult.iloc[0] == 1.0


def test_dividend_only_in_total_return_mode():
    p = px([100, 100, 95, 95])
    a = adj_table([("S00001", p.date[2], "DIVIDEND", 0.95, 1.0, "rs 5", 0)])
    assert adjust.apply(p, a, mode="splits")["adj_close"].tolist() == [100, 100, 95, 95]
    assert adjust.apply(p, a, mode="total_return")["adj_close"].tolist() == pytest.approx([95, 95, 95, 95])


def test_duplicate_listing_of_same_action_applies_once():
    d = pd.bdate_range("2020-01-01", periods=3)
    base = {"sec_id": "S00001", "eff_date": d[2], "kind": "BONUS", "status": "OK", "detail": "1:1",
            "share_factor": 2.0, "amount": np.nan, "rights_new": np.nan, "rights_held": np.nan, "issue_price": np.nan}
    ev = pd.DataFrame([{**base, "rec_id": 0}, {**base, "rec_id": 1}])
    a = adjust.build_adjustments(ev, {"S00001": pd.Series([1.0, 1.0, 1.0], index=d)})
    assert len(a) == 1


def test_attach_moves_exdate_to_next_trading_day_and_reports_unplaceable():
    seg = pd.DataFrame({"symbol": ["AAA"], "start": [pd.Timestamp("2020-01-01")],
                        "end": [pd.Timestamp("2020-01-31")], "sec_id": ["S00001"]})
    days = {"S00001": pd.bdate_range("2020-01-01", "2020-01-31").values}
    ev = pd.DataFrame({"symbol": ["AAA", "AAA", "ZZZ"],
                       "ex_date": pd.to_datetime(["2020-01-11", "2020-02-20", "2020-01-10"]),   # Saturday
                       "kind": "BONUS"})
    out = adjust.attach_events(ev, seg, days)
    assert out.loc[0, "eff_date"] == pd.Timestamp("2020-01-13")
    assert out.loc[1, "status"] in ("NO_SECURITY", "NO_TRADING_AFTER")
    assert out.loc[2, "status"] == "NO_SECURITY"
