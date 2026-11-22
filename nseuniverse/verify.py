"""Data-integrity checks. This is the release gate: `nseuniverse verify` exits non-zero on any FAIL.

PASS  the invariant holds
WARN  informational; counts are reported, no data is wrong by construction
FAIL  the data cannot be trusted until fixed or waived in data/curated/waivers.csv with evidence
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
import zipfile
import io
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import pandas as pd

from . import adjust, bhavcopy, calendar, indices, membership, paths, pipeline

NUMCOLS = ["open", "high", "low", "close", "last", "prev_close", "volume", "turnover", "trades", "settle_price"]


@dataclass
class Result:
    name: str
    status: str
    summary: str
    details: list = field(default_factory=list)


def _waivers() -> pd.DataFrame:
    p = paths.CURATED / "waivers.csv"
    if p.exists():
        return pd.read_csv(p, dtype=str)
    return pd.DataFrame(columns=["check", "key", "reason", "evidence"])


# ------------------------------------------------------------------ raw layer
def check_manifest() -> Result:
    if not paths.MANIFEST.exists():
        return Result("raw_manifest", "FAIL", "no manifest")
    rows = list(csv.DictReader(open(paths.MANIFEST, newline="", encoding="utf-8", errors="replace")))
    from concurrent.futures import ThreadPoolExecutor

    def _hash_file(r):
        p = paths.ROOT / r["path"]
        if not p.exists():
            return "missing", r["path"], p
        h = hashlib.sha256()
        with p.open("rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        digest = h.hexdigest()
        if digest != r["sha256"]:
            return "bad", r["path"], p
        return "ok", None, p

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(_hash_file, rows))

    bad = [p for status, p, _ in results if status == "bad"]
    missing = [p for status, p, _ in results if status == "missing"]
    seen = {p.resolve() for _, _, p in results if p.exists()}

    on_disk = [p for root in (paths.BHAV_RAW, paths.INDEX_DAILY_RAW, paths.PRESS_RAW,
                              paths.RAW / "constituents", paths.RAW / "corporate_actions", paths.RAW / "nse_lists", paths.HELD)
               if root.exists()
               for p in root.rglob("*") if p.is_file() and p.suffix != ".part"]
    on_disk += [p for p in paths.INDEX_HIST_RAW.rglob("*.json")]
    unlisted = [p.name for p in on_disk if p.resolve() not in seen]
    dup = len(rows) - len({r["path"] for r in rows})
    ok = not (bad or missing or unlisted or dup)
    return Result("raw_manifest", "PASS" if ok else "FAIL",
                  f"{len(rows)} files; hash mismatches={len(bad)} missing={len(missing)} unlisted={len(unlisted)} duplicate_rows={dup}",
                  (bad + missing + unlisted)[:20])


def _independent_parse(blob: bytes) -> dict:
    """A second, separate reader (stdlib csv + float) used only to audit the main parser."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    text = z.read(z.namelist()[0]).decode("latin1")
    rd = csv.reader(io.StringIO(text))
    head = [h.strip() for h in next(rd)]
    ix = {h: i for i, h in enumerate(head)}
    legacy = "SYMBOL" in ix
    m = ({"symbol": "SYMBOL", "series": "SERIES", "open": "OPEN", "high": "HIGH", "low": "LOW", "close": "CLOSE",
          "last": "LAST", "prev_close": "PREVCLOSE", "volume": "TOTTRDQTY", "turnover": "TOTTRDVAL",
          "trades": "TOTALTRADES", "isin": "ISIN"} if legacy else
         {"symbol": "TckrSymb", "series": "SctySrs", "open": "OpnPric", "high": "HghPric", "low": "LwPric",
          "close": "ClsPric", "last": "LastPric", "prev_close": "PrvsClsgPric", "volume": "TtlTradgVol",
          "turnover": "TtlTrfVal", "trades": "TtlNbOfTxsExctd", "isin": "ISIN", "settle_price": "SttlmPric"})
    out = {}
    for row in rd:
        if not row or all(not c.strip() for c in row):
            continue
        rec = {}
        for k, h in m.items():
            if h in ix and ix[h] < len(row):
                v = row[ix[h]].strip()
                rec[k] = v
            else:
                rec[k] = ""
        out[(rec["symbol"], rec["series"])] = rec
    return out


def check_bhavcopy_lossless(sample_every: int = 1) -> Result:
    t = bhavcopy.load()
    chosen = bhavcopy.select_per_day(bhavcopy.raw_files())
    by_day = {d: g for d, g in t.groupby(t["date"].dt.date)}
    problems = []
    n_days = n_rows = 0
    for i, (d, (k, p)) in enumerate(sorted(chosen.items())):
        if i % sample_every:
            continue
        ind = _independent_parse(p.read_bytes())
        g = by_day.get(d)
        n_days += 1
        if g is None:
            problems.append((str(d), "day missing from table")); continue
        n_rows += len(g)
        if len(g) != len(ind):
            problems.append((str(d), f"row count table={len(g)} raw={len(ind)}")); continue
        for r in g.itertuples(index=False):
            raw = ind.get((r.symbol, r.series))
            if raw is None:
                problems.append((str(d), f"row {r.symbol}/{r.series} not in raw")); break
            bad = False
            for c in NUMCOLS:
                rv = raw.get(c, "")
                rv = None if rv in ("", "-") else float(rv)
                tv = getattr(r, c)
                if (rv is None) != bool(pd.isna(tv)) or (rv is not None and rv != tv):
                    problems.append((str(d), f"{r.symbol}/{r.series} {c}: table={tv} raw={rv}")); bad = True; break
            if not bad:
                isin = raw.get("isin") or None
                if isin != r.isin:
                    problems.append((str(d), f"{r.symbol}/{r.series} isin table={r.isin} raw={isin}")); bad = True
            if bad:
                break
    return Result("bhavcopy_lossless", "PASS" if not problems else "FAIL",
                  f"{n_days} days / {n_rows} rows compared against an independent re-parse of the raw files; "
                  f"{len(problems)} days with differences", problems[:20])


