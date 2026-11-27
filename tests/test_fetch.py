from unittest.mock import patch

import pytest

from nseuniverse import fetch


def test_fetch_constituent_rejects_html(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch.paths, "ROOT", tmp_path)
    monkeypatch.setattr(fetch.paths, "RAW", tmp_path / "raw")
    monkeypatch.setattr(fetch.paths, "MANIFEST", tmp_path / "manifest.csv")

    with patch.object(fetch, "_get", return_value=(200, b"<html><body>404</body></html>")):
        with pytest.raises(ValueError, match="invalid constituent CSV"):
            fetch.fetch_constituent("nifty50", date_str="2026-11-19")


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
