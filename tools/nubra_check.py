"""Cross-check the bhavcopy prices against Nubra's daily candles.

    python tools/nubra_check.py fetch      # you log in at the prompt; read-only market data calls
    python tools/nubra_check.py compare    # offline

Credentials are typed at the Nubra SDK's own prompt and are never stored by this script.
Nubra documents its equity history as corporate-action adjusted (splits, bonuses and dividends) and in paise,
so levels can differ before an event: daily returns are the main test, raw close and volume are reported too.
Nubra's documented fields carry no delivery quantity, so delivery is not checked.
"""
import sys
import time
from pathlib import Path

import pandas as pd

OUT = Path(__file__).with_name("nubra_candles.csv")
START, END = "2024-11-20", "2026-11-20"
SYMBOLS = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "BHARTIARTL", "ITC", "LT", "HINDUNILVR",
           "MARUTI", "SUNPHARMA", "TITAN", "ASIANPAINT", "WIPRO", "TATASTEEL", "COALINDIA", "NESTLEIND",
           "BAJFINANCE", "DIXON", "IDEA", "SUZLON", "YESBANK", "PNB", "HEG"]
FIELDS = ["open", "high", "low", "close", "cumulative_volume"]


def fetch():
    from nubra_python_sdk.marketdata.market_data import MarketData
    from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv

    md = MarketData(InitNubraSdk(NubraEnv.PROD))
    rows = []
    for i in range(0, len(SYMBOLS), 5):                       # at most 5 symbols per request
        res = md.historical_data({"exchange": "NSE", "type": "STOCK", "values": SYMBOLS[i:i + 5], "fields": FIELDS,
                                  "startDate": f"{START}T00:00:00.000Z", "endDate": f"{END}T23:59:59.000Z",
                                  "interval": "1d", "intraDay": False, "realTime": False})
        for chart in res.result:
            for by_symbol in chart.values:
                for symbol, series in by_symbol.items():
                    for field in FIELDS:
                        for point in getattr(series, field) or []:
                            rows.append((symbol, point.timestamp, field, point.value))
        time.sleep(1.1)                                       # documented limit: 60 requests per minute
    d = pd.DataFrame(rows, columns=["symbol", "ts_ns", "field", "value"])
    d["date"] = pd.to_datetime(d.ts_ns, unit="ns", utc=True).dt.tz_convert("Asia/Kolkata").dt.date
    d = d.pivot_table(index=["symbol", "date"], columns="field", values="value", aggfunc="last").reset_index()
    for c in ["open", "high", "low", "close"]:
        d[c] = d[c] / 100                                     # paise -> rupees
    d.to_csv(OUT, index=False)
    print(f"{len(d)} rows, {d.symbol.nunique()} symbols -> {OUT}")


def compare():
    import nseuniverse.api as nse

    n = pd.read_csv(OUT, parse_dates=["date"])
    out = []
    for symbol, g in n.groupby("symbol"):
        ours = nse.prices(symbol, START, END, adjust_mode=None)
        m = ours.merge(g, on="date", suffixes=("", "_nubra")).sort_values("date")
        if m.empty:
            out.append({"symbol": symbol, "days": 0})
            continue
        ret_diff = (m.close.pct_change() - m.close_nubra.pct_change()).abs().dropna()
        out.append({"symbol": symbol, "days": len(m), "only_ours": len(ours) - len(m), "only_nubra": len(g) - len(m),
                    "close_within_0.1%": ((m.close_nubra / m.close - 1).abs() <= 0.001).mean(),
                    "return_within_0.1pt": (ret_diff <= 0.001).mean(),
                    "volume_within_1%": ((m.cumulative_volume / m.volume - 1).abs() <= 0.01).mean(),
                    "worst_day": m.date.loc[ret_diff.idxmax()].date() if len(ret_diff) else None})
    r = pd.DataFrame(out)
    print(r.to_string(index=False, float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    {"fetch": fetch, "compare": compare}[sys.argv[1]]()