def check_overlap_days() -> Result:
    files = bhavcopy.raw_files()
    by = {}
    for d, k, p in files:
        by.setdefault(d, {})[k] = p
    both = [d for d, v in by.items() if len(v) == 2]
    diffs = []
    for d in both:
        a = bhavcopy.parse(by[d]["legacy"].read_bytes()).set_index(["symbol", "series"])
        b = bhavcopy.parse(by[d]["udiff"].read_bytes()).set_index(["symbol", "series"])
        common = a.index.intersection(b.index)
        for c in ["open", "high", "low", "close", "volume"]:
            x, y = a.loc[common, c], b.loc[common, c]
            n = int(((x != y) & ~(x.isna() & y.isna())).sum())
            if n:
                diffs.append((str(d), c, n))
        if len(a.index.symmetric_difference(b.index)):
            diffs.append((str(d), "keys", int(len(a.index.symmetric_difference(b.index)))))
    return Result("legacy_vs_udiff_overlap", "PASS" if not diffs else "FAIL",
                  f"{len(both)} days published in both formats; {len(diffs)} differences", diffs[:10])


def check_calendar() -> Result:
    cal = calendar.build()
    if cal.empty:
        return Result("calendar", "FAIL", "no bhavcopy days")
    wd = cal[cal.weekday < 5]
    after = cal[cal.date >= "2012-02-21"]
    idx_no_bhav = after[after.index_file & ~after.bhavcopy]
    bhav_no_idx = after[after.bhavcopy & ~after.index_file]
    weekend_sessions = cal[(cal.weekday >= 5) & cal.bhavcopy]
    missing_weekdays = wd[~wd.bhavcopy]
    status = "FAIL" if len(idx_no_bhav) else ("WARN" if len(bhav_no_idx) else "PASS")
    d = [("index file but no bhavcopy", [str(x.date()) for x in idx_no_bhav.date][:15]),
         ("bhavcopy but no index file", [str(x.date()) for x in bhav_no_idx.date][:15]),
         ("weekend sessions", [str(x.date()) for x in weekend_sessions.date])]
    return Result("calendar", status,
                  f"{int(cal.bhavcopy.sum())} trading days {cal.date.min().date()}..{cal.date.max().date()}; "
                  f"weekday non-sessions={len(missing_weekdays)}; weekend sessions={len(weekend_sessions)}; "
                  f"index-only days={len(idx_no_bhav)}; bhavcopy-only days={len(bhav_no_idx)}", d)


def _close_outside_range(t: pd.DataFrame) -> int:
    """Traded rows whose close lies outside [low, high] (as published by NSE; mostly series T0)."""
    traded = t[t.volume > 0]
    return int(((traded.close > traded.high * 1.0000001) | (traded.close < traded.low * 0.9999999)).sum())


def check_table_sanity() -> Result:
    t = bhavcopy.load()
    dup = int(t.duplicated(["date", "symbol", "series"]).sum())
    neg = int(((t[["open", "high", "low", "close"]] < 0).any(axis=1)).sum())
    traded = t[t.volume > 0]
    hl = int((traded.high < traded.low).sum())
    cl = _close_outside_range(t)
    nosid = int(t["sec_id"].isna().sum()) if "sec_id" in t else -1
    status = "FAIL" if (dup or neg or nosid != 0) else "PASS"
    return Result("table_sanity", status,
                  f"rows={len(t)} duplicate_keys={dup} negative_prices={neg} rows_without_sec_id={nosid}; "
                  f"as-published oddities (not altered): high<low={hl} close_outside_range={cl}")


# ------------------------------------------------------------------ identity
def check_identity() -> Result:
    t = bhavcopy.load()
    sec = pd.read_parquet(paths.BUILD / "identity" / "securities.parquet")
    sh = pd.read_parquet(paths.BUILD / "identity" / "symbol_history.parquet")
    uniq = sec.sec_id.is_unique
    multi = t.groupby(["sec_id", "date"])["symbol"].nunique()
    n_multi = int((multi > 1).sum())
    sh = sh.sort_values(["sec_id", "from_date"])
    overlap = int((sh.groupby("sec_id")["from_date"].shift(-1) <= sh["to_date"]).sum())
    sym_multi_sec = t.groupby(["symbol", "date"])["sec_id"].nunique()
    n_sm = int((sym_multi_sec > 1).sum())
    links = pd.read_parquet(paths.BUILD / "identity" / "links.parquet")
    st = links.status.value_counts().to_dict()
    ok = uniq and n_multi == 0 and overlap == 0 and n_sm == 0
    return Result("identity", "PASS" if ok else "FAIL",
                  f"{len(sec)} securities from {t.symbol.nunique()} symbols; ids unique={uniq}; "
                  f"security with 2 symbols on one day={n_multi}; symbol with 2 securities on one day={n_sm}; "
                  f"overlapping symbol intervals={overlap}; link outcomes={st}")


