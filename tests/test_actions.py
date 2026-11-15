import pytest

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


def test_special_dividend_is_not_a_split():
    # "Spl" means special dividend here
    kinds = {c["kind"] for c in one("Div Fin-30% + Spl-50%")}
    assert kinds == {"DIVIDEND"}


def test_consolidation_is_below_one():
    c = one("Consolidation Of Equity Shares From Re 1 Per Share To Rs 10 Per Share")[0]
    assert c["kind"] == "CONSOLIDATION" and c["share_factor"] == pytest.approx(0.1)


def test_bonus_and_split_in_one_subject_give_two_components():
    comps = one("Bon 1:1/Fv Spl Rs.5tore.1")
    kinds = sorted(c["kind"] for c in comps)
    assert kinds == ["BONUS", "SPLIT"]
    total = 1.0
    for c in comps:
        total *= c["share_factor"]
    assert total == pytest.approx(10.0)


def test_rights_with_premium_and_at_par():
    c = one("Rights 1:5 @ Premium Rs 120", fv=10)[0]
    assert c["kind"] == "RIGHTS" and c["issue_price"] == pytest.approx(130.0)
    c = one("Rights 4:7 At Par", fv=10)[0]
    assert c["kind"] == "RIGHTS" and c["issue_price"] == pytest.approx(10.0)


def test_rights_without_a_price_is_reported_not_guessed():
    assert one("Rights 1:1", fv=10)[0]["kind"] == "UNPARSED"


def test_dividend_amounts():
    assert one("Dividend - Rs 5 Per Share")[0]["amount"] == pytest.approx(5.0)
    assert one("Dividend - Rs 2 Per Share/Special Dividend - Rs 3 Per Share")[0]["amount"] == pytest.approx(5.0)
    # percentage of face value
    assert one("Div 30%", fv=10)[0]["amount"] == pytest.approx(3.0)
    # rupee amount wins over the percentage that restates it
    assert one("Agm/Dividend - Rs 15/- Per Share (150%)", fv=10)[0]["amount"] == pytest.approx(15.0)
    # "inclusive of" must not double count the special part
    assert one("Dividend Rs 8.50 Per Share Inclusive Of Special Dividend Rs 2")[0]["amount"] == pytest.approx(8.5)


def test_dividend_with_no_amount_is_reported():
    assert one("Interim Dividend")[0]["kind"] == "UNPARSED"


def test_noeffect_and_unknown():
    assert one("Annual General Meeting")[0]["kind"] == "NOEFFECT"
    assert one("Dividend - Nil")[0]["kind"] == "NOEFFECT"
    assert one("zxqv something new")[0]["kind"] == "UNKNOWN"


def test_scheme_is_not_quantified():
    for s in ("Demerger", "Scheme Of Arrangement", "Buy Back"):
        c = one(s)[0]
        assert c["kind"] == "SCHEME" and "share_factor" not in c
