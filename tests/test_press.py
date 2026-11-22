"""Offline synthetic tests for nseuniverse.press."""
import pytest

from nseuniverse import indices, press


def test_index_events_and_extract_all_events(tmp_path, monkeypatch):
    monkeypatch.setattr(indices, "name_map", lambda: {
        "NIFTY50": "NIFTY50",
        "NIFTYNEXT50": "NIFTYNEXT50",
    })
    txt = """PRESS RELEASE
Mumbai, February 21, 2025
These changes shall become effective from March 28, 2025 (close of March 27, 2025).
Note: Also applicable to Nifty 50 Equal Weight.
a) Nifty 50
The following companies are being excluded:
Sr. No. Company Name Symbol
1 Bharat Petroleum Corporation Ltd. BPCL
The following companies are being included:
Sr. No. Company Name Symbol
1 Jio Financial Services Ltd. JIOFIN
"""
    p = tmp_path / "ind_prs21022025.txt"
    p.write_text(txt, encoding="utf-8")

    ev = press.index_events(p, "Nifty 50")
    assert len(ev) == 1
    assert ev[0]["excluded"] == ["BPCL"]
    assert ev[0]["included"] == ["JIOFIN"]

    df = press.extract_all_events(tmp_path, since_date="2020-09-01", known_symbols={"BPCL", "JIOFIN"})
    assert len(df) == 2
    assert set(df["action"]) == {"OUT", "IN"}
    assert set(df["symbol"]) == {"BPCL", "JIOFIN"}
    assert "also applicable to" in df["flag"].iloc[0]


def test_extract_text_rewrites_only_empty(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdfs, out = tmp_path / "pdf", tmp_path / "txt"
    pdfs.mkdir()
    for name, body in (("ind_prs01012020.pdf", "Nifty 50 being included ABCD " * 10), ("ind_prs02012020.pdf", "")):
        doc = pymupdf.open(); page = doc.new_page()
        if body:
            page.insert_text((72, 72), body)
        doc.save(pdfs / name); doc.close()
    out.mkdir()
    (out / "ind_prs01012020.txt").write_text("x" * 500)          # already good: must be left alone
    r = press.extract_text(pdfs, out, only_empty=True)
    assert r["written"] == 1 and r["still_empty"] == ["ind_prs02012020.pdf"]
    assert (out / "ind_prs01012020.txt").read_text() == "x" * 500
