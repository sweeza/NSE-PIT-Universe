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
