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


def _zip(name: str, body: bytes) -> bytes:
    import io, zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, body)
    return b.getvalue()


def test_parse_fo_bhav_both_layouts_keep_stock_contracts_only():
    nl = bytes([10])
    legacy = _zip("fo.csv", b"INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN" + nl + b"FUTIDX,NIFTY,28-JAN-2020,0,XX,1" + nl +
                  b"FUTSTK,AAA,28-JAN-2020,0,XX,1" + nl + b"OPTSTK,BBB,28-JAN-2020,10,CE,1" + nl + b"FUTSTK,BBB,28-JAN-2020,0,XX,1" + nl)
    x = market.parse_fo_bhav(legacy, D)
    assert x.symbol.tolist() == ["AAA", "BBB"] and x.fut.tolist() == [True, True] and x.opt.tolist() == [False, True]
    udiff = _zip("u.csv", b"FinInstrmTp,TckrSymb,XpryDt" + nl + b"IDF,BANKNIFTY,x" + nl + b"STO,CCC,x" + nl)
    y = market.parse_fo_bhav(udiff, D)
    assert y.symbol.tolist() == ["CCC"] and y.opt.tolist() == [True] and y.fut.tolist() == [False]
    with pytest.raises(market.UnknownLayout):
        market.parse_fo_bhav(_zip("z.csv", b"A,B" + nl + b"1,2" + nl), D)


def test_fo_eligible_api_and_build_merge_the_overlap_day(market_build, tmp_path):
    nl = bytes([10])
    root = paths.MARKET_RAW / "fobhav"
    for sub, name, body in [("legacy", "fo20OCT2020bhav.csv.zip", _zip("a.csv", b"INSTRUMENT,SYMBOL" + nl + b"FUTSTK,AAA" + nl)),
                            ("udiff", "BhavCopy_NSE_FO_0_0_0_20201020_F_0000.csv.zip", _zip("b.csv", b"FinInstrmTp,TckrSymb" + nl + b"STO,AAA" + nl))]:
        (root / sub / "2020").mkdir(parents=True, exist_ok=True); (root / sub / "2020" / name).write_bytes(body)
    t = pd.DataFrame([(D, "AAA", "EQ", "S1", 1000.0)], columns=["date", "symbol", "series", "sec_id", "volume"])
    info = market.build(paths.BUILD / "market", t)
    assert info["fo_stocks"] == {"rows": 1, "unattached": 0}                      # one row per date and symbol
    api.clear_cache()
    e = api.fo_eligible("2020-10-20")
    assert e.symbol.tolist() == ["AAA"] and e.fut.tolist() == [True] and e.opt.tolist() == [True]
    with pytest.raises(api.CoverageError):
        api.fo_eligible("2020-10-21")


def test_parse_deals_all_layouts_and_unknown_layout():
    nl = bytes([10])
    bom = b"\xef\xbb\xbf"
    bulk = (bom + b'"Date ","Symbol ","Security Name ","Client Name ","Buy / Sell ","Quantity Traded ","Trade Price / Wght. Avg. Price ","Remarks "' + nl +
            b'"20-OCT-2020","AAA","A LTD","BIG FUND","BUY","1,25,000","50.25","-"' + nl)
    b1 = market.parse_deals(bulk, "bulk")
    assert b1.symbol.tolist() == ["AAA"] and b1.quantity.tolist() == [125000] and b1.price.tolist() == [50.25]
    assert b1.remarks.tolist() == [""] and b1.kind.tolist() == ["bulk"]

    block_daily = b"Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price" + nl + b"20-OCT-2020,AAA,A LTD,FUND X,SELL,50000,51.00" + nl
    b2 = market.parse_deals(block_daily, "block")
    assert b2.buy_sell.tolist() == ["SELL"] and b2.remarks.tolist() == [""] and b2.kind.tolist() == ["block"]

    short = bom + b'"Date ","Symbol ","Security Name ","Quantity "' + nl + b'"20-OCT-2020","AAA","A LTD","10,000"' + nl + b'"21-OCT-2020","AAA","A LTD","-"' + nl
    s1 = market.parse_deals(short, "short")
    assert s1.quantity.iloc[0] == 10000 and pd.isna(s1.quantity.iloc[1]) and s1.price.isna().all() and s1.kind.tolist() == ["short", "short"]

    with pytest.raises(market.UnknownLayout):
        market.parse_deals(b"Date,Ticker,Qty" + nl + b"20-OCT-2020,AAA,100" + nl, "bulk")