# ------------------------------------------------------------------ corporate actions
def _gap_table(t: pd.DataFrame) -> pd.DataFrame:
    pc = pipeline.primary_close(t).sort_values(["sec_id", "date"])
    pc["prev_close_obs"] = pc.groupby("sec_id")["close"].shift(1)
    pc["prev_date"] = pc.groupby("sec_id")["date"].shift(1)
    return pc


def _nearby_day(g: pd.DataFrame | None, day, s: float, k: int = 5, tol: float = 0.12):
    """Trading day within +-k sessions whose price move matches share factor s (a hint for a
    mis-dated ex-date). Returns the date only when exactly one day matches."""
    if g is None or not (s > 1.15 or s < 0.87):
        return None
    i = int(g["date"].searchsorted(pd.Timestamp(day)))
    hits = []
    for j in range(max(1, i - k), min(len(g), i + k + 1)):
        po, o = g["prev_close_obs"].iloc[j], g["open"].iloc[j]
        if o and o > 0 and pd.notna(po) and abs(po / o / s - 1) <= tol:
            hits.append(str(g["date"].iloc[j].date()))
    return hits[0] if len(hits) == 1 else None


def check_actions() -> Result:
    """Every share-structure action is tested against the price move NSE actually printed.

    Per (security, effective day): expected move = product of all parsed share factors that day
    (a bonus and a split on the same ex-date compound). The observed move is previous close over
    the day's open (or close). A day passes if observed/expected is within 25%. Unquantified or
    unparsed events pass only if they sit on a day with no residual jump after the parsed events."""
    ev = pd.read_parquet(paths.BUILD / "actions" / "events.parquet")
    adj = pd.read_parquet(paths.BUILD / "actions" / "adjustments.parquet")
    t = bhavcopy.load()
    pc = _gap_table(t).set_index(["sec_id", "date"])
    wv = _waivers()
    wkeys = set(wv[wv.check == "action"]["key"]) if len(wv) else set()
    ev = ev[ev.status != "NOT_EQUITY"]

    share = adj[adj.kind.isin(["SPLIT", "BONUS", "CONSOLIDATION"])].groupby(["sec_id", "eff_date"]).agg(
        S=("vol_mult", "prod"), what=("detail", lambda x: "+".join(x))).reset_index()
    rights = adj[adj.kind == "RIGHTS"].groupby(["sec_id", "eff_date"])["price_mult"].prod().rename("R").reset_index()
    days = share.merge(rights, on=["sec_id", "eff_date"], how="outer")
    days["S"] = days["S"].fillna(1.0); days["R"] = days["R"].fillna(1.0)
    unres = ev[ev.kind.isin(["UNPARSED", "UNKNOWN", "SCHEME"]) & (ev.status == "OK")]
    u = unres.groupby(["sec_id", "eff_date"]).agg(unres_kind=("kind", "first"), unres_symbol=("symbol", "first"),
                                                   unres_detail=("subject", lambda x: " | ".join(sorted(set(x)))[:90])).reset_index()
    days = days.merge(u, on=["sec_id", "eff_date"], how="outer")
    days["S"] = days["S"].fillna(1.0); days["R"] = days["R"].fillna(1.0)

    out = []
    rights_notes = []
    pc_sorted = {sid: g.reset_index() for sid, g in pc.reset_index().sort_values(["sec_id", "date"]).groupby("sec_id")} \
        if len(days) else {}
    counts = {"explained": 0, "contradicted": 0, "unresolved_jump": 0, "unresolved_nojump": 0, "no_price_row": 0}
    for r in days.itertuples(index=False):
        k = (r.sec_id, r.eff_date)
        if k not in pc.index:
            counts["no_price_row"] += 1; continue
        row = pc.loc[k]
        if pd.isna(row.prev_close_obs):
            counts["no_price_row"] += 1; continue
        obs = [row.prev_close_obs / x for x in (row.open, row.close) if x and x > 0]
        expected = r.S / r.R
        resid = [o / expected for o in obs]
        okday = any(0.8 <= x <= 1.25 for x in resid)
        parsed = abs(r.S - 1) > 1e-12 or abs(r.R - 1) > 1e-12
        name = r.unres_symbol if isinstance(r.unres_symbol, str) else str(r.sec_id)
        # waivers are keyed by the feed's symbol and date, never by sec_id (ids are build-derived)
        key = f"{name}|{pd.Timestamp(r.eff_date).date()}"
        has_unres = isinstance(r.unres_kind, str)
        share_only = abs(r.S - 1) > 1e-12
        if parsed and okday:
            counts["explained"] += 1
        elif parsed and has_unres:
            if key not in wkeys:
                counts["unresolved_jump"] += 1
                out.append(("UNRESOLVED_WITH_JUMP", key, f"{r.unres_kind}: {r.unres_detail} (parsed part: {getattr(r, 'what', '')})",
                            round(expected, 4), round(obs[0], 4) if obs else None))
        elif parsed and not share_only:
            counts["rights_vs_price"] = counts.get("rights_vs_price", 0) + 1     # rights: theoretical (TERP) vs market
            rights_notes.append((key, round(expected, 4), round(obs[0], 4) if obs else None))
        elif parsed:
            if key not in wkeys:
                counts["contradicted"] += 1
                hit = _nearby_day(pc_sorted.get(r.sec_id), r.eff_date, r.S)
                out.append(("PARSED_CONTRADICTED", key, f"{getattr(r, 'what', '')}" + (f" | price move matches on {hit}" if hit else ""),
                            round(expected, 4), round(obs[0], 4) if obs else None))
        elif okday:
            counts["unresolved_nojump"] += 1
        elif key not in wkeys:
            counts["unresolved_jump"] += 1
            out.append(("UNRESOLVED_WITH_JUMP", key, f"{r.unres_kind}: {r.unres_detail}", 1.0, round(obs[0], 4) if obs else None))
    pd.DataFrame(out, columns=["class", "key", "what", "expected_ratio", "observed_ratio"]).to_csv(
        paths.BUILD / "action_exceptions.csv", index=False)
    nbad = counts["contradicted"] + counts["unresolved_jump"]
    n_unplaced = int((ev.status != "OK").sum())
    pd.DataFrame(rights_notes, columns=["key", "expected_ratio", "observed_ratio"]).to_csv(
        paths.BUILD / "rights_vs_price.csv", index=False)
    gl = pd.read_parquet(paths.BUILD / "actions" / "gate_log.parquet")
    gc = gl.decision.value_counts().to_dict()
    gl[gl.decision.isin(["REJECTED", "SHIFTED"])].to_csv(paths.BUILD / "actions_rejected_or_shifted.csv", index=False)
    waived = len(wkeys)
    status = "FAIL" if nbad else ("WARN" if (gc.get("REJECTED", 0) or waived) else "PASS")
    return Result("corporate_actions_vs_prices", status,
                  f"ex-date days where parsed action(s) match the observed price move={counts['explained']}; "
                  f"parsed actions contradicted by the price move={counts['contradicted']}; "
                  f"unquantified/unparsed events with an unexplained price jump={counts['unresolved_jump']}; "
                  f"rights days where the theoretical (TERP) adjustment differs from the market move by >25% (informational, build/rights_vs_price.csv)={counts.get('rights_vs_price', 0)}; "
                  f"unquantified events with no price effect (nothing to adjust)={counts['unresolved_nojump']}; "
                  f"event components whose security was not trading around the ex-date={n_unplaced}; "
                  f"evidence gate on share actions: {gc} (REJECTED = feed claims an action the prices do not show, not applied; "
                  f"listed in build/actions_rejected_or_shifted.csv); documented adjustment breaks (waived, unquantifiable in the feed)={waived}",
                  out[:25])


