from unittest.mock import patch

import pytest

from nseuniverse import fetch


def test_fetch_press_releases_suffixed_and_since_year(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch.paths, "ROOT", tmp_path)
    monkeypatch.setattr(fetch.paths, "PRESS_RAW", tmp_path / "press")
    monkeypatch.setattr(fetch.paths, "MANIFEST", tmp_path / "manifest.csv")
    monkeypatch.setattr(fetch.paths, "ABSENT", tmp_path / "absent.csv")

    html = (
        b'<a href="/Press_Release/ind_prs01012019.pdf">2019</a>'
        b'<a href="/Press_Release/ind_prs15032024_1.pdf">2024_1</a>'
        b'<a href="/Press_Release/ind_prs15032024_2.pdf">2024_2</a>'
    )

    seen_urls = []

    def fake_get(url, timeout=45):
        seen_urls.append(url)
        if url.endswith("/press-release"):
            return 200, html
        return 200, b"%PDF-1.4 fake"

    with patch.object(fetch, "_get", side_effect=fake_get):
        counts = fetch.fetch_press_releases(workers=1, since_year=2020)

    assert counts == {"fetched": 2}
    assert any("ind_prs15032024_1.pdf" in u for u in seen_urls)
    assert any("ind_prs15032024_2.pdf" in u for u in seen_urls)
    assert not any("ind_prs01012019.pdf" in u for u in seen_urls)


def test_fetch_constituent_rejects_html(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch.paths, "ROOT", tmp_path)
    monkeypatch.setattr(fetch.paths, "RAW", tmp_path / "raw")
    monkeypatch.setattr(fetch.paths, "MANIFEST", tmp_path / "manifest.csv")

    with patch.object(fetch, "_get", return_value=(200, b"<html><body>404</body></html>")):
        with pytest.raises(ValueError, match="invalid constituent CSV"):
            fetch.fetch_constituent("nifty50", date_str="2026-11-19")


def test_fetch_constituent_valid_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch.paths, "ROOT", tmp_path)
    monkeypatch.setattr(fetch.paths, "RAW", tmp_path / "raw")
    monkeypatch.setattr(fetch.paths, "MANIFEST", tmp_path / "manifest.csv")

    csv_bytes = b"Company Name,Industry,Symbol,Series,ISIN Code\nReliance Industries Ltd.,Oil,RELIANCE,EQ,INE002A01018\n"
    with patch.object(fetch, "_get", return_value=(200, csv_bytes)):
        dest = fetch.fetch_constituent("nifty50", date_str="2026-11-19")

    assert dest.exists()
    assert dest.read_bytes() == csv_bytes
    assert (tmp_path / "manifest.csv").exists()


def test_market_sources_use_the_session_calendar_and_validate_bodies(tmp_path, monkeypatch):
    import datetime as dt
    from nseuniverse import fetch, paths
    monkeypatch.setattr(paths, "ROOT", tmp_path); monkeypatch.setattr(paths, "RAW", tmp_path / "raw")
    monkeypatch.setattr(paths, "BHAV_RAW", tmp_path / "raw" / "bhavcopy")
    monkeypatch.setattr(paths, "MARKET_RAW", tmp_path / "raw" / "market")
    monkeypatch.setattr(paths, "MANIFEST", tmp_path / "raw" / "manifest.csv")
    monkeypatch.setattr(paths, "ABSENT", tmp_path / "raw" / "absent.csv")
    d = paths.BHAV_RAW / "legacy" / "2020"; d.mkdir(parents=True)
    (d / "cm03JAN2020bhav.csv.zip").write_bytes(b"x")                  # a session
    (d / "cm04JAN2020bhav.csv.zip").write_bytes(b"x")                  # a (special) Saturday session
    assert fetch.session_days() == {dt.date(2020, 1, 3), dt.date(2020, 1, 4)}
    calls = []

    def fake_get(url, retries=4):
        calls.append(url)
        if "20200103" in url or "03012020" in url:
            return 200, b"Security Wise Delivery Position - Compulsory Rolling Settlement\n10,MTO,03012020,1,1\n"
        return 200, b"<!DOCTYPE html><html>not a file</html>"          # NSE answers a missing day with HTTP 200 + HTML
    monkeypatch.setattr(fetch, "_get", fake_get)
    res = fetch.fetch_range("delivery_mto", dt.date(2020, 1, 1), dt.date(2020, 1, 6), workers=1)
    assert res == {"fetched": 1, "absent": 1}                           # 2 session days only; the HTML body is not stored
    assert len(calls) == 2 and all("MTO_" in u for u in calls)
    assert (paths.MARKET_RAW / "delivery" / "2020" / "MTO_03012020.DAT").exists()
    assert not (paths.MARKET_RAW / "delivery" / "2020" / "MTO_04012020.DAT").exists()
    assert "MTO_03012020.DAT" in paths.MANIFEST.read_text()
    assert fetch.fetch_range("delivery_mto", dt.date(2020, 1, 1), dt.date(2020, 1, 6), workers=1) == {"have": 1, "known-absent": 1}


