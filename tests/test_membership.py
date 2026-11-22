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
    from pathlib import Path
    from nseuniverse import paths
    assert {"NIFTY50", "NIFTYNEXT50", "NIFTY100", "NIFTY500"} <= set(m.ANCHORED)
    assert m.FLOORS["NIFTY500"] == "2007-01-01"
    exc_p = paths.CURATED / "index_size_exceptions.csv"
    exc = pd.read_csv(exc_p) if exc_p.exists() else pd.DataFrame()
    for k, (n, f) in m.ANCHORED.items():
        lst = pd.read_csv(paths.ROOT / f)
        adate = Path(f).parent.name
        has_exp = len(exc) and exc[exc.index_key == k]["reason"].fillna("").str.contains("expanded|constituents between", case=False).any()
        ext = int(m.extra_members(pd.DatetimeIndex([adate]), exc, k)[0]) if has_exp else 0
        # a zero-price dummy-symbol demerger constituent (DUMMY...) is documented in index_size_exceptions.csv, not a real member
        assert (~lst.Symbol.str.startswith("DUMMY")).sum() == n + ext and lst.Symbol.is_unique, k


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


def test_norm_name_preserves_parenthetical_tokens():
    assert m.norm_name("Jindal Stainless (Hisar) Ltd.") == "jindal stainless hisar"
    assert m.norm_name("Jindal Stainless Ltd.") == "jindal stainless"
    assert m.norm_name("United Breweries (Holdings) Ltd.") == "united breweries holdings"
    assert m.norm_name("United Breweries Ltd.") == "united breweries"


def test_namebook_loads_corporate_actions(tmp_path, monkeypatch):
    import json
    ca_file = tmp_path / "raw_corporate_actions_1995_2026.json"
    ca_file.write_text(json.dumps([{"comp": "Acme Corp Ltd.", "symbol": "ACME"}]), encoding="utf-8")
    monkeypatch.setattr(m.paths, "HELD", tmp_path)
    monkeypatch.setattr(m.paths, "RAW", tmp_path)
    monkeypatch.setattr(m.paths, "CURATED", tmp_path)
    nb = m.NameBook.build()
    assert nb.candidates("Acme Corp Ltd.") == {"ACME"}


def test_build_anchored_raises_on_unmapped_press_or_anchor(tmp_path, monkeypatch):
    cur_dir = tmp_path / "curated"
    cur_dir.mkdir()
    monkeypatch.setattr(m.paths, "CURATED", cur_dir)

    seg = pd.DataFrame([{"sec_id": "S1", "symbol": "A", "start": pd.Timestamp("2000-01-01"), "end": pd.Timestamp("2030-01-01")}])
    t = pd.DataFrame([{"sec_id": "S1", "series": "EQ", "date": pd.Timestamp("2026-01-02")}])
    ev_res = pd.DataFrame(columns=["index_key", "resolution", "date", "sec_id", "action"])

    anchor_dir = tmp_path / "2026-01-02"
    anchor_dir.mkdir()
    (anchor_dir / "a.csv").write_text("Symbol\nA\n", encoding="utf-8")
    monkeypatch.setattr(m, "ANCHORED", {"X": (1, "2026-01-02/a.csv")})

    # 1) Unmapped press event raises ValueError
    (cur_dir / "index_events_press.csv").write_text("index_key,date,symbol,action\nX,2026-01-02,MISSING,IN\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unmapped press events"):
        m.build_anchored(ev_res, seg, t, tmp_path)

    # 2) Unmapped real anchor raises ValueError
    (cur_dir / "index_events_press.csv").unlink()
    (anchor_dir / "a.csv").write_text("Symbol\nA\nMISSING_ANCHOR\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unmapped anchor symbols"):
        m.build_anchored(ev_res, seg, t, tmp_path)