def check_adjusted_continuity(lo: float = 0.55, hi: float = 1.8, max_gap_days: int = 7, min_move: float = 0.25) -> Result:
    """Scan the adjusted close of every equity security for overnight moves outside [lo, hi] on
    consecutive sessions (moves of <= Rs 0.25 are ignored: at prices near Rs 0.05 one tick is a 100%
    change). Every flagged move is classified and written to build/adjustment_gaps.csv:
      PRE_COVERAGE   before the corporate-action feed has coverage (see adjust.COVERAGE_START)
      ON_ACTION_DAY  a feed action (waived scheme, rejected, unquantifiable) sits on the day
      UNEXPLAINED    nothing in the feed explains it (e.g. an action the feed omits, an SME or
                     ETF unit event, or a genuine crash/relisting)
    UNEXPLAINED moves are a documented limitation: WARN, never silently adjusted."""
    t = bhavcopy.load()
    adj = pd.read_parquet(paths.BUILD / "actions" / "adjustments.parquet")
    ev = pd.read_parquet(paths.BUILD / "actions" / "events.parquet")
    ev = ev[ev.status == "OK"]
    pc = pipeline.primary_close(t)
    pc = adjust.apply(pc.assign(last=np.nan, prev_close=np.nan, high=pc.close, low=pc.close), adj, "splits")
    pc = pc.sort_values(["sec_id", "date"])
    g = pc.groupby("sec_id")
    pc["r"] = pc["adj_close"] / g["adj_close"].shift(1)
    pc["gap"] = g["date"].diff().dt.days
    pc["move"] = (pc["close"] - g["close"].shift(1)).abs()
    fl = pc[((pc.r < lo) | (pc.r > hi)) & (pc.gap <= max_gap_days) & (pc.volume > 0) & (pc.move > min_move)].copy()
    evd = set(zip(ev.sec_id, ev.eff_date))
    wv = _waivers()
    wk = set(wv[wv.check == "jump"]["key"]) if len(wv) else set()
    fl["key"] = fl.sec_id + "|" + fl.date.dt.strftime("%Y-%m-%d")
    fl["class"] = np.where(fl.date < adjust.COVERAGE_START, "PRE_COVERAGE",
                  np.where([(s, d) in evd for s, d in zip(fl.sec_id, fl.date)], "ON_ACTION_DAY", "UNEXPLAINED"))
    fl.loc[fl.key.isin(wk), "class"] = "WAIVED"
    sec = pd.read_parquet(paths.BUILD / "identity" / "securities.parquet").set_index("sec_id")
    fl["symbol"] = fl.sec_id.map(sec.last_symbol)
    fl["series"] = fl["series"]
    out = fl[["sec_id", "symbol", "date", "series", "r", "class"]].sort_values(["sec_id", "date"])
    out.to_csv(paths.BUILD / "adjustment_gaps.csv", index=False)
    c = out["class"].value_counts().to_dict()
    un = out[out["class"] == "UNEXPLAINED"]
    nsec = int(out[out["class"].isin(["UNEXPLAINED", "ON_ACTION_DAY"])].sec_id.nunique())
    return Result("adjusted_price_continuity", "WARN" if c.get("UNEXPLAINED") or c.get("ON_ACTION_DAY") else "PASS",
                  f"adjusted-close overnight moves outside [{lo},{hi}] on consecutive sessions: {len(out)} flagged -> {c}; "
                  f"securities with a documented break after {adjust.COVERAGE_START.date()}: {nsec} "
                  f"(all rows in build/adjustment_gaps.csv). Adjusted prices before {adjust.COVERAGE_START.date()} are NOT verified "
                  f"(the feed holds almost no splits/bonuses before then).",
                  [(r.symbol, str(r.date.date()), round(float(r.r), 3)) for r in un.head(15).itertuples()])


