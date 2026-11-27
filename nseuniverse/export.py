"""The consumer tables in data/final/, written from the intermediates in data/final/_work.

prices/prices_YYYY.parquet  one row per date, symbol, series: OHLCV and delivery as published, plus
                            price_factor / volume_factor (adjusted = raw x factor; NaN where adjusted prices are not
                            offered) and adj_gap (class of a break in the adjusted series on that day, else "")
membership.csv              index_key, sec_id, symbol, isin, from_date, to_date (inclusive); VERIFIED days only
indices.parquet             official index levels
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import adjust, paths

PRICE_COLUMNS = ["date", "sec_id", "symbol", "series", "isin", "open", "high", "low", "close", "prev_close", "volume",
                 "turnover", "trades", "deliv_qty", "deliv_pct", "price_factor", "volume_factor", "adj_gap"]


def verified_membership(intervals: pd.DataFrame, coverage: pd.DataFrame, symbols: pd.DataFrame, last_day) -> pd.DataFrame:
    """Cut each membership interval [from, to) down to the VERIFIED windows [a, b] of its index.

    A row's dates are inclusive. symbol is the one carried on the row's last day; isin is the latest ISIN recorded
    for that symbol."""
    iv = intervals.rename(columns={"from_date": "start", "to_date": "stop"})
    win = coverage[coverage.status == "VERIFIED"][["index_key", "from_date", "to_date"]]
    m = iv.merge(win, on="index_key")
    first = m[["start", "from_date"]].max(axis=1)                       # NaT start = member since before the records
    last = pd.concat([m.stop - pd.Timedelta(days=1), m.to_date], axis=1).min(axis=1).fillna(pd.Timestamp(last_day))
    out = pd.DataFrame({"index_key": m.index_key, "sec_id": m.sec_id, "from_date": first, "to_date": last})
    out = out[out.from_date <= out.to_date].reset_index(drop=True)
    names = out.reset_index().merge(symbols[["sec_id", "symbol", "from_date", "isins"]].rename(columns={"from_date": "since"}),
                                    on="sec_id")
    names = names[names.since <= names.to_date].sort_values(["index", "since"]).drop_duplicates("index", keep="last")
    names = names.set_index("index")
    out["symbol"] = names.symbol
    out["isin"] = names.isins.astype(str).str.split(r"[;,| ]+").str[-1]
    cols = ["index_key", "sec_id", "symbol", "isin", "from_date", "to_date"]
    return out[cols].sort_values(["index_key", "from_date", "symbol"], kind="mergesort").reset_index(drop=True)


def price_table(bhav: pd.DataFrame, delivery: pd.DataFrame, adj: pd.DataFrame, refused: set, gaps: pd.DataFrame) -> pd.DataFrame:
    """One year of prices with delivery, adjustment factors and break flags."""
    key = ["date", "symbol", "series"]
    p = bhav.merge(delivery[key + ["deliv_qty", "deliv_pct"]].drop_duplicates(key), on=key, how="left")
    a = adjust.apply(p[["sec_id", "date", "close", "volume"]], adj)
    bad = p.sec_id.isin(refused).to_numpy()
    p["price_factor"] = np.where(bad, np.nan, a.price_factor)
    p["volume_factor"] = np.where(bad, np.nan, a.volume_factor)
    flags = gaps[["sec_id", "date", "class"]].drop_duplicates(["sec_id", "date"])
    p = p.merge(flags, on=["sec_id", "date"], how="left")
    p["adj_gap"] = p.pop("class").fillna("")
    return p.reindex(columns=PRICE_COLUMNS)


def write() -> dict:
    from . import api, bhavcopy, verify
    api.clear_cache()
    verify.check_adjusted_continuity()                                  # writes _work/adjustment_gaps.csv
    gaps = api.adjustment_gaps()
    adj = api._adjustments()
    est = adj[adj.kind == adjust.DEMERGER_EST][["sec_id", "eff_date"]].rename(columns={"eff_date": "date"})
    gaps = pd.concat([est.assign(**{"class": "DEMERGER_ESTIMATED"}), gaps], ignore_index=True)
    refused = set(api._unreliable())
    delivery = pd.read_parquet(paths.BUILD / "market" / "delivery.parquet")

    pdir = paths.FINAL / "prices"
    pdir.mkdir(parents=True, exist_ok=True)
    rows, last_day = 0, None
    for f in sorted((paths.BUILD / "bhavcopy").glob("bhavcopy_*.parquet")):
        b = pd.read_parquet(f)
        year = b.date.dt.year.iloc[0]
        p = price_table(b, delivery[delivery.date.dt.year == year], adj, refused, gaps)
        p.to_parquet(pdir / f"prices_{year}.parquet", index=False, compression="zstd", compression_level=9)
        rows, last_day = rows + len(p), p.date.max()

    cov = api.coverage()
    sh = pd.read_parquet(paths.BUILD / "identity" / "symbol_history.parquet")
    mem = verified_membership(api._intervals(), cov, sh, last_day)
    mem.to_csv(paths.FINAL / "membership.csv", index=False, date_format="%Y-%m-%d")

    keys = pd.read_csv(paths.CURATED / "index_universe.csv").index_name
    frames = [api.index_values(n).assign(index_name=n) for n in keys]
    for f in frames:
        f.attrs = {}                                                    # attrs holding frames break concat
    levels = pd.concat(frames, ignore_index=True)
    levels.to_parquet(paths.FINAL / "indices.parquet", index=False, compression="zstd", compression_level=9)
    return {"price_rows": rows, "membership_rows": len(mem), "index_rows": len(levels)}
