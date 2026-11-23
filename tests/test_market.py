"""Market-activity parsers, the build step and the API on small synthetic files."""
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


def test_parse_band_changes_and_sec_list_and_ban():
    bc = market.parse_band_changes(b"Sr. No,Symbol,Series,Security Name,From,To\n1,PANSARI,EQ,PANSARI LTD,10,5\n", D)
    assert bc.iloc[0].tolist()[1:5] == ["PANSARI", "EQ", "10", "5"]
    nil = market.parse_band_changes(b"Sr. No,Symbol,Series,Security Name,From,To" + bytes([10]) + b"1,Nil,,,," + bytes([10]), D)
    assert nil.empty                                                          # "Nil" = no change that day
    sl = market.parse_sec_list(b'Symbol,Series,Security Name,Band,Remarks\nABAN,BE,ABAN LTD,2,"-"\nANKIT,BZ,ANKIT LTD,2,"GSM STAGE - IV"\n', D)
    assert sl.remarks.tolist() == ["", "GSM STAGE - IV"] and sl.band.tolist() == ["2", "2"]
    assert market.parse_secban(b"Securities in Ban For Trade Date 20-OCT-2020: NIL\n", D).empty
    ban = market.parse_secban(b"Securities in Ban For Trade Date 20-OCT-2020:\n1,IDEA\n2,SAIL\n", D)
    assert ban.symbol.tolist() == ["IDEA", "SAIL"] and (ban.date == D).all()


@pytest.fixture()
def market_build(tmp_path, monkeypatch):
    raw = tmp_path / "raw" / "market"
    for kind, name, body in [("delivery", "MTO_20102020.DAT", MTO),
                             ("bandchanges", "eq_band_changes_20102020.csv", b"Sr. No,Symbol,Series,Security Name,From,To\n1,AAA,EQ,A LTD,20,10\n"),
                             ("seclist", "sec_list_21102020.csv", b'Symbol,Series,Security Name,Band,Remarks\nAAA,EQ,A LTD,10,"ASM LTD STAGE I"\n'),
                             ("fosecban", "fo_secban_20102020.csv", b"Securities in Ban For Trade Date 20-OCT-2020:\n1,AAA\n"),
                             ("fosecban", "fo_secban_21102020.csv", b"Securities in Ban For Trade Date 21-OCT-2020: NIL\n")]:
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
    assert info["fo_ban"]["rows"] == 1 and info["sec_list"]["rows"] == 1


def test_api_delivery_price_band_asm_and_ban(market_build):
    d = api.delivery("AAA", "2020-10-20", "2020-10-21")
    assert d.deliv_qty.tolist() == [400] and d.deliv_pct.tolist() == [40.0]
    assert api.price_band("AAA", "2020-10-21")["band"] == "10"                 # from the security list
    assert api.price_band("AAA", "2020-10-21")["remarks"] == "ASM LTD STAGE I"
    assert api.price_band("AAA", "2020-10-20")["band"] == "10"                 # no list that day: last recorded change
    with pytest.raises(api.CoverageError):
        api.price_band("BBB", "2020-10-20")                                    # no change recorded, no list: refused
    assert api.asm_gsm("2020-10-21").symbol.tolist() == ["AAA"]
    with pytest.raises(api.CoverageError):
        api.asm_gsm("2020-10-20")
    assert api.fo_ban("2020-10-20").symbol.tolist() == ["AAA"]
    assert api.fo_ban("2020-10-21").empty                                      # NIL day: empty, not an error
    with pytest.raises(api.CoverageError):
        api.fo_ban("2020-10-22")                                               # no file: refused


def test_header_variants_are_read_and_unknown_layouts_are_refused_not_guessed():
    nl = bytes([10])
    v = market.parse_band_changes(b"Sr. No.,Symbol,Series,Security Name,From ,To," + nl + b"1,AAA,EQ,A LTD,20,10," + nl, D)
    assert v.iloc[0].tolist()[1:5] == ["AAA", "EQ", "20", "10"]
    r = market.parse_band_changes(b"Sr. No,Symbol,Series,Security Name,From,To" + bytes([13]) + b"1,BBB,EQ,B LTD,10,5" + bytes([13]), D)
    assert r.symbol.tolist() == ["BBB"]                                         # old Mac-style line ends
    with pytest.raises(market.UnknownLayout):
        market.parse_band_changes(b"Sr. No,Symbol,Series,Min Band or no band,Max Band or no band" + nl + b"1,AAA,EQ,5,10" + nl, D)
    extra = market.parse_sec_list(b"Symbol,Series,Security Name,Band,Remarks,,Check" + nl + b"AAA,EQ,A,5,-,," + nl, D)
    assert extra.band.tolist() == ["5"] and extra.remarks.tolist() == [""]
