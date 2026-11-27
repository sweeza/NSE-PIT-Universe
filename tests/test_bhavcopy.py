import io
import zipfile

import numpy as np
import pytest

from nseuniverse import bhavcopy, fetch

LEGACY_OLD = ("SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,\n"
              "AAA,EQ,101,105.75,100.7,105.6,105.7,100.7,79273,8247959.95,2-JAN-2004,\n"
              "BBB,BE,10,11,9,10.5,10.5,10,100,1050,2-JAN-2004,\n")
LEGACY_NEW = ("SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"
              "AAA,EQ,101,105.75,100.7,105.6,105.7,100.7,79273,8247959.95,14-JUN-2018,741,INE144J01027,\n")
UDIFF = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,"
         "OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,"
         "ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
         "2024-08-01,2024-08-01,CM,NSE,STK,4986,INE962Y01021,IRCON,EQ,,,,,IRCON INTERNATIONAL LTD,290.00,291.00,"
         "283.30,287.15,287.65,288.75,,287.15,,,5838251,1676348516.90,77844,F1,1,,,,,\n")


def z(text, name="f.csv"):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as f:
        f.writestr(name, text)
    return b.getvalue()


def test_legacy_without_isin_leaves_missing_fields_null():
    df = bhavcopy.parse(z(LEGACY_OLD))
    assert len(df) == 2 and df["src"].eq("legacy").all()
    a = df[df.symbol == "AAA"].iloc[0]
    assert a.open == 101 and a.high == 105.75 and a.prev_close == 100.7 and a.volume == 79273
    assert a.turnover == pytest.approx(8247959.95)
    assert a["isin"] is None and np.isnan(a.trades)          # not published in 2004: stays null


def test_udiff_maps_to_same_columns():
    a = bhavcopy.parse(z(UDIFF)).iloc[0]
    assert (a.symbol, a.series, a["isin"]) == ("IRCON", "EQ", "INE962Y01021")
    assert a.close == 287.15 and a.prev_close == 288.75 and a.volume == 5838251 and a.trades == 77844
    assert a["name"] == "IRCON INTERNATIONAL LTD" and a.src == "udiff"


def test_no_value_is_filled_or_clipped():
    t = LEGACY_OLD.replace("105.75,100.7,105.6", "99,100.7,105.6")   # high below close: stays as published
    a = bhavcopy.parse(z(t)).query("symbol == 'AAA'").iloc[0]
    assert a.high == 99 and a.close == 105.6


def test_rejects_garbage():
    with pytest.raises(bhavcopy.BhavcopyError):
        bhavcopy.parse(z("X,Y\n1,2\n"))
    with pytest.raises(bhavcopy.BhavcopyError):
        bhavcopy.parse(z(LEGACY_OLD.replace("105.6,105.7", "abc,105.7")))        # non-numeric close
    with pytest.raises(bhavcopy.BhavcopyError):
        bhavcopy.parse(z(LEGACY_OLD + "AAA,EQ,1,1,1,1,1,1,1,1,2-JAN-2004,\n"))   # duplicate key
    with pytest.raises(bhavcopy.BhavcopyError):
        bhavcopy.parse(z(LEGACY_OLD + "CCC,EQ,1,1,1,1,1,1,1,1,3-JAN-2004,\n"))   # two dates in one file


def test_format_is_chosen_by_header_not_date():
    # a "2018" file with the UDiFF header still parses as UDiFF
    assert bhavcopy.parse(z(UDIFF)).src.iloc[0] == "udiff"
