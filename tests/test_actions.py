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


def test_special_dividend_after_spl_is_still_a_dividend():
    c = classify("Div-Int.Rs.5+Spl Rs2.50", 10.0)
    assert [x["kind"] for x in c] == ["DIVIDEND"] and c[0]["amount"] == pytest.approx(7.5)


def test_rupee_dividend_next_to_a_split_is_kept_and_percentage_is_not_read():
    c = classify("Fv Spl-Rs10to2/Div-Rs2.50", 2.0)
    assert [x["kind"] for x in c] == ["SPLIT", "DIVIDEND"]
    assert c[0]["share_factor"] == pytest.approx(5.0) and c[1]["amount"] == pytest.approx(2.5)
    c = classify("Interim Dividend Rs.3/- Per Share And Face Value Split From Rs.5/- To Rs.2/-", 2.0)
    assert [x["kind"] for x in c] == ["SPLIT", "DIVIDEND"] and c[1]["amount"] == pytest.approx(3.0)
    # a percentage next to a split: of the old or the new face value? not read
    assert [x["kind"] for x in classify("Agm/Div-5%/Spl-Rs10tors2", 2.0)] == ["SPLIT"]
    # a plain sub-division text must not produce a dividend component
    assert [x["kind"] for x in classify("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", 2.0)] == ["SPLIT"]


def test_dividend_with_colon_dash_or_at_sign():
    assert classify("Annual General Meeting/Dividend Rs:- 5.50 Per Share", 10.0)[0]["amount"] == pytest.approx(5.5)
    assert classify("Annual General Meeting/Dividend Rs:- 2/- Per Share", 10.0)[0]["amount"] == pytest.approx(2.0)
    assert classify("Annual General Meeting/Div.@1.20 Per Share", 10.0)[0]["amount"] == pytest.approx(1.2)
    # "Dvr : 10 Eq" (a bonus of DVR shares) is not a dividend of Rs 10
    assert classify("Bonus 1 Dvr : 10 Eq Share", 10.0)[0]["kind"] == "UNPARSED"


def test_leading_zero_dividend_without_point_is_reported_not_read():
    c = classify("Annual General Meeting/Dividend - Rs.0125 Per Share", 5.0)   # GENESYS 2019: 0.125 or 1.25
    assert [x["kind"] for x in c] == ["UNPARSED"]
    # a two-digit "Rs 09" is a plain nine rupees (TORNTPOWER 2023)
    c = classify("Interim Dividend - Rs 09 Per Share / Special Dividend - Rs 13 Per Share", 10.0)
    assert c[0]["kind"] == "DIVIDEND" and c[0]["amount"] == pytest.approx(22.0)


@pytest.mark.parametrize("subject", [
    "Sch Of Agmt- Bonus Deb1:1", "Scheme Of Arrangement - Bonus Debentures 6:1", "Bonus Preference Shares 21:1",
    "Scheme Of Arrangement - Bonus Ncrps 1:10", "Bonus Ncrps 1:116", "Scheme Of Arrangement - Bonus Ncrps 46:1",
])
def test_bonus_of_another_instrument_gets_no_share_factor(subject):
    c = classify(subject, 10.0)
    assert [x["kind"] for x in c] == ["SCHEME"] and "share_factor" not in c[0]


def test_equity_bonus_still_a_bonus_next_to_other_text():
    c = classify("Annual General Meeting/Dividend Rs.3/- Per Share/Bonus 1:1", 10.0)
    assert [x["kind"] for x in c] == ["BONUS", "DIVIDEND"] and c[0]["share_factor"] == pytest.approx(2.0)
    assert classify("Bonus 1 Dvr : 10 Eq Share", 10.0)[0]["kind"] == "UNPARSED"


def test_supplement_adds_only_rows_after_the_held_feed_and_not_duplicates(tmp_path):
    from nseuniverse.actions import load_supplement, build_events
    held = [{"symbol": "AAA", "exDate": "16-Oct-2026", "subject": "Bonus 1:1", "faceVal": "10", "isin": "INE000000001"}]
    csv = tmp_path / "s.csv"
    csv.write_text('\ufeff"SYMBOL","COMPANY NAME","SERIES","PURPOSE","FACE VALUE","EX-DATE","RECORD DATE","BOOK CLOSURE START DATE","BOOK CLOSURE END DATE"\n'
                   '"AAA","A Ltd","EQ","Bonus 1:1","10","16-Oct-2026","-","-","-"\n'      # same as held, not after it
                   '"BBB","B Ltd","EQ","Fv Split From Rs.10/- To Re.1/-","1","19-Oct-2026","-","-","-"\n'
                   '"CCC","C Ltd","EQ","Dividend - Rs 2 Per Share","10","not a date","-","-","-"\n', encoding="utf-8")
    add = load_supplement(held, csv)
    assert [r["symbol"] for r in add] == ["BBB"] and add[0]["isin"] is None
    ev = build_events(held + add)
    assert set(ev.symbol) == {"AAA", "BBB"}
    assert ev[ev.symbol == "BBB"].share_factor.iloc[0] == pytest.approx(10.0)
    assert load_supplement(held, tmp_path / "missing.csv") == []