# ------------------------------------------------------------------ indices
def check_indices() -> Result:
    """Two independent NSE publications must agree; disagreements are surfaced, never hidden."""
    d = pd.read_parquet(paths.BUILD / "indices" / "index_daily.parquet")
    h = pd.read_parquet(paths.BUILD / "indices" / "index_history.parquet")
    dup_daily = int(d.duplicated(["index_key", "date"]).sum())
    dup_hist = int(h.duplicated(["index_key", "date"]).sum())
    v = indices.values()
    cf = v[v.conflict]
    cf = cf.assign(rel=(cf.close - cf.alt_close).abs() / cf.alt_close)
    cf[["index_key", "date", "close", "alt_close", "rel"]].to_csv(paths.BUILD / "index_conflicts.csv", index=False)
    both = int(v.alt_close.notna().sum())
    big = int((cf.rel >= 1e-3).sum())
    cal = pd.DatetimeIndex(calendar.trading_days())
    gaps = {}
    for k, g in v.groupby("index_key"):
        days = cal[(cal >= g.date.min()) & (cal <= g.date.max())]
        miss = len(days.difference(pd.DatetimeIndex(g.date)))
        if miss:
            gaps[k] = miss
    only_d = int((v.src == "daily").sum() - both)
    status = "FAIL" if (dup_daily or dup_hist) else ("WARN" if (len(cf) or gaps) else "PASS")
    top = cf.groupby("index_key").size().sort_values(ascending=False).head(8).to_dict()
    return Result("index_values_two_source_agreement", status,
                  f"{v.index_key.nunique()} indices, {len(v)} index-days (daily file {len(d)} rows, history API {len(h)} rows); "
                  f"unresolved duplicate rows: daily={dup_daily} history={dup_hist}; days covered by both sources={both}, "
                  f"of which closes differ >0.011: {len(cf)} ({big} by >=0.1%) - all flagged conflict=True with alt_close, "
                  f"listed in build/index_conflicts.csv; index-days missing vs trading calendar inside each index's life: "
                  f"{sum(gaps.values())} across {len(gaps)} indices",
                  [("conflicts by index (top)", top), ("gap indices (top)", dict(sorted(gaps.items(), key=lambda x: -x[1])[:8]))])


def check_curated_provenance() -> Result:
    """Every data/raw/... reference in data/curated/*.csv must exist on disk."""
    files = ["index_events_press.csv", "index_dual_class.csv", "index_size_exceptions.csv",
             "identity_links.csv", "name_aliases.csv"]
    checked = 0
    n_files = 0
    missing = []
    for name in files:
        p = paths.CURATED / name
        if not p.exists():
            continue
        n_files += 1
        df = pd.read_csv(p, dtype=str).fillna("")
        if "source" not in df.columns:
            continue
        for src_val in df["source"]:
            last_dir = None
            for tok in (t.strip() for t in src_val.split(";") if t.strip()):
                m = re.match(r"(data/raw/[^\s:;,\"']+)", tok)
                if m:
                    ref = m.group(1)
                    last_dir = str(Path(ref).parent).replace("\\", "/")
                elif last_dir and "/" not in tok and "\\" not in tok:
                    bm = re.match(r"([^\s:;,\"']+\.[A-Za-z0-9]{2,5})$", tok)
                    if not bm:
                        continue
                    ref = f"{last_dir}/{bm.group(1)}"
                else:
                    continue
                checked += 1
                if not (paths.ROOT / ref).exists():
                    missing.append((name, ref))
    return Result("curated_provenance", "PASS" if not missing else "FAIL",
                  f"{checked} raw references across {n_files} curated files; missing={len(missing)}",
                  missing[:20])


