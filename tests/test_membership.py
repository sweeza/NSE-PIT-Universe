import numpy as np
import pandas as pd
import pytest

from nseuniverse import membership as m


def iv(rows):
    return pd.DataFrame(rows, columns=["index_key", "sec_id", "from_date", "to_date"]).assign(
        from_date=lambda d: pd.to_datetime(d.from_date), to_date=lambda d: pd.to_datetime(d.to_date))


def ev(rows):
    return pd.DataFrame(rows, columns=["date", "sec_id", "action"]).assign(date=lambda d: pd.to_datetime(d.date))


def test_backward_replay_recovers_earlier_sets_from_the_anchor():
    # today: A, B. On 2020-01-01 C was replaced by B; on 2021-01-01 D was replaced by A.
    events = ev([("2020-01-01", "B", "IN"), ("2020-01-01", "C", "OUT"), ("2021-01-01", "A", "IN"), ("2021-01-01", "D", "OUT")])
    out = m.anchor_intervals({"A", "B"}, "2026-01-01", events)
    days = pd.bdate_range("2019-06-03", "2021-06-01")
    on = lambda d: set(out[(out.from_date.isna() | (out.from_date <= d)) & (out.to_date.isna() | (out.to_date > d))].sec_id)
    assert on(pd.Timestamp("2019-12-31")) == {"C", "D"}
    assert on(pd.Timestamp("2020-06-01")) == {"B", "D"}
    assert on(pd.Timestamp("2021-06-01")) == {"A", "B"}
    assert (m.size_on(out, days) == 2).all()


def test_member_since_before_first_event_has_open_start_and_is_found():
    out = iv([("X", "A", None, None), ("X", "B", "2020-01-01", None)])
    assert m.members(out, "X", "2010-01-01") == {"A"}
    assert m.members(out, "X", "2021-01-01") == {"A", "B"}


def test_size_counts_half_open_intervals():
    out = iv([("X", "A", "2020-01-02", "2020-01-06")])
    days = pd.bdate_range("2020-01-01", "2020-01-08")
    s = m.size_on(out, days)
    assert s.tolist() == [0, 1, 1, 0, 0, 0]       # in on Jan 2, out (exclusive) on Jan 6


def test_name_matching_is_exact_after_normalisation_and_never_fuzzy():
    nb = m.NameBook()
    nb.add("Tata Consultancy Services Ltd.", "TCS", "t")
    assert nb.candidates("TATA CONSULTANCY SERVICES LIMITED") == {"TCS"}
    assert nb.candidates("Tata Consultancy Service") == set()     # near miss is only a suggestion
    assert nb.suggest("Tata Consultancy Service")


def test_dated_alias_picks_the_company_that_existed_on_the_date():
    nb = m.NameBook()
    nb.add("Bajaj Auto Ltd", "BAJAJAUTO", "a", None, "2008-03-14")
    nb.add("Bajaj Auto Ltd", "BAJAJ-AUTO", "a", "2008-03-15", None)
    assert nb.candidates("Bajaj Auto Ltd", pd.Timestamp("2005-01-01")) == {"BAJAJAUTO"}
    assert nb.candidates("Bajaj Auto Ltd", pd.Timestamp("2010-01-01")) == {"BAJAJ-AUTO"}


def test_index_universe_reference_is_complete_and_unique():
    from nseuniverse import paths
    u = pd.read_csv(paths.CURATED / "index_universe.csv")
    assert u.index_key.is_unique and len(u) == 57
    assert u.category.value_counts().to_dict() == {"sectoral": 34, "broad_market": 23}


def test_contradictions_flag_events_that_cannot_be_undone():
    # consistent history: no contradictions
    ok = ev([("2020-01-01", "B", "IN"), ("2020-01-01", "C", "OUT")])
    assert m.contradictions({"A", "B"}, "2026-01-01", ok).empty
    # X was included in 2017 but is not in today's list and no exclusion is recorded
    bad = ev([("2017-03-31", "X", "IN"), ("2017-03-31", "C", "OUT")])
    out = m.contradictions({"A", "B"}, "2026-01-01", bad)
    assert out.to_dict("records") == [{"date": pd.Timestamp("2017-03-31"), "sec_id": "X", "action": "IN"}]
    # an exclusion of a current member with no re-inclusion is also a contradiction
    bad2 = ev([("2018-01-01", "A", "OUT")])
    assert m.contradictions({"A"}, "2026-01-01", bad2).action.tolist() == ["OUT"]