def test_build_anchored_writes_contradictions_csv(tmp_path, monkeypatch):
    cur_dir = tmp_path / "curated"
    cur_dir.mkdir()
    monkeypatch.setattr(m.paths, "CURATED", cur_dir)

    seg = pd.DataFrame([
        {"sec_id": "S1", "symbol": "A", "start": pd.Timestamp("2000-01-01"), "end": pd.Timestamp("2030-01-01")},
        {"sec_id": "S2", "symbol": "B", "start": pd.Timestamp("2000-01-01"), "end": pd.Timestamp("2030-01-01")},
    ])
    t = pd.DataFrame([
        {"sec_id": "S1", "series": "EQ", "date": pd.Timestamp("2026-01-02")},
        {"sec_id": "S2", "series": "EQ", "date": pd.Timestamp("2026-01-02")},
    ])
    # S2 (B) is in anchor, but has an un-re-included OUT event -> contradiction
    ev_res = pd.DataFrame([
        {"index_key": "X", "resolution": "OK", "date": pd.Timestamp("2020-01-01"), "sec_id": "S2", "action": "OUT"}
    ])
    anchor_dir = tmp_path / "2026-01-02"
    anchor_dir.mkdir()
    (anchor_dir / "a.csv").write_text("Symbol\nA\nB\n", encoding="utf-8")
    monkeypatch.setattr(m, "ANCHORED", {"X": (2, "2026-01-02/a.csv")})
    monkeypatch.setattr(m, "FLOORS", {"X": "2007-01-01"})

    out_csv = tmp_path / "contradictions.csv"
    m.build_anchored(ev_res, seg, t, tmp_path, contradictions_out=out_csv)
    assert out_csv.exists()
    cdf = pd.read_csv(out_csv)
    assert cdf.to_dict("records") == [{"index_key": "X", "date": "2020-01-01", "sec_id": "S2", "last_symbol": "B", "action": "OUT"}]