def test_deals_build_dedupes_and_api_enforces_coverage(market_build):
    nl = bytes([10])
    ddir = paths.MARKET_RAW / "deals"
    ddir.mkdir(parents=True, exist_ok=True)
    row = b"20-OCT-2020,AAA,A LTD,FUND X,BUY,10000,50.00,-" + nl
    hdr = b"Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks" + nl
    (ddir / "bulk_20201001_20201021.csv").write_bytes(hdr + row)
    (ddir / "bulk_20201020.csv").write_bytes(hdr + row)                     # duplicate row in daily snapshot
    (ddir / "short_20201001_20201021.csv").write_bytes(b"Date,Symbol,Security Name,Quantity" + nl + b"21-OCT-2020,AAA,A LTD,500" + nl)
    (ddir / "block_bad.csv").write_bytes(b"Wrong,Header" + nl + b"1,2" + nl)

    t = pd.DataFrame([(D, "AAA", "EQ", "S1", 1000.0), (D + pd.Timedelta(days=1), "AAA", "EQ", "S1", 5.0)],
                     columns=["date", "symbol", "series", "sec_id", "volume"])
    info = market.build(paths.BUILD / "market", t)
    assert info["deals"] == {"rows": 2, "unattached": 0}
    assert "block_bad.csv" in info["skipped_unknown_layout"]
    api.clear_cache()

    res = api.deals("AAA", "2020-10-20", "2020-10-21")
    assert len(res) == 2 and set(res.kind) == {"bulk", "short"}
    assert len(api.deals("AAA", "2020-10-20", "2020-10-21", kind="bulk")) == 1
    with pytest.raises(api.CoverageError):
        api.deals("AAA", "2020-10-19", "2020-10-21")                        # before covered range
    with pytest.raises(api.CoverageError):
        api.deals("AAA", "2020-10-20", "2020-10-20", kind="short")          # short starts 2020-10-21
    with pytest.raises(ValueError):
        api.deals("AAA", "2020-10-20", "2020-10-21", kind="other")


def test_parse_impact_cost_and_unknown_layout():
    nl = bytes([10])
    raw = (b"10,OCT,2020,000003" + nl +
           b"20,AAA,EQ,INE001A01010,1,0.15" + nl +
           b"20,BBB,BE,INE002A01010,3," + nl +
           b'"20,KRISHPP,E1,IN90GGO01013,1,0.52\t"' + nl)
    df = market.parse_impact_cost(raw, pd.Timestamp("2020-10-01"))
    assert df.symbol.tolist() == ["AAA", "BBB", "KRISHPP"]
    assert df.category.tolist() == [1, 3, 1]
    assert df.loc[0, "impact_cost_pct"] == pytest.approx(0.15)
    assert pd.isna(df.loc[1, "impact_cost_pct"])
    assert df.loc[2, "impact_cost_pct"] == pytest.approx(0.52)
    with pytest.raises(market.UnknownLayout):
        market.parse_impact_cost(b"BAD,HEADER" + nl + b"20,AAA,EQ,INE,1,0.1" + nl, pd.Timestamp("2020-10-01"))
    with pytest.raises(market.UnknownLayout):
        market.parse_impact_cost(b"10,OCT,2020,1" + nl + b"20,AAA,EQ" + nl, pd.Timestamp("2020-10-01"))