def test_reconcile_manifest_lists_market_files_whose_manifest_write_failed(tmp_path, monkeypatch):
    import csv
    from nseuniverse import fetch, paths
    monkeypatch.setattr(paths, "ROOT", tmp_path); monkeypatch.setattr(paths, "RAW", tmp_path / "raw")
    monkeypatch.setattr(paths, "MARKET_RAW", tmp_path / "raw" / "market")
    monkeypatch.setattr(paths, "MANIFEST", tmp_path / "raw" / "manifest.csv")
    f = paths.MARKET_RAW / "delivery" / "2020" / "MTO_03012020.DAT"; f.parent.mkdir(parents=True)
    f.write_bytes(b"Security Wise Delivery Position")
    assert fetch.reconcile_manifest() == 1
    rows = list(csv.DictReader(open(paths.MANIFEST, newline="")))
    assert rows[0]["path"] == "raw/market/delivery/2020/MTO_03012020.DAT" and rows[0]["url"].endswith("MTO_03012020.DAT")
    assert fetch.reconcile_manifest() == 0                          # already listed

    import datetime as dt
    monkeypatch.setattr(fetch, "_get", lambda url, retries=4: (200, b"Security Wise Delivery Position x"))
    assert fetch.fetch_one(fetch.SOURCES["delivery_mto"], dt.date(2020, 1, 6), {}) == "fetched"
    assert "MTO_06012020" not in paths.MANIFEST.read_text()           # queued, not yet written
    real = fetch._append_many

    def busy(*a, **k):
        raise RuntimeError("could not lock")
    monkeypatch.setattr(fetch, "_append_many", busy)
    assert fetch.flush_queue() == 0 and len(fetch._queue["manifest"]) == 1   # a failed write keeps the rows
    monkeypatch.setattr(fetch, "_append_many", real)
    assert fetch.flush_queue() == 1 and "MTO_06012020" in paths.MANIFEST.read_text()


def test_derivatives_bhavcopy_sources_split_at_2024_07_05_and_reconcile_reads_their_dates(tmp_path, monkeypatch):
    import datetime as dt
    from nseuniverse import fetch, paths
    s_old, s_new = fetch.SOURCES["fo_bhav_legacy"], fetch.SOURCES["fo_bhav_udiff"]
    assert s_old.last_fn() == dt.date(2024, 7, 5) and s_new.first == dt.date(2024, 7, 5)
    assert s_old.url(dt.date(2015, 10, 20)).endswith("/DERIVATIVES/2015/OCT/fo20OCT2015bhav.csv.zip")
    assert s_new.url(dt.date(2025, 11, 20)).endswith("BhavCopy_NSE_FO_0_0_0_20251120_F_0000.csv.zip")
    monkeypatch.setattr(paths, "ROOT", tmp_path); monkeypatch.setattr(paths, "RAW", tmp_path / "raw")
    monkeypatch.setattr(paths, "MARKET_RAW", tmp_path / "raw" / "market"); monkeypatch.setattr(paths, "MANIFEST", tmp_path / "raw" / "manifest.csv")
    for sub, name in (("legacy", "fo20OCT2015bhav.csv.zip"), ("udiff", "BhavCopy_NSE_FO_0_0_0_20251120_F_0000.csv.zip")):
        f = paths.MARKET_RAW / "fobhav" / sub / "2015" / name; f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(b"PK")
    assert fetch.reconcile_manifest() == 2
    text = paths.MANIFEST.read_text()
    assert "/DERIVATIVES/2015/OCT/fo20OCT2015bhav.csv.zip" in text and "BhavCopy_NSE_FO_0_0_0_20251120_F_0000.csv.zip" in text


def test_dedupe_manifest_keeps_the_first_row_and_every_other_line_untouched(tmp_path, monkeypatch):
    from nseuniverse import fetch, paths
    monkeypatch.setattr(paths, "MANIFEST", tmp_path / "manifest.csv")
    head = b"path,url,sha256,bytes,fetched_utc" + bytes([13, 10])
    odd = "a,u,h,1,2026 \x96 estimate".encode("latin-1") + bytes([13, 10])        # a non-UTF-8 byte must survive
    paths.MANIFEST.write_bytes(head + odd + b"b,u,h,2,t" + bytes([13, 10]) + b"a,u,h,1,later" + bytes([13, 10]) + b"b,u,h,2,t" + bytes([13, 10]))
    assert fetch.dedupe_manifest() == 2
    assert paths.MANIFEST.read_bytes() == head + odd + b"b,u,h,2,t" + bytes([13, 10])
    assert fetch.dedupe_manifest() == 0


