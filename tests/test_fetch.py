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