# Prior to the 1 Apr 2016 broad-market restructuring (NSE release ind_prs22022016_1.pdf),
# only NIFTY50 + NIFTYNEXT50 = NIFTY100 and NIFTY100/200/500 nested unconditionally; the strict
# 100 <= 200 <= 500, 100 <= LARGEMIDCAP250 <= 500, MIDCAP50 <= MIDCAP150 <= 500, and
# SMALLCAP50 <= SMALLCAP100 <= SMALLCAP250 <= 500 hierarchy took effect on 2016-04-01.
# On 2018-04-02 (NSE release ind_prs05012018.pdf), NIFTY Free float Midcap 100 was renamed
# NIFTY Midcap 100 and restructured to be drawn from Nifty Midcap 150 (making MIDCAP100 <= 200,
# MIDCAP100 <= MIDCAP150, and MIDCAP100 <= 500 active from 2018-04-02; before then, Free Float Midcap 100
# was an independent percentile band, and in Sep 2017 DMART entered FF Midcap 100 on 2017-09-05 per
# ind_prs29082017.pdf while entering Nifty 500 on 2017-09-29 per ind_prs28082017.pdf).
_SUBSET_PAIRS = [
    ("NIFTY50", "NIFTY100"), ("NIFTYNEXT50", "NIFTY100"), ("NIFTY100", "NIFTY200"),
    ("NIFTYMIDCAP100", "NIFTY200"), ("NIFTY100", "NIFTY500"), ("NIFTY200", "NIFTY500"),
    ("NIFTYMIDCAP150", "NIFTY500"), ("NIFTYSMALLCAP250", "NIFTY500"),
    ("NIFTYMIDSMALLCAP400", "NIFTY500"), ("NIFTYLARGEMIDCAP250", "NIFTY500"),
    ("NIFTY100", "NIFTYLARGEMIDCAP250"), ("NIFTYMIDCAP50", "NIFTYMIDCAP150"),
    ("NIFTYMIDCAP100", "NIFTYMIDCAP150"),
    ("NIFTYSMALLCAP50", "NIFTYSMALLCAP100"), ("NIFTYSMALLCAP100", "NIFTYSMALLCAP250"),
    ("NIFTYMIDCAP100", "NIFTY500"), ("NIFTYSMALLCAP100", "NIFTY500"),
]
_PRE_RESTRUCTURE_PAIRS = {("NIFTY50", "NIFTY100"), ("NIFTYNEXT50", "NIFTY100"), ("NIFTY100", "NIFTY500")}
_RESTRUCTURE_DATE = pd.Timestamp("2016-04-01")
_MIDCAP100_RESTRUCTURE_DATE = pd.Timestamp("2018-04-02")


