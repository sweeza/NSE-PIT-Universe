"""Reconstruction helpers on small synthetic data (fast, offline)."""
import numpy as np
import pandas as pd
import pytest

from nseuniverse import reconstruct as rc


def test_review_dates_use_january_and_july_windows():
    days = pd.bdate_range("2007-01-02", "2008-12-31")
    rv = rc.review_dates(days)
    assert [e for e, _ in rv][:3] == [pd.Timestamp("2007-04-02"), pd.Timestamp("2007-10-01"), pd.Timestamp("2008-04-01")]
    assert rv[0][1] == pd.Timestamp("2007-01-31") and rv[1][1] == pd.Timestamp("2007-07-31")
    assert all(w < e for e, w in rv)


def test_shares_are_carried_back_through_splits():
    # 1:1 bonus (x2) on 2020-01-10; the snapshot (2024) says 200 shares, so before the bonus there were 100
    ref = pd.DataFrame({"sec_id": ["A"], "shares_ref": [200.0], "ref_date": [pd.Timestamp("2024-03-01")]})
    ev = pd.DataFrame({"sec_id": ["A"], "eff_date": [pd.Timestamp("2020-01-10")], "cum": [2.0]})
    rows = pd.DataFrame({"sec_id": ["A", "A", "A"],
                         "date": pd.to_datetime(["2019-12-31", "2020-01-10", "2023-01-02"])})
    s = rc._shares_on(rows, ref, ev)
    assert list(s) == [100.0, 200.0, 200.0]


def test_events_after_the_snapshot_are_ignored():
    ref = pd.DataFrame({"sec_id": ["A"], "shares_ref": [100.0], "ref_date": [pd.Timestamp("2024-03-01")]})
    ev = pd.DataFrame({"sec_id": ["A"], "eff_date": [pd.Timestamp("2025-01-01")], "cum": [2.0]})
    rows = pd.DataFrame({"sec_id": ["A"], "date": [pd.Timestamp("2023-01-02")]})
    assert list(rc._shares_on(rows, ref, ev)) == [100.0]


def test_security_without_events_keeps_snapshot_shares():
    ref = pd.DataFrame({"sec_id": ["A"], "shares_ref": [50.0], "ref_date": [pd.Timestamp("2024-03-01")]})
    ev = pd.DataFrame({"sec_id": ["B"], "eff_date": [pd.Timestamp("2020-01-10")], "cum": [2.0]})
    rows = pd.DataFrame({"sec_id": ["A"], "date": [pd.Timestamp("2010-01-04")]})
    assert list(rc._shares_on(rows, ref, ev)) == [50.0]


def test_members_at_uses_latest_review_and_rank_band():
    r = pd.DataFrame({"effective": [pd.Timestamp("2010-04-01")] * 3 + [pd.Timestamp("2010-10-01")] * 3,
                      "sec_id": ["A", "B", "C", "C", "B", "A"], "rank": [1, 2, 3, 1, 2, 3]})
    first = rc.members_at(r, "NIFTY50", "2010-06-30")
    assert list(first.sec_id) == ["A", "B", "C"]          # top 50 holds all three
    assert list(rc.members_at(r, "NIFTY50", "2010-10-01").sec_id) == ["C", "B", "A"]
    assert rc.members_at(r, "NIFTY50", "2010-03-31").empty
    assert list(rc.members_at(r, "NIFTYNEXT50", "2010-06-30").sec_id) == []   # ranks 51-100


def test_rules_are_nested():
    lo = {k: v[:2] for k, v in rc.RULES.items()}
    assert lo["NIFTY50"] == (1, 50) and lo["NIFTYMIDCAP150"] == (101, 250) and lo["NIFTYSMALLCAP250"] == (251, 500)
    assert all(a <= b for a, b in lo.values())


def test_sectoral_indices_have_no_rule():
    assert "NIFTYBANK" not in rc.RULES and "NIFTYIT" not in rc.RULES
