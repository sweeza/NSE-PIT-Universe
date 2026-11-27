import pandas as pd
import pytest

from nseuniverse import identity


def table(spec):
    """spec: {symbol: (start, end, isin)} -> daily rows (every business day)."""
    rows = []
    for sym, (a, b, isin) in spec.items():
        for d in pd.bdate_range(a, b):
            rows.append({"date": d, "symbol": sym, "series": "EQ", "isin": isin})
    return pd.DataFrame(rows)


def sc(*rows):
    return pd.DataFrame(rows, columns=["old", "new", "eff"]).assign(eff=lambda d: pd.to_datetime(d.eff))


def test_rename_in_symbolchange_keeps_one_security():
    t = table({"OLD": ("2010-01-01", "2010-06-30", None), "NEW": ("2010-07-01", "2011-01-31", None)})
    sec, sh, links, seg = identity.build(t, sc(("OLD", "NEW", "2010-07-01")))
    assert len(sec) == 1
    assert list(sh.symbol) == ["OLD", "NEW"]
    assert (links.status == "JOINED").sum() == 1


def test_recycled_ticker_after_long_gap_is_a_new_security():
    t = table({"ABC": ("2005-01-03", "2005-12-30", "INE111A01011")})
    t2 = table({"ABC": ("2012-01-02", "2012-12-31", "INE222B01022")})
    sec, sh, links, seg = identity.build(pd.concat([t, t2], ignore_index=True), sc())
    assert len(sec) == 2 and sec.first_symbol.tolist() == ["ABC", "ABC"]


def test_same_ticker_new_issuer_without_gap_is_a_new_security():
    t = table({"ABC": ("2005-01-03", "2005-06-30", "INE111A01011")})
    t2 = table({"ABC": ("2005-07-01", "2005-12-30", "INE222B01022")})
    sec, *_ = identity.build(pd.concat([t, t2], ignore_index=True), sc())
    assert len(sec) == 2


def test_isin_change_of_digits_on_same_issuer_stays_one_security():
    # face-value split changes the trailing digits, not the issuer part
    t = table({"ABC": ("2005-01-03", "2005-06-30", "INE111A01011")})
    t2 = table({"ABC": ("2005-07-01", "2005-12-30", "INE111A01029")})
    sec, *_ = identity.build(pd.concat([t, t2], ignore_index=True), sc())
    assert len(sec) == 1


def test_join_that_would_overlap_two_symbols_on_one_day_is_rejected():
    t = table({"AAA": ("2010-01-01", "2010-06-30", "INE333C01033"), "BBB": ("2010-06-25", "2010-09-30", "INE333C01033")})
    sec, sh, links, _ = identity.build(t, sc(("AAA", "BBB", "2010-06-28")))
    assert len(sec) == 2
    assert "REJECTED_OVERLAP" in set(links.status)


def test_sec_ids_ordered_by_first_date_and_stable_when_data_is_appended():
    base = table({"AAA": ("2010-01-01", "2010-03-31", None), "BBB": ("2010-02-01", "2010-03-31", None)})
    sec1, *_ = identity.build(base, sc())
    more = pd.concat([base, table({"CCC": ("2010-03-01", "2010-03-31", None)})], ignore_index=True)
    sec2, *_ = identity.build(more, sc())
    m = sec2.set_index("sec_id").first_symbol.to_dict()
    assert {k: m[k] for k in sec1.sec_id} == sec1.set_index("sec_id").first_symbol.to_dict()
    assert m["S00003"] == "CCC"