def test_impact_cost_source_is_monthly_validates_bodies_and_reconciles(tmp_path, monkeypatch):
    import datetime as dt
    from nseuniverse import fetch, paths
    monkeypatch.setattr(paths, "ROOT", tmp_path); monkeypatch.setattr(paths, "RAW", tmp_path / "raw")
    monkeypatch.setattr(paths, "MARKET_RAW", tmp_path / "raw" / "market")
    monkeypatch.setattr(paths, "MANIFEST", tmp_path / "raw" / "manifest.csv")
    monkeypatch.setattr(paths, "ABSENT", tmp_path / "raw" / "absent.csv")
    calls = []

    def fake_get(url, retries=4):
        calls.append(url)
        if "JAN2024" in url:
            return 200, b"10,JAN,2024,000001\n20,AAA,EQ,INE001A01010,1,0.12\n"
        return 200, b"<!DOCTYPE html><html>not found</html>"
    monkeypatch.setattr(fetch, "_get", fake_get)
    res = fetch.fetch_range("impact_cost", dt.date(2024, 1, 15), dt.date(2024, 2, 20), workers=1)
    assert res == {"fetched": 1, "absent": 1}
    assert len(calls) == 2 and calls[0].endswith("C_CATG_JAN2024.T01") and calls[1].endswith("C_CATG_FEB2024.T01")
    assert (paths.MARKET_RAW / "impactcost" / "2024" / "C_CATG_JAN2024.T01").exists()
    assert not (paths.MARKET_RAW / "impactcost" / "2024" / "C_CATG_FEB2024.T01").exists()
    f = paths.MARKET_RAW / "impactcost" / "2024" / "C_CATG_MAR2024.T01"
    f.write_bytes(b"10,MAR,2024,000001\n20,AAA,EQ,INE001A01010,1,0.10\n")
    assert fetch.reconcile_manifest() == 1
    assert "C_CATG_MAR2024.T01" in paths.MANIFEST.read_text(encoding="latin-1")


def test_mii_security_source_is_session_only_validates_gzip_and_reconciles(tmp_path, monkeypatch):
    import datetime as dt
    import gzip
    from nseuniverse import fetch, paths
    monkeypatch.setattr(paths, "ROOT", tmp_path); monkeypatch.setattr(paths, "RAW", tmp_path / "raw")
    monkeypatch.setattr(paths, "MARKET_RAW", tmp_path / "raw" / "market")
    monkeypatch.setattr(paths, "MANIFEST", tmp_path / "raw" / "manifest.csv")
    monkeypatch.setattr(paths, "ABSENT", tmp_path / "raw" / "absent.csv")
    monkeypatch.setattr(paths, "BHAV_RAW", tmp_path / "raw" / "bhavcopy")
    for d in ("20240205", "20240206"):
        f = paths.BHAV_RAW / "udiff" / "2024" / f"BhavCopy_NSE_CM_0_0_0_{d}_F_0000.csv.zip"
        f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(b"x")
    body = gzip.compress(b"FinInstrmId,TckrSymb,IssdCptl,FreeFltCptl\n1,AAA,100,60\n")

    def fake_get(url, retries=4):
        return (200, body) if "05022024" in url else (200, b"<html>no</html>")
    monkeypatch.setattr(fetch, "_get", fake_get)
    assert fetch.SOURCES["mii_security"].first == dt.date(2024, 2, 5)
    res = fetch.fetch_range("mii_security", dt.date(2024, 2, 1), dt.date(2024, 2, 8), workers=1)
    assert res == {"fetched": 1, "absent": 1}                      # only the two session days are tried; HTML body rejected
    f = paths.MARKET_RAW / "mii" / "2024" / "NSE_CM_security_05022024.csv.gz"
    assert f.exists() and gzip.decompress(f.read_bytes()).startswith(b"FinInstrmId")
    g = paths.MARKET_RAW / "mii" / "2024" / "NSE_CM_security_07022024.csv.gz"
    g.write_bytes(body)
    assert fetch.reconcile_manifest() == 1
    assert "NSE_CM_security_07022024.csv.gz" in paths.MANIFEST.read_text(encoding="latin-1")
