"""Delivery parser, the build step and the API on small synthetic files."""
import pandas as pd
import pytest

from nseuniverse import api, indices, market, paths

D = pd.Timestamp("2020-10-20")

MTO = (b"Security Wise Delivery Position - Compulsory Rolling Settlement\n"
       b"10,MTO,20102020,2432401686,0003520\n"
       b"Trade Date <20-OCT-2020>,Settlement Type <N>\n"
       b"Record Type,Sr No,Name of Security,Quantity Traded,Deliverable Quantity(gross across client level),% of Deliverable Quantity to Traded Quantity\n"
       b"20,1,AAA,EQ,1000,400,40.00\n"
       b"20,2,BBB,BE,50,50,100.00\n"
       b"20,3,CCC,EQ,10,,\n")


def test_parse_mto_reads_only_data_rows_and_keeps_missing_numbers_null():
    df = market.parse_mto(MTO, D)
    assert df.symbol.tolist() == ["AAA", "BBB", "CCC"] and df.series.tolist() == ["EQ", "BE", "EQ"]
    assert df.loc[0, ["traded_qty", "deliv_qty", "deliv_pct"]].tolist() == [1000, 400, 40.0]
    assert pd.isna(df.loc[2, "deliv_qty"]) and (df.date == D).all()




@pytest.fixture()
def market_build(tmp_path, monkeypatch):
    raw = tmp_path / "raw" / "market"
    for kind, name, body in [("delivery", "MTO_20102020.DAT", MTO)]:
        d = raw / kind / "2020"; d.mkdir(parents=True, exist_ok=True); (d / name).write_bytes(body)
    b = tmp_path / "build"; (b / "identity").mkdir(parents=True)
    monkeypatch.setattr(paths, "MARKET_RAW", raw); monkeypatch.setattr(paths, "BUILD", b)
    monkeypatch.setattr(indices, "name_map", lambda: {})
    t = pd.DataFrame([(D, "AAA", "EQ", "S1", 1000.0), (D, "BBB", "BE", "S2", 50.0), (D, "CCC", "EQ", "S3", 11.0),
                      (D + pd.Timedelta(days=1), "AAA", "EQ", "S1", 5.0)], columns=["date", "symbol", "series", "sec_id", "volume"])
    info = market.build(b / "market", t)
    pd.DataFrame({"sec_id": ["S1", "S2", "S3"], "first_symbol": ["AAA", "BBB", "CCC"], "last_symbol": ["AAA", "BBB", "CCC"],
                  "first_date": D, "last_date": D + pd.Timedelta(days=1), "n_days": 2, "isin_last": None, "is_equity": True}
                 ).to_parquet(b / "identity" / "securities.parquet")
    pd.DataFrame({"sec_id": ["S1", "S2", "S3"], "symbol": ["AAA", "BBB", "CCC"], "from_date": D,
                  "to_date": D + pd.Timedelta(days=1), "isins": ""}).to_parquet(b / "identity" / "symbol_history.parquet")
    api.clear_cache()
    yield info
    api.clear_cache()


def test_build_attaches_securities_and_checks_delivery_against_bhavcopy_volume(market_build):
    info = market_build
    assert info["delivery"] == {"rows": 3, "unattached": 0}
    assert info["delivery_volume_match"] == {"compared": 3, "equal": 2}      # CCC: file 10, bhavcopy 11


def test_api_delivery_returns_rows_and_refuses_an_empty_range(market_build):
    d = api.delivery("AAA", "2020-10-20", "2020-10-21")
    assert d.deliv_qty.tolist() == [400] and d.deliv_pct.tolist() == [40.0]
    with pytest.raises(api.CoverageError):
        api.delivery("AAA", "2020-11-01", "2020-11-05")
