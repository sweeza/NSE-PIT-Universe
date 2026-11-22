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


# --- Stage 4 audit fixes (dividend entries used by total_return) ---

def test_rights_premium_is_not_a_dividend_amount():
    # audit S1-A: the rights premium / issue price was summed into the dividend (TRENT 500, HATSUN 557, ...)
    d = [c for c in one("Dividend Rs.1.80 Per Share And Rights 1:3 @ Premium Rs.30/- Per Share", fv=5) if c["kind"] == "DIVIDEND"][0]
    assert d["amount"] == pytest.approx(1.8)
    k = [c["kind"] for c in one("Interim Dividend- Rs 3 Per Share / Rights 1:16 @ Premium Rs 554 Per Share", fv=1)]
    assert "DIVIDEND" in k
    d = [c for c in one("Interim Dividend- Rs 3 Per Share / Rights 1:16 @ Premium Rs 554 Per Share", fv=1) if c["kind"] == "DIVIDEND"][0]
    assert d["amount"] == pytest.approx(3.0)
    d = [c for c in one("Rights 7:5@Premium Rs.55 Per Share/Annual General Meeting / Dividend Re.1/- Per Equity Share", fv=1)
         if c["kind"] == "DIVIDEND"][0]
    assert d["amount"] == pytest.approx(1.0)
    d = [c for c in one("Int.Div70%/Rght1:5@Rs.500purpose Revised", fv=10) if c["kind"] == "DIVIDEND"][0]
    assert d["amount"] == pytest.approx(7.0)


def test_rupee_amount_glued_to_the_unit():
    assert one("Agm/Div-Re0.80 Per Share")[0]["amount"] == pytest.approx(0.8)
    assert one("Agm/Div-Rs7.5/- Per Sh")[0]["amount"] == pytest.approx(7.5)
    assert one("Dividend Rs -3.60 Per Share")[0]["amount"] == pytest.approx(3.6)
    # an ambiguous leading dot stays unparsed rather than guessed
    assert one("Agm/Div - Rs .50 Per Sh")[0]["kind"] == "UNPARSED"


def test_face_value_phrase_is_not_a_dividend():
    assert one("Annual General Meeting/ Div. Of Rs. 1.50/- Per Equity Share Of Rs. 10/- Each.")[0]["amount"] == pytest.approx(1.5)


def test_distribution_headline_total_or_sum_of_parts():
    # headline total stated: it is the payout
    assert one("Distribution - Rs 2.20 Per Unit Consisting Of Interest - Rs 1.66 Per Unit/ Dividend - Re 0.30 Per Unit/Return Of Capital 0.19 Per Unit/ Other Income 0.05 Per Unit")[0]["amount"] == pytest.approx(2.2)
    assert one("Distribution- Rs 2.51 Comprising Interest- Rs 2.01/Return Of Capital- Rs 0.47 Per Unit/Other Income On Surplus Funds- Rs 0.03 Per Unit")[0]["amount"] == pytest.approx(2.51)
    assert one("Distribution - Re 0.57 Per Unit Consisting Of Re 0.04 Per Unit In The Form Of Interest & Re 0.53 Per Unit In The Form Of Return Of Capital")[0]["amount"] == pytest.approx(0.57)
    # no headline: payout is the sum of the listed parts
    assert one("First Distribution - Interest Payment Rs 2.25 Per Unit/ Return Of Capital Re 0.80 Per Unit (Purpose Revised)")[0]["amount"] == pytest.approx(3.05)
    assert one("Distribution - Interest - Re 0.37/Dividend - Rs 4.44 Per Unit")[0]["amount"] == pytest.approx(4.81)
    # plain single-figure distribution
    assert one("Distribution - Rs 6.10 Per Unit")[0]["amount"] == pytest.approx(6.1)


def test_rights_abbreviations():
    c = one("Rhs 3:7@Prem Rs95/Div185%", fv=1)
    r = [x for x in c if x["kind"] == "RIGHTS"][0]
    assert r["issue_price"] == pytest.approx(96.0) and r["rights_new"] == 3 and r["rights_held"] == 7
    assert [x for x in c if x["kind"] == "DIVIDEND"][0]["amount"] == pytest.approx(1.85)