def test_impact_cost_build_attaches_monthly_and_api_enforces_coverage(market_build):
    nl = bytes([10])
    icdir = paths.MARKET_RAW / "impactcost" / "2020"
    icdir.mkdir(parents=True, exist_ok=True)
    (icdir / "C_CATG_OCT2020.T01").write_bytes(
        b"10,OCT,2020,000002" + nl +
        b"20,AAA,EQ,INE001A01010,1,0.15" + nl +
        b"20,BBB,BE,INE002A01010,3," + nl)
    t = pd.DataFrame([(D, "AAA", "EQ", "S1", 1000.0), (D, "BBB", "BE", "S2", 50.0)],
                     columns=["date", "symbol", "series", "sec_id", "volume"])
    info = market.build(paths.BUILD / "market", t)
    assert info["impact_cost"] == {"rows": 2, "unattached": 0}
    api.clear_cache()
    res = api.impact_cost("AAA", "2020-10-01", "2020-10-31")
    assert len(res) == 1 and res.loc[0, "impact_cost_pct"] == pytest.approx(0.15) and res.loc[0, "category"] == 1
    res_b = api.impact_cost("BBB", "2020-10-01", "2020-10-31")
    assert len(res_b) == 1 and pd.isna(res_b.loc[0, "impact_cost_pct"])
    with pytest.raises(api.CoverageError):
        api.impact_cost("AAA", "2020-09-01", "2020-09-30")


def test_deals_identical_rows_inside_one_file_are_kept_and_cross_file_repeats_are_dropped(tmp_path, monkeypatch):
    nl = bytes([10])
    head = b"Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks" + nl
    row = b"20-NOV-2026,AAA,A LTD,CLIENT X,BUY,1000,10.5,-" + nl
    d = tmp_path / "market" / "deals"; d.mkdir(parents=True)
    (d / "bulk_20261120_20261120.csv").write_bytes(head + row + row)      # two identical deals the same day
    (d / "bulk_20261120.csv").write_bytes(head + row)                     # the daily snapshot repeats one of them
    monkeypatch.setattr(paths, "MARKET_RAW", tmp_path / "market")
    out = market._read_deals()
    assert len(out) == 2                                                  # not 1 (over-merged) and not 3 (double-counted)


def test_parse_mii_reads_issued_share_count_and_ignores_free_float(tmp_path):
    import gzip
    import pandas as pd
    from nseuniverse import market
    csv_ = ("FinInstrmId,TckrSymb,SctySrs,ISIN,ParVal,IssdCptl,FreeFltCptl,Other\n"
            "1,AAA,EQ,INE001A01010,1000,1.0E+08,,x\n"
            "2,BBB,BE,INE002A01010,500,abc,5,x\n"
            "3,,EQ,INE003A01010,1,5,,x\n").encode()
    df = market.parse_mii(gzip.compress(csv_), pd.Timestamp("2024-02-05"))
    assert df.columns.tolist() == ["date", "symbol", "series", "isin", "par_val", "shares_outstanding"]
    assert df.symbol.tolist() == ["AAA", "BBB"]                          # empty symbol dropped
    assert df.shares_outstanding.iloc[0] == 1e8 and pd.isna(df.shares_outstanding.iloc[1])      # not filled
    import pytest
    with pytest.raises(market.UnknownLayout):
        market.parse_mii(gzip.compress(b"a,b\n1,2\n"), pd.Timestamp("2024-02-05"))
    with pytest.raises(market.UnknownLayout):
        market.parse_mii(b"<html>", pd.Timestamp("2024-02-05"))


def test_build_keeps_only_shares_rows_of_the_series_that_traded_that_day(tmp_path, monkeypatch):
    import gzip
    root = tmp_path / "market"
    (root / "mii" / "2024").mkdir(parents=True)
    body = ("TckrSymb,SctySrs,ISIN,ParVal,IssdCptl,FreeFltCptl\n"
            "AAA,EQ,INE001A01010,10,1000,\nAAA,BL,INE001A01010,10,1000,\nBBB,EQ,INE002A01010,10,500,\n").encode()
    (root / "mii" / "2024" / "NSE_CM_security_05022024.csv.gz").write_bytes(gzip.compress(body))
    monkeypatch.setattr(paths, "MARKET_RAW", root)
    t = pd.DataFrame({"date": [pd.Timestamp("2024-02-05")], "symbol": ["AAA"], "series": ["EQ"], "sec_id": ["S1"],
                      "volume": [1.0], "isin": ["INE001A01010"]})
    info = market.build(tmp_path / "out", t)
    s = pd.read_parquet(tmp_path / "out" / "shares.parquet")
    assert s[["symbol", "series", "shares_outstanding", "sec_id"]].values.tolist() == [["AAA", "EQ", 1000.0, "S1"]]
    assert info["shares"] == {"rows": 1, "unattached": 2}              # AAA/BL and BBB did not trade in that series that day
