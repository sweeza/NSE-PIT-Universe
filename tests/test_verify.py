"""Offline synthetic tests for nseuniverse.verify."""
import hashlib
import pandas as pd
import pytest

from nseuniverse import membership, paths, verify


@pytest.fixture()
def synthetic_env(tmp_path, monkeypatch):
    root = tmp_path
    raw = root / "data" / "raw"
    curated = root / "data" / "curated"
    build = root / "data" / "build"
    for d in [
        raw / "bhavcopy", raw / "indexdaily", raw / "indexhist", raw / "pressreleases" / "pdf",
        raw / "constituents", raw / "corporate_actions", raw / "nse_lists", raw / "held",
        curated, build / "membership", build / "identity",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(paths, "ROOT", root)
    monkeypatch.setattr(paths, "DATA", root / "data")
    monkeypatch.setattr(paths, "RAW", raw)
    monkeypatch.setattr(paths, "CURATED", curated)
    monkeypatch.setattr(paths, "BUILD", build)
    monkeypatch.setattr(paths, "BHAV_RAW", raw / "bhavcopy")
    monkeypatch.setattr(paths, "INDEX_DAILY_RAW", raw / "indexdaily")
    monkeypatch.setattr(paths, "INDEX_HIST_RAW", raw / "indexhist")
    monkeypatch.setattr(paths, "PRESS_RAW", raw / "pressreleases")
    monkeypatch.setattr(paths, "HELD", raw / "held")
    monkeypatch.setattr(paths, "MANIFEST", raw / "manifest.csv")
    return root


def test_check_curated_provenance_handles_semicolon_and_shorthand(synthetic_env):
    root = synthetic_env
    p1 = root / "data" / "raw" / "pressreleases" / "pdf" / "a.pdf"
    p1.write_bytes(b"pdf1")
    pd.DataFrame([{
        "index_key": "NIFTY50", "date": "2026-01-01", "symbol": "AAA", "action": "IN",
        "source": "data/raw/pressreleases/pdf/a.pdf; b.pdf",
    }]).to_csv(paths.CURATED / "index_events_press.csv", index=False)

    res = verify.check_curated_provenance()
    assert res.status == "FAIL"
    assert ("index_events_press.csv", "data/raw/pressreleases/pdf/b.pdf") in res.details

    (root / "data" / "raw" / "pressreleases" / "pdf" / "b.pdf").write_bytes(b"pdf2")
    assert verify.check_curated_provenance().status == "PASS"


def test_check_membership_enforces_hierarchy(synthetic_env, monkeypatch):
    d = pd.bdate_range("2025-01-01", periods=3)
    monkeypatch.setattr(verify.calendar, "trading_days", lambda: d)
    monkeypatch.setattr(membership, "ANCHORED", {})

    pd.DataFrame([
        {"sec_id": "S1", "symbol": "AAA", "from_date": d[0], "to_date": d[-1]},
        {"sec_id": "S2", "symbol": "BBB", "from_date": d[0], "to_date": d[-1]},
    ]).to_parquet(paths.BUILD / "identity" / "segments.parquet")

    pd.DataFrame([
        {"index_key": "NIFTY50", "from_date": d[0], "to_date": d[-1], "status": "VERIFIED", "reason": ""},
        {"index_key": "NIFTY100", "from_date": d[0], "to_date": d[-1], "status": "VERIFIED", "reason": ""},
    ]).to_parquet(paths.BUILD / "membership" / "coverage.parquet")

    # S1 in NIFTY50 but missing from NIFTY100 -> FAIL
    pd.DataFrame([
        {"index_key": "NIFTY50", "sec_id": "S1", "from_date": d[0], "to_date": d[-1]},
        {"index_key": "NIFTY100", "sec_id": "S2", "from_date": d[0], "to_date": d[-1]},
    ]).to_parquet(paths.BUILD / "membership" / "intervals.parquet")
    assert verify.check_membership().status == "FAIL"

    # Fix NIFTY100 to include S1 (with NaT from_date/to_date) and test half-open [from_date, to_date) -> PASS
    pd.DataFrame([
        {"index_key": "NIFTY50", "sec_id": "S1", "from_date": pd.NaT, "to_date": pd.NaT},
        {"index_key": "NIFTY100", "sec_id": "S1", "from_date": pd.NaT, "to_date": pd.NaT},
        {"index_key": "NIFTY100", "sec_id": "S2", "from_date": d[0], "to_date": d[-1]},
        {"index_key": "NIFTY50", "sec_id": "S2", "from_date": d[0], "to_date": d[1]},  # excluded on d[1], so NOT in NIFTY50 on d[1]
    ]).to_parquet(paths.BUILD / "membership" / "intervals.parquet")
    assert verify.check_membership().status == "PASS"


def test_coverage_baseline_detects_loss_and_gain(synthetic_env):
    cov = lambda to: pd.DataFrame([{"index_key": "NIFTY50", "from_date": pd.Timestamp("2020-01-01"),
                                    "to_date": pd.Timestamp(to), "status": "VERIFIED", "reason": ""}])
    cov("2020-01-10").to_parquet(paths.BUILD / "membership" / "coverage.parquet")
    assert verify.check_coverage_baseline().status == "FAIL"      # no baseline yet
    verify.write_coverage_baseline()
    assert verify.check_coverage_baseline().status == "PASS"
    cov("2020-01-09").to_parquet(paths.BUILD / "membership" / "coverage.parquet")   # one day lost
    r = verify.check_coverage_baseline()
    assert r.status == "FAIL" and r.details[0] == ("NIFTY50", 10, 9)
    cov("2020-01-12").to_parquet(paths.BUILD / "membership" / "coverage.parquet")   # two days gained
    assert verify.check_coverage_baseline().status == "WARN"


def _ratchet_env(n_oor=1, unexplained=("AAA|2020-01-02",), rejected=(("S1", "2020-02-03"),)):
    (paths.BUILD / "bhavcopy").mkdir(parents=True, exist_ok=True)
    (paths.BUILD / "actions").mkdir(parents=True, exist_ok=True)
    (paths.BUILD / "identity").mkdir(parents=True, exist_ok=True)
    rows = [{"date": pd.Timestamp("2020-01-02"), "symbol": "X", "series": "EQ", "open": 10.0, "high": 11.0,
             "low": 9.0, "close": 12.0 if i < n_oor else 10.0, "volume": 5.0} for i in range(3)]
    for i, r in enumerate(rows):
        r["symbol"] = f"X{i}"
    pd.DataFrame(rows).to_parquet(paths.BUILD / "bhavcopy" / "bhavcopy_2020.parquet")
    pd.DataFrame([{"sec_id": "S9", "symbol": k.split("|")[0], "date": k.split("|")[1], "series": "EQ", "r": 0.4,
                   "class": "UNEXPLAINED"} for k in unexplained] +
                 [{"sec_id": "S8", "symbol": "ZZZ", "date": "2020-03-03", "series": "EQ", "r": 0.4, "class": "PRE_COVERAGE"}]
                 ).to_csv(paths.BUILD / "adjustment_gaps.csv", index=False)
    pd.DataFrame([{"sec_id": s, "eff_date": d, "applied_date": None, "decision": "REJECTED", "share_factor": 2.0,
                   "observed_ratio": 1.0} for s, d in rejected] +
                 [{"sec_id": "S1", "eff_date": "2021-01-01", "applied_date": None, "decision": "KEPT", "share_factor": 2.0,
                   "observed_ratio": 2.0}]).to_parquet(paths.BUILD / "actions" / "gate_log.parquet")
    pd.DataFrame([{"sec_id": s, "last_symbol": "BBB"} for s in {"S1", "S2"}]).to_parquet(
        paths.BUILD / "identity" / "securities.parquet")


def test_ratchet_baseline_fails_on_any_rise_and_warns_on_fall(synthetic_env):
    _ratchet_env()
    assert verify.check_ratchet_baseline().status == "FAIL"        # no baseline yet
    verify.write_ratchet_baseline()
    assert verify.check_ratchet_baseline().status == "PASS"
    _ratchet_env(n_oor=2)                                           # one more out-of-range close
    assert verify.check_ratchet_baseline().status == "FAIL"
    _ratchet_env(unexplained=("AAA|2020-01-02", "CCC|2020-01-03"))  # a new unexplained move
    r = verify.check_ratchet_baseline()
    assert r.status == "FAIL" and ("new_unexplained", "CCC|2020-01-03") in r.details
    _ratchet_env(rejected=(("S1", "2020-02-03"), ("S2", "2020-04-01")))   # a newly rejected share action
    r = verify.check_ratchet_baseline()
    assert r.status == "FAIL" and ("new_rejected", "BBB|2020-04-01") in r.details
    _ratchet_env(n_oor=0)                                           # improvement only
    assert verify.check_ratchet_baseline().status == "WARN"
