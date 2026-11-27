import pandas as pd
import pytest

from nseuniverse import actions
from nseuniverse.actions import classify


def one(subject, fv=10.0):
    comps = classify(subject, fv)
    assert len(comps) >= 1
    return comps


@pytest.mark.parametrize("subject,factor", [
    ("Bonus 1:1", 2.0), ("Bonus 1:2", 1.5), ("Bonus 4:1", 5.0), (" Bonus 10:1", 11.0),
])
def test_bonus_share_factor(subject, factor):
    c = one(subject)[0]
    assert c["kind"] == "BONUS" and c["share_factor"] == pytest.approx(factor)


@pytest.mark.parametrize("subject,factor", [
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", 5.0),
    ("Fv Splt Frm Rs 10 To Re 1", 10.0),
    ("Face Value Split From Rs. 10/- To Rs. 5/-", 2.0),
])
def test_split_share_factor(subject, factor):
    c = one(subject)[0]
    assert c["kind"] == "SPLIT" and c["share_factor"] == pytest.approx(factor)


def test_consolidation_is_below_one():
    c = one("Consolidation Of Equity Shares From Re 1 Per Share To Rs 10 Per Share")[0]
    assert c["kind"] == "CONSOLIDATION" and c["share_factor"] == pytest.approx(0.1)


def test_rights_with_premium_and_at_par():
    c = one("Rights 1:5 @ Premium Rs 120", fv=10)[0]
    assert c["kind"] == "RIGHTS" and c["issue_price"] == pytest.approx(130.0)
    c = one("Rights 4:7 At Par", fv=10)[0]
    assert c["kind"] == "RIGHTS" and c["issue_price"] == pytest.approx(10.0)


def test_rights_without_a_price_is_reported_not_guessed():
    assert one("Rights 1:1", fv=10)[0]["kind"] == "UNPARSED"


def test_scheme_is_not_quantified():
    for s in ("Demerger", "Scheme Of Arrangement", "Buy Back"):
        c = one(s)[0]
        assert c["kind"] == "SCHEME" and "share_factor" not in c


# --- Stage 4 audit fixes (dividend entries used by total_return) ---


@pytest.mark.parametrize("subject,fv,factor", [
    ("Agm/Div-Rs.2/Fv Rs10tors5", 5.0, 2.0),                  # BHARTIARTL 2009: "to" glued to the figures
    ("Agm/Div-20%/Fv Rs10tors2 Purpose Revised", 2.0, 5.0),   # ERAINFRA 2008
    ("Agm/Div-5%/Spl-Rs10tors2 Purpose Revised", 2.0, 5.0),   # COREEDUTEC 2007
    ("Agm/Div-7%/Fv Sp Rs10to 4purpose Revised", 4.0, 2.5),   # SHREEKRPET 2000
    ("Agm/Div-20%/Spl Rs10-Rs2", 2.0, 5.0),                   # CASTEXTECH 2005: hyphen instead of "to"
])
def test_glued_face_value_split_is_a_split_not_a_dividend(subject, fv, factor):
    comps = classify(subject, fv)
    sp = [c for c in comps if c["kind"] == "SPLIT"]
    assert len(sp) == 1 and sp[0]["share_factor"] == pytest.approx(factor)
    # the face value (10) must not be read as a dividend of Rs 10
    assert all(c.get("amount", 0) < 10 for c in comps if c["kind"] == "DIVIDEND")


@pytest.mark.parametrize("subject", [
    "Sch Of Agmt- Bonus Deb1:1", "Scheme Of Arrangement - Bonus Debentures 6:1", "Bonus Preference Shares 21:1",
    "Scheme Of Arrangement - Bonus Ncrps 1:10", "Bonus Ncrps 1:116", "Scheme Of Arrangement - Bonus Ncrps 46:1",
])
def test_bonus_of_another_instrument_gets_no_share_factor(subject):
    c = classify(subject, 10.0)
    assert [x["kind"] for x in c] == ["SCHEME"] and "share_factor" not in c[0]