def check_membership() -> Result:
    """Verify event/anchor resolution and cross-index hierarchy invariants on VERIFIED days."""
    cov_p = paths.BUILD / "membership" / "coverage.parquet"
    int_p = paths.BUILD / "membership" / "intervals.parquet"
    seg_p = paths.BUILD / "identity" / "segments.parquet"
    if not (cov_p.exists() and int_p.exists() and seg_p.exists()):
        return Result("membership", "FAIL", "missing membership or identity build tables")
    cov = pd.read_parquet(cov_p)
    iv = pd.read_parquet(int_p)
    seg = pd.read_parquet(seg_p)
    ver = cov[cov["status"] == "VERIFIED"]
    if ver.empty:
        return Result("membership", "FAIL", "no VERIFIED indices in coverage.parquet")

    problems = []
    # (a) index_events_press.csv resolution
    press_p = paths.CURATED / "index_events_press.csv"
    if press_p.exists():
        ev = pd.read_csv(press_p, dtype=str).fillna("")
        for r in ev.itertuples(index=False):
            if not membership._sid(seg, r.symbol, pd.Timestamp(r.date)):
                problems.append(("press_unresolved", r.index_key, r.date, r.symbol))

    # (b) ANCHORED constituent files resolution
    for k, (_, anchor_rel) in membership.ANCHORED.items():
        ap = paths.ROOT / anchor_rel
        if not ap.exists():
            continue
        adate = pd.Timestamp(ap.parent.name) if ap.parent.name[:4].isdigit() else seg["end"].max()
        adf = pd.read_csv(ap, dtype=str).fillna("")
        sym_col = "Symbol" if "Symbol" in adf.columns else ("SYMBOL" if "SYMBOL" in adf.columns else None)
        if sym_col:
            for sym in adf[sym_col]:
                sym = sym.strip()
                if sym and not sym.upper().startswith("DUMMY") and not membership._sid(seg, sym, adate):
                    problems.append(("anchor_unresolved", k, sym))

    # (c) Cross-index hierarchy / partition invariants on trading days
    cal = pd.DatetimeIndex(calendar.trading_days())
    ver_windows: dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]] = {}
    for r in ver.itertuples(index=False):
        ver_windows.setdefault(r.index_key, []).append((pd.Timestamp(r.from_date), pd.Timestamp(r.to_date)))
    dc_p = paths.CURATED / "index_dual_class.csv"
    dc_rows = pd.read_csv(dc_p, dtype=str).fillna("") if dc_p.exists() else pd.DataFrame()

    def _dual_class_sids(t: pd.Timestamp) -> set[str]:
        if dc_rows.empty:
            return set()
        out = set()
        for r in dc_rows.itertuples(index=False):
            if pd.Timestamp(r.from_date) <= t <= pd.Timestamp(r.to_date):
                for s in str(r.symbols).split(";"):
                    s = s.strip()
                    if s:
                        sid = membership._sid(seg, s, t)
                        if sid:
                            out.add(sid)
        return out

    # Pre-filter trading days to those where at least 2 relevant indices are verified
    relevant = set(["NIFTY50", "NIFTYNEXT50", "NIFTY100"]) | {c for p in _SUBSET_PAIRS for c in p}
    active = {k: wl for k, wl in ver_windows.items() if k in relevant}
    checked_days = 0
    if len(active) >= 2:
        min_d = min(w[0] for wl in active.values() for w in wl)
        max_d = max(w[1] for wl in active.values() for w in wl)
        days = cal[(cal >= min_d) & (cal <= max_d)]
        # Build fast interval lookup per index
        iv_by_idx = {k: g for k, g in iv.groupby("index_key")}
        for t in days:
            avail = [k for k, wl in active.items() if any(f <= t <= to for f, to in wl)]
            if len(avail) < 2:
                continue
            checked_days += 1
            mem = {}
            for k in avail:
                g = iv_by_idx.get(k)
                if g is None:
                    mem[k] = set()
                else:
                    mem[k] = set(g.loc[(g["from_date"].isna() | (g["from_date"] <= t)) & (g["to_date"].isna() | (g["to_date"] > t)), "sec_id"])
            if "NIFTY50" in mem and "NIFTYNEXT50" in mem:
                overlap = mem["NIFTY50"] & mem["NIFTYNEXT50"]
                if overlap:
                    problems.append(("n50_next50_overlap", str(t.date()), len(overlap)))
            if "NIFTY50" in mem and "NIFTYNEXT50" in mem and "NIFTY100" in mem:
                dc = _dual_class_sids(t)
                lhs = (mem["NIFTY50"] | mem["NIFTYNEXT50"]) - dc
                rhs = mem["NIFTY100"] - dc
                if lhs != rhs:
                    problems.append(("n100_partition", str(t.date()), len(lhs ^ rhs)))
            for child, parent in _SUBSET_PAIRS:
                if t < _RESTRUCTURE_DATE and (child, parent) not in _PRE_RESTRUCTURE_PAIRS:
                    continue
                if child == "NIFTYMIDCAP100" and parent in {"NIFTY200", "NIFTYMIDCAP150", "NIFTY500"} and t < _MIDCAP100_RESTRUCTURE_DATE:
                    continue
                if child in mem and parent in mem:
                    diff = mem[child] - mem[parent]
                    if diff:
                        problems.append(("subset_violation", child, parent, str(t.date()), len(diff)))

    return Result("membership", "PASS" if not problems else "FAIL",
                  f"{len(ver)} verified indices, {checked_days} multi-index trading days checked; violations={len(problems)}",
                  problems[:20])


def _verified_days_by_index(cov: pd.DataFrame) -> dict[str, int]:
    v = cov[cov["status"] == "VERIFIED"]
    days = (pd.to_datetime(v["to_date"]) - pd.to_datetime(v["from_date"])).dt.days + 1
    return days.groupby(v["index_key"]).sum().astype(int).to_dict()


def check_coverage_baseline() -> Result:
    """Verified coverage may not shrink: compare calendar days VERIFIED per index with data/curated/coverage_baseline.csv.

    A membership error does not fail check_membership; it only removes VERIFIED days. This is the check that notices.
    To accept a deliberate change, regenerate the baseline (write_coverage_baseline) and commit it."""
    cov_p = paths.BUILD / "membership" / "coverage.parquet"
    base_p = paths.CURATED / "coverage_baseline.csv"
    if not cov_p.exists():
        return Result("coverage_baseline", "FAIL", "missing coverage.parquet")
    if not base_p.exists():
        return Result("coverage_baseline", "FAIL", "no data/curated/coverage_baseline.csv")
    now = _verified_days_by_index(pd.read_parquet(cov_p))
    base = pd.read_csv(base_p).set_index("index_key")["verified_days"].to_dict()
    lost = [(k, b, now.get(k, 0)) for k, b in base.items() if now.get(k, 0) < b]
    gained = [(k, base.get(k, 0), n) for k, n in now.items() if n > base.get(k, 0)]
    if lost:
        return Result("coverage_baseline", "FAIL",
                      f"{len(lost)} indices lost verified days vs baseline (index, baseline, now)", lost[:20])
    if gained:
        return Result("coverage_baseline", "WARN",
                      f"{len(gained)} indices gained verified days; regenerate the baseline to lock them in", gained[:20])
    return Result("coverage_baseline", "PASS", f"{len(base)} indices at or above baseline")


def write_coverage_baseline() -> Path:
    cov = pd.read_parquet(paths.BUILD / "membership" / "coverage.parquet")
    d = _verified_days_by_index(cov)
    p = paths.CURATED / "coverage_baseline.csv"
    pd.DataFrame(sorted(d.items()), columns=["index_key", "verified_days"]).to_csv(p, index=False)
    return p


