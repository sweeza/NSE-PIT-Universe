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


def test_check_manifest_flags_unlisted_constituents_and_held(synthetic_env):
    root = synthetic_env
    (root / "data" / "raw" / "held" / "old.xls").write_bytes(b"held")
    f = root / "data" / "raw" / "constituents" / "ind_nifty50list.csv"
    f.write_bytes(b"Symbol\nAAA\n")
    (paths.MANIFEST).write_text("path,url,sha256,bytes,fetched_utc\n")
    res = verify.check_manifest()
    assert res.status == "FAIL"
    assert "ind_nifty50list.csv" in res.details
    assert "old.xls" in res.details   # held inputs must be in the manifest too

    sha = hashlib.sha256(b"Symbol\nAAA\n").hexdigest()
    (paths.MANIFEST).write_text(
        f"path,url,sha256,bytes,fetched_utc\n"
        f"data/raw/constituents/ind_nifty50list.csv,http://x,{sha},11,2026-01-01\n"
    )
    assert verify.check_manifest().status == "FAIL"   # held/old.xls is still unlisted
    shah = hashlib.sha256(b"held").hexdigest()
    (paths.MANIFEST).write_text(
        f"path,url,sha256,bytes,fetched_utc\n"
        f"data/raw/constituents/ind_nifty50list.csv,http://x,{sha},11,2026-01-01\n"
        f"data/raw/held/old.xls,held,{shah},4,unknown\n"
    )
    assert verify.check_manifest().status == "PASS"


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