def test_every_anchor_file_exists_and_matches_its_declared_size():
    from nseuniverse import paths
    assert {"NIFTY50", "NIFTYNEXT50", "NIFTY100"} <= set(m.ANCHORED)
    for k, (n, f) in m.ANCHORED.items():
        lst = pd.read_csv(paths.ROOT / f)
        assert len(lst) == n and lst.Symbol.is_unique, k


def test_exclusive_alias_overrides_other_candidates_only_inside_its_window():
    nb = m.NameBook()
    nb.add("United Breweries Ltd.", "UBL", "a")
    nb.add("United Breweries Ltd.", "UBHOLDINGS", "b")
    assert nb.candidates("United Breweries Ltd.", pd.Timestamp("2015-01-01")) == {"UBL", "UBHOLDINGS"}
    nb.add("United Breweries Ltd.", "UBL", "c", "2013-04-01", "2019-12-31", exclusive=True)
    assert nb.candidates("United Breweries Ltd.", pd.Timestamp("2015-01-01")) == {"UBL"}
    assert nb.candidates("United Breweries Ltd.", pd.Timestamp("2010-01-01")) == {"UBL", "UBHOLDINGS"}   # outside the window nothing changes


def test_documented_dummy_constituents_are_counted_per_day_and_stack():
    days = pd.bdate_range("2026-04-27", "2026-05-06")
    exc = pd.DataFrame([("X", "2026-04-30", "2026-05-04", 1, "dummy", "s"), ("X", "2026-05-01", "2026-05-01", 2, "dummy", "s")],
                       columns=["index_key", "from_date", "to_date", "extra_members", "reason", "source"])
    assert m.extra_members(days, exc, "X").tolist() == [0, 0, 0, 1, 3, 1, 0, 0]
    assert not m.extra_members(days, exc, "Y").any()
    assert not m.extra_members(days, None, "X").any()


def test_dual_class_security_counts_only_while_dvr_and_parent_are_members():
    days = pd.bdate_range("2016-03-30", "2016-04-06")
    seg = pd.DataFrame([("DVR", "d", "2016-01-01", "2017-12-31"), ("PAR", "p", "2016-01-01", "2017-12-31")],
                       columns=["symbol", "sec_id", "start", "end"]).assign(start=lambda d: pd.to_datetime(d.start), end=lambda d: pd.to_datetime(d.end))
    dc = pd.DataFrame([("X", "2016-04-01", "2016-04-05", 1, "DVR", "PAR", "r", "s")],
                      columns=["index_key", "from_date", "to_date", "extra_securities", "symbols", "parent_symbol", "reason", "source"])
    both = iv([("X", "d", "2016-04-01", None), ("X", "p", None, None)])
    assert m.dual_class_securities(days, dc, "X", both, seg).tolist() == [0, 0, 1, 1, 1, 0]
    assert not m.dual_class_securities(days, dc, "Y", both, seg).any()
    no_parent = iv([("X", "d", "2016-04-01", None)])             # the company itself is not a member: no allowance
    assert not m.dual_class_securities(days, dc, "X", no_parent, seg).any()
    only_parent = iv([("X", "p", None, None)])                    # DVR not (yet) a member: no allowance
    assert not m.dual_class_securities(days, dc, "X", only_parent, seg).any()
    assert not m.dual_class_securities(days, None, "X", both, seg).any()


def test_floor_masks_days_before_it_and_leaves_no_floor_untouched():
    days = pd.bdate_range("2006-12-27", "2007-01-04")
    ok = np.ones(len(days), dtype=bool)
    out, scope = m.apply_floor(ok, days, "2007-01-01")
    assert out.tolist() == scope.tolist() == [False, False, False, True, True, True, True]    # 2006-12-27..29 are out of scope
    out, scope = m.apply_floor(ok, days, None)
    assert out.all() and scope.all()
