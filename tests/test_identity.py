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


def test_same_isin_adjacent_symbols_join_without_symbolchange_record():
    t = table({"AAA": ("2010-01-01", "2010-03-31", "INE333C01033"), "BBB": ("2010-04-01", "2010-09-30", "INE333C01033")})
    sec, sh, links, _ = identity.build(t, sc())
    assert len(sec) == 1 and links.source.tolist() == ["isin"]


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


def test_attach_maps_every_row():
    t = table({"OLD": ("2010-01-01", "2010-06-30", None), "NEW": ("2010-07-01", "2010-12-31", None)})
    sec, sh, links, seg = identity.build(t, sc(("OLD", "NEW", "2010-07-01")))
    out = identity.attach(t, seg)
    assert out.sec_id.nunique() == 1 and out.sec_id.notna().all()


def test_partly_paid_isin_does_not_split_a_security():
    a = table({"TSTL": ("2018-01-01", "2018-06-29", "INE081A01012")})
    b = table({"TSTL": ("2018-07-02", "2018-12-31", "IN9081A01010")})     # partly-paid shares
    c = table({"TSTL": ("2019-01-01", "2019-06-28", "INE081A01012")})
    sec, *_ = identity.build(pd.concat([a, b, c], ignore_index=True), sc())
    assert len(sec) == 1


def test_missing_isin_as_nan_behaves_like_none():
    # newer pandas represents a missing string as NaN, which is truthy
    a = table({"AAA": ("2010-01-01", "2010-03-31", float("nan"))})
    b = table({"AAA": ("2010-04-01", "2010-06-30", "INE333C01033")})
    c = table({"AAA": ("2010-07-01", "2010-09-30", float("nan"))})
    sec, *_ = identity.build(pd.concat([a, b, c], ignore_index=True), sc())
    assert len(sec) == 1


def test_curated_join_links_a_rename_with_no_symbolchange_or_shared_isin():
    t = table({"OLD": ("2006-01-02", "2006-11-07", None), "NEW": ("2006-11-27", "2007-03-30", "INE017A01032")})
    sec, sh, links, seg = identity.build(t, sc())
    assert len(sec) == 2                                   # nothing links them without the curated row
    cur = pd.DataFrame([("OLD", "NEW", "evidence")], columns=["old_symbol", "new_symbol", "source"])
    sec, sh, links, seg = identity.build(t, sc(), cur)
    assert len(sec) == 1 and list(sh.symbol) == ["OLD", "NEW"]
    assert (links.source == "curated").sum() == 1


def test_curated_join_is_rejected_when_the_two_symbols_overlap():
    t = table({"OLD": ("2006-01-02", "2006-12-29", None), "NEW": ("2006-11-27", "2007-03-30", None)})
    cur = pd.DataFrame([("OLD", "NEW", "evidence")], columns=["old_symbol", "new_symbol", "source"])
    sec, *_ = identity.build(t, sc(), cur)
    assert len(sec) == 2