def test_namebook_accepts_exclusive_true_string(tmp_path, monkeypatch):
    cur_dir = tmp_path / "curated"
    cur_dir.mkdir()
    (cur_dir / "name_aliases.csv").write_text(
        "company,symbol,source,valid_from,valid_to,exclusive\n"
        "Acme Ltd.,ACME1,test,,,True\n"
        "Acme Ltd.,ACME2,test,,,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(m.paths, "HELD", tmp_path)
    monkeypatch.setattr(m.paths, "RAW", tmp_path)
    monkeypatch.setattr(m.paths, "CURATED", cur_dir)
    nb = m.NameBook.build()
    assert nb.candidates("Acme Ltd.", pd.Timestamp("2020-01-01")) == {"ACME1"}


def test_build_composites_derives_eq_and_diff_indices(tmp_path, monkeypatch):
    days = pd.bdate_range("2026-01-01", "2026-01-10")
    traded = {f"S{i}": np.arange(len(days)) for i in range(1, 6)}
    seg = pd.DataFrame([{"sec_id": f"S{i}", "symbol": f"SYM{i}", "start": days[0], "end": days[-1]} for i in range(1, 6)])
    exc = pd.DataFrame(columns=["index_key", "from_date", "to_date", "reason", "source"])

    # Base intervals: P1 has {S1, S2, S3}, P2 has {S1}
    iv_p1 = pd.DataFrame([
        {"index_key": "P1", "sec_id": "S1", "from_date": pd.NaT, "to_date": pd.NaT},
        {"index_key": "P1", "sec_id": "S2", "from_date": pd.NaT, "to_date": pd.NaT},
        {"index_key": "P1", "sec_id": "S3", "from_date": pd.NaT, "to_date": pd.NaT},
    ])
    iv_p2 = pd.DataFrame([
        {"index_key": "P2", "sec_id": "S1", "from_date": pd.NaT, "to_date": pd.NaT},
    ])
    ivs = [iv_p1, iv_p2]
    cov = [
        ("P1", days[0], days[-1], "VERIFIED", "all good"),
        ("P2", days[0], days[-1], "VERIFIED", "all good"),
    ]

    # Mock COMPOSITE_ANCHORS with one EQ and one DIFF
    # Write constituent CSVs in tmp_path
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "p1.csv").write_text("Symbol\nSYM1\nSYM2\nSYM3\n", encoding="utf-8")
    (raw_dir / "p2.csv").write_text("Symbol\nSYM1\n", encoding="utf-8")
    (raw_dir / "c_eq.csv").write_text("Symbol\nSYM1\nSYM2\nSYM3\n", encoding="utf-8")
    (raw_dir / "c_diff.csv").write_text("Symbol\nSYM2\nSYM3\n", encoding="utf-8")

    test_composites = {
        "C_EQ": (3, "raw/c_eq.csv", ("EQ", "P1")),
        "C_DIFF": (2, "raw/c_diff.csv", ("DIFF", "P1", "P2")),
    }
    monkeypatch.setattr(m, "COMPOSITE_ANCHORS", test_composites)
    monkeypatch.setattr(m, "FLOORS", {"C_EQ": "2026-01-01", "C_DIFF": "2026-01-01"})
    # Mock parent_anchor_files inside build_composites by passing custom root
    # Note build_composites uses parent_anchor_files mapping, let's map in root
    anchor_2026 = tmp_path / "data" / "raw" / "constituents" / "2026-11-19"
    anchor_2026.mkdir(parents=True)
    (anchor_2026 / "ind_nifty500list.csv").write_text("Symbol\nSYM1\nSYM2\nSYM3\n", encoding="utf-8")
    (anchor_2026 / "ind_nifty100list.csv").write_text("Symbol\nSYM1\n", encoding="utf-8")
    test_composites_official = {
        "C_EQ": (3, "raw/c_eq.csv", ("EQ", "NIFTY500")),
        "C_DIFF": (2, "raw/c_diff.csv", ("DIFF", "NIFTY500", "NIFTY100")),
    }
    monkeypatch.setattr(m, "COMPOSITE_ANCHORS", test_composites_official)
    ivs_test = [
        pd.DataFrame([
            {"index_key": "NIFTY500", "sec_id": "S1", "from_date": pd.NaT, "to_date": pd.NaT},
            {"index_key": "NIFTY500", "sec_id": "S2", "from_date": pd.NaT, "to_date": pd.NaT},
            {"index_key": "NIFTY500", "sec_id": "S3", "from_date": pd.NaT, "to_date": pd.NaT},
        ]),
        pd.DataFrame([
            {"index_key": "NIFTY100", "sec_id": "S1", "from_date": pd.NaT, "to_date": pd.NaT},
        ]),
    ]
    cov_test = [
        ("NIFTY500", days[0], days[-1], "VERIFIED", "all good"),
        ("NIFTY100", days[0], days[-1], "VERIFIED", "all good"),
    ]
    m.build_composites(ivs_test, cov_test, days, traded, seg, exc, tmp_path)

    # Check that C_EQ and C_DIFF were added to ivs_test and cov_test
    keys_in_iv = {df["index_key"].iloc[0] for df in ivs_test}
    assert "C_EQ" in keys_in_iv
    assert "C_DIFF" in keys_in_iv
    cov_df = pd.DataFrame(cov_test, columns=["index_key", "from_date", "to_date", "status", "reason"])
    assert len(cov_df[(cov_df.index_key == "C_EQ") & (cov_df.status == "VERIFIED")]) == 1
    assert len(cov_df[(cov_df.index_key == "C_DIFF") & (cov_df.status == "VERIFIED")]) == 1

    # Check member sets of C_DIFF
    c_diff_iv = [df for df in ivs_test if df["index_key"].iloc[0] == "C_DIFF"][0]
    m_diff_day0 = m.members(c_diff_iv, "C_DIFF", days[0])
    assert m_diff_day0 == {"S2", "S3"}