_RATCHET_FILE = "ratchet_baseline.csv"


def _ratchet_current(t: pd.DataFrame | None = None) -> dict:
    """The three quantities that may not rise: close-outside-range rows, UNEXPLAINED adjusted moves
    (build/adjustment_gaps.csv, written by check_adjusted_continuity) and rejected share actions
    (build/actions/gate_log.parquet). Keys use the last symbol, which survives a change of sec_id labels."""
    t = bhavcopy.load() if t is None else t
    gaps = paths.BUILD / "adjustment_gaps.csv"
    if not gaps.exists():
        raise FileNotFoundError("build/adjustment_gaps.csv missing: run check adjusted_continuity first")
    g = pd.read_csv(gaps)
    un = g[g["class"] == "UNEXPLAINED"]
    gl = pd.read_parquet(paths.BUILD / "actions" / "gate_log.parquet")
    sec = pd.read_parquet(paths.BUILD / "identity" / "securities.parquet").set_index("sec_id")["last_symbol"]
    rej = gl[gl.decision == "REJECTED"]
    return {"out_of_range": _close_outside_range(t),
            "unexplained": {f"{r.symbol}|{str(r.date)[:10]}" for r in un.itertuples()},
            "rejected": {f"{sec.get(r.sec_id, r.sec_id)}|{str(r.eff_date)[:10]}" for r in rej.itertuples()}}


def write_ratchet_baseline() -> Path:
    """Accept the current counts as the new ceiling (a deliberate act; commit the file)."""
    cur = _ratchet_current()
    rows = [("out_of_range_closes", "", cur["out_of_range"])]
    rows += [("unexplained_move", k, "") for k in sorted(cur["unexplained"])]
    rows += [("rejected_action", k, "") for k in sorted(cur["rejected"])]
    p = paths.CURATED / _RATCHET_FILE
    pd.DataFrame(rows, columns=["metric", "key", "value"]).to_csv(p, index=False)
    return p


def check_ratchet_baseline() -> Result:
    """Counts of close-outside-range rows, UNEXPLAINED adjusted moves and REJECTED share actions may not
    rise above data/curated/ratchet_baseline.csv: a rise (or any new item) is FAIL, a fall is WARN.

    This is what notices a price cell or a corporate-action ratio edited so that the manifest still matches.
    It is a tripwire, not a proof: a price edit consistent with the manifest that creates no new flag is
    caught only by an independent price source (audit stage 2.4)."""
    p = paths.CURATED / _RATCHET_FILE
    if not p.exists():
        return Result("ratchet_baseline", "FAIL", f"no data/curated/{_RATCHET_FILE}")
    try:
        cur = _ratchet_current()
    except FileNotFoundError as e:
        return Result("ratchet_baseline", "FAIL", str(e))
    b = pd.read_csv(p, dtype=str, keep_default_na=False)
    base_oor = int(b.loc[b.metric == "out_of_range_closes", "value"].iloc[0])
    base_un = set(b.loc[b.metric == "unexplained_move", "key"])
    base_rej = set(b.loc[b.metric == "rejected_action", "key"])
    new_un, gone_un = sorted(cur["unexplained"] - base_un), sorted(base_un - cur["unexplained"])
    new_rej, gone_rej = sorted(cur["rejected"] - base_rej), sorted(base_rej - cur["rejected"])
    rose = cur["out_of_range"] > base_oor or new_un or new_rej
    fell = cur["out_of_range"] < base_oor or gone_un or gone_rej
    msg = (f"close outside range {cur['out_of_range']} (baseline {base_oor}); "
           f"unexplained adjusted moves {len(cur['unexplained'])} (baseline {len(base_un)}, new {len(new_un)}, gone {len(gone_un)}); "
           f"rejected share actions {len(cur['rejected'])} (baseline {len(base_rej)}, new {len(new_rej)}, gone {len(gone_rej)})")
    detail = [("new_unexplained", x) for x in new_un[:10]] + [("new_rejected", x) for x in new_rej[:10]]
    if rose:
        return Result("ratchet_baseline", "FAIL", msg, detail)
    if fell:
        return Result("ratchet_baseline", "WARN", msg + "; regenerate the baseline to lock in the improvement")
    return Result("ratchet_baseline", "PASS", msg)


ALL = [check_manifest, check_bhavcopy_lossless, check_overlap_days, check_calendar, check_table_sanity,
       check_identity, check_actions, check_adjusted_continuity, check_indices,
       check_curated_provenance, check_membership, check_coverage_baseline, check_ratchet_baseline]


def run(names: list[str] | None = None) -> list[Result]:
    out = []
    for fn in ALL:
        if names and fn.__name__.replace("check_", "") not in names:
            continue
        try:
            out.append(fn())
        except Exception as e:  # a check that cannot run is a failure, not a pass
            out.append(Result(fn.__name__.replace("check_", ""), "FAIL", f"check crashed: {type(e).__name__}: {e}"))
        print(f"[{out[-1].status}] {out[-1].name}: {out[-1].summary}", flush=True)
    rep = paths.BUILD / "verify_report.json"
    rep.write_text(json.dumps([asdict(r) for r in out], indent=1, default=str), encoding="utf-8")
    return out
