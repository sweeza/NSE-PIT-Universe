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


def test_dividend_far_from_its_ex_date_is_not_placed():
    # audit: InvIT distributions of 2017-2024 were placed on the first day the unit traded in an equity series (2026)
    seg = pd.DataFrame({"symbol": ["AAA"], "sec_id": ["S1"], "start": pd.to_datetime(["2015-01-01"]),
                        "end": pd.to_datetime(["2030-01-01"])})
    days = {"S1": pd.to_datetime(["2020-01-10", "2020-01-13", "2020-03-02"]).values}
    ev = pd.DataFrame({"symbol": ["AAA"] * 4,
                       "ex_date": pd.to_datetime(["2020-01-11", "2020-01-13", "2020-01-20", "2020-01-10"]),
                       "kind": ["DIVIDEND"] * 3 + ["BONUS"]})
    out = adjust.attach_events(ev, seg, days)
    assert out.loc[0, "status"] == "OK" and out.loc[0, "eff_date"] == pd.Timestamp("2020-01-13")   # weekend
    assert out.loc[1, "status"] == "OK"        # same day
    assert out.loc[2, "status"] == "NO_TRADING_NEAR"   # next trade is 42 days later
    ev2 = pd.DataFrame({"symbol": ["AAA"], "ex_date": pd.to_datetime(["2020-01-20"]), "kind": ["BONUS"]})
    assert adjust.attach_events(ev2, seg, days).loc[0, "status"] == "OK"   # share events are gated elsewhere


def test_gate_keeps_an_overridden_action_the_price_test_would_reject_and_logs_it():
    import numpy as np
    d = pd.bdate_range("2013-07-01", periods=6)
    pcg = pd.DataFrame({"sec_id": "S1", "date": d, "open": [24.0, 24.0, 18.85, 18.0, 17.0, 16.0],
                        "close": [24.0, 24.0, 18.85, 18.0, 17.0, 16.0]})
    pcg["prev_close_obs"] = pcg.close.shift(1)
    adj = pd.DataFrame({"sec_id": ["S1"], "eff_date": [d[2]], "kind": ["BONUS"], "price_mult": [19 / 42], "vol_mult": [42 / 19],
                        "detail": ["23:19"], "rec_id": [0]})
    out, log = adjust.gate(adj, pcg)                                   # price fell 21%, a 2.2x bonus expects 55%
    assert out.empty and log.decision.tolist() == ["REJECTED"]
    out, log = adjust.gate(adj, pcg, override=frozenset({("S1", d[2])}))
    assert len(out) == 1 and log.decision.tolist() == ["OVERRIDDEN"]


def test_gate_override_keys_need_the_same_symbol_date_and_factor(tmp_path):
    ev = pd.DataFrame({"symbol": ["AAA", "AAA", "BBB"], "ex_date": pd.to_datetime(["2013-07-09"] * 3), "kind": "BONUS",
                       "status": "OK", "sec_id": ["S1", "S2", "S3"], "eff_date": pd.to_datetime(["2013-07-09"] * 3),
                       "share_factor": [2.0, 3.0, 2.0]})
    f = tmp_path / "o.csv"
    f.write_text("symbol,ex_date,share_factor,reason,source" + chr(10) + "AAA,2013-07-09,2.0,why,data/raw/x" + chr(10), encoding="utf-8")
    keys = adjust.gate_override_keys(ev, f)
    assert keys == frozenset({("S1", pd.Timestamp("2013-07-09"))})     # not the factor-3 record, not another symbol
    assert adjust.gate_override_keys(ev, tmp_path / "none.csv") == frozenset()