def test_price_evidenced_action_becomes_a_split_event(tmp_path):
    from nseuniverse.actions import load_price_evidenced, build_events
    f = tmp_path / "p.csv"
    f.write_text("symbol,ex_date,kind,share_factor,source,note\n"
                 "NIFTYBEES,2019-12-19,SPLIT,10,data/raw/bhavcopy/legacy/2019/cm19DEC2019bhav.csv.zip,unit 1:10\n", encoding="utf-8")
    extra = load_price_evidenced(f)
    ev = build_events([], extra)
    r = ev.iloc[0]
    assert (r.symbol, r.kind, r.share_factor) == ("NIFTYBEES", "SPLIT", 10.0) and str(r.ex_date.date()) == "2019-12-19"
    assert len(load_price_evidenced(tmp_path / "none.csv")) == 0


def test_rights_at_par_with_an_at_sign():
    c = classify("Rights - 2:3@ Par Rs 10 Per Share", 10.0)   # ALOKTEXT 2013: issue price is the face value
    r = [x for x in c if x["kind"] == "RIGHTS"][0]
    assert r["issue_price"] == pytest.approx(10.0) and r["rights_new"] == 2 and r["rights_held"] == 3


def test_feed_lag_warning_fires_only_when_feed_ends_over_14_days_before_last_bhavcopy(tmp_path):
    ca = tmp_path / "corporate_actions"; ca.mkdir()
    (ca / "CF-CA-equities-01-01-2004-to-31-12-2006.csv").write_text("x")
    (ca / "CF-CA-equities-01-01-2004-to-01-11-2026.csv").write_text("x")
    assert actions.feed_end_date(ca) == pd.Timestamp("2026-11-01")
    assert actions.feed_end_date(tmp_path / "none") is pd.NaT
    bh = tmp_path / "bhavcopy"; (bh / "udiff" / "2026").mkdir(parents=True); (bh / "legacy" / "2024").mkdir(parents=True)
    (bh / "udiff" / "2026" / "BhavCopy_NSE_CM_0_0_0_20261120_F_0000.csv.zip").write_text("x")
    (bh / "legacy" / "2024" / "cm31MAY2024bhav.csv.zip").write_text("x")
    assert actions.last_bhavcopy_date(bh) == pd.Timestamp("2026-11-20")
    assert actions.last_bhavcopy_date(tmp_path / "none") is pd.NaT
    assert actions.feed_lag("2026-11-01", "2026-11-15")[0] == 14
    assert actions.feed_lag_warning("2026-11-01", "2026-11-15") is None             # exactly 14 days: no warning
    w = actions.feed_lag_warning("2026-11-01", "2026-11-16")                          # 15 days: warning
    assert "2026-11-01" in w and "15 days" in w and "2026-11-16" in w
    assert actions.feed_lag_warning("2026-11-23", "2026-11-20") is None             # feed newer than bhavcopy
    assert "no corporate-action feed file" in actions.feed_lag_warning(pd.NaT, "2026-11-16")
    assert actions.feed_lag_warning(pd.NaT, pd.NaT) is None


def test_feed_lag_is_in_the_caveat_catalogue():
    from nseuniverse import caveats
    assert "FEED_LAGS_BHAVCOPY" in set(caveats.catalogue().id)


def test_update_prints_the_feed_warning_before_and_after_the_run(monkeypatch, capsys):
    from nseuniverse import cli, fetch, pipeline, verify
    monkeypatch.setattr(fetch, "fetch_range", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "build_all", lambda: {})
    monkeypatch.setattr(verify, "run", lambda: [])
    monkeypatch.setattr(actions, "feed_lag_warning", lambda: "WARNING: feed old")
    assert cli.main(["update"]) == 0
    out = capsys.readouterr().out
    assert out.count("WARNING: feed old") == 2
    monkeypatch.setattr(actions, "feed_lag_warning", lambda: None)
    assert cli.main(["update"]) == 0
    assert "WARNING" not in capsys.readouterr().out


def test_data_quirks_are_in_the_caveat_catalogue():
    from nseuniverse import caveats
    assert {"PARTIAL_WEEKEND_SESSIONS", "T0_CLOSE_OUTSIDE_RANGE"} <= set(caveats.catalogue().id)
