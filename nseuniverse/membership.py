"""Index membership by event replay.

An event is (index, date, company name, IN | OUT, source). Membership on a date is the set
obtained by replaying all events up to and including that date, starting from empty at launch.
Nothing is estimated: a company name is resolved to a security only by an exact normalised-name
match against names NSE itself published (EQUITY_L, UDiFF instrument names, symbolchange.csv,
press-release symbol tables) or by a curated alias that cites its source. Near matches are only
suggested in the unresolved report; they are never applied.

Coverage is explicit. For each index the build records the dates over which the replay is
trusted: from the first event until the last source event, and only if every event in that span
resolved and the size checks passed. verify.py enforces this; the API refuses other dates.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import indices, paths

_SUFFIX = re.compile(r"\b(limited|ltd|ltd\.|company|co|corporation|corp|inc|the)\b")


def norm_name(s: str) -> str:
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s) if re.search(r"\(\s*(india|i)\s*\)", s) is None else s.replace("(", " ").replace(")", " ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_workbook(path: Path | None = None) -> pd.DataFrame:
    import xlrd
    p = path or (paths.HELD / "IndexInclExcl.xls")
    wb = xlrd.open_workbook(p)
    rows = []
    for sh in wb.sheets():
        for r in range(1, sh.nrows):
            idx, dte, nm, desc = sh.row_values(r)[:4]
            if not str(nm).strip():
                continue
            if isinstance(dte, float):
                d = pd.Timestamp(xlrd.xldate_as_datetime(dte, wb.datemode))
            else:
                d = pd.to_datetime(str(dte).strip(), format="%d-%m-%Y", errors="coerce")
            action = "IN" if str(desc).lower().startswith("incl") else ("OUT" if str(desc).lower().startswith("excl") else "?")
            rows.append({"index_name": str(idx).strip(), "sheet": sh.name, "date": d, "company": str(nm).strip(),
                         "action": action, "source": f"held:IndexInclExcl.xls#{sh.name}"})
    df = pd.DataFrame(rows)
    m = indices.name_map()
    df["index_key"] = df["index_name"].map(lambda n: m.get(indices.key(n), indices.key(n)))
    return df


class NameBook:
    """normalised company name -> set of symbols, from NSE-published tables only."""

    def __init__(self):
        self.by_name: dict[str, set[str]] = {}
        self.src: dict[tuple[str, str], str] = {}
        self.window: dict[tuple[str, str], tuple] = {}   # (name, symbol) -> (valid_from, valid_to) for dated aliases

    def add(self, name, symbol, source, valid_from=None, valid_to=None):
        if not isinstance(name, str) or not isinstance(symbol, str) or not name.strip():
            return
        k = norm_name(name)
        if k:
            self.by_name.setdefault(k, set()).add(symbol.strip())
            self.src.setdefault((k, symbol.strip()), source)
            if isinstance(valid_from, str) or isinstance(valid_to, str):
                self.window[(k, symbol.strip())] = (pd.Timestamp(valid_from) if isinstance(valid_from, str) else None,
                                                    pd.Timestamp(valid_to) if isinstance(valid_to, str) else None)

    @classmethod
    def build(cls, bhav: pd.DataFrame | None = None) -> "NameBook":
        nb = cls()
        eq = paths.HELD / "EQUITY_L.csv"
        if eq.exists():
            e = pd.read_csv(eq, dtype=str, encoding="latin1")
            e.columns = [c.strip() for c in e.columns]
            for r in e.itertuples():
                nb.add(r._2, r.SYMBOL, "EQUITY_L")
        sc = paths.HELD / "symbolchange.csv"
        if sc.exists():
            s = pd.read_csv(sc, dtype=str, encoding="latin1", keep_default_na=False)
            s.columns = [c.strip().upper() for c in s.columns]
            for r in s.itertuples():
                nb.add(r._1, r._2, "symbolchange(old)"); nb.add(r._1, r._3, "symbolchange(new)")
        if bhav is not None and "name" in bhav:
            u = bhav[bhav["name"].notna()][["name", "symbol"]].drop_duplicates()
            for r in u.itertuples():
                nb.add(r.name, r.symbol, "udiff")
        dl = paths.RAW / "nse_lists" / "delisted.csv"
        if dl.exists():
            d = pd.read_csv(dl, dtype=str, encoding="latin1", usecols=[0, 1])
            d.columns = ["symbol", "company"]
            for r in d.itertuples():
                nb.add(r.company, r.symbol, "delisted.csv")
        pr = paths.CURATED / "press_name_symbol.csv"       # produced from press-release tables
        if pr.exists():
            for r in pd.read_csv(pr, dtype=str).itertuples():
                nb.add(r.company, r.symbol, f"press:{r.source}")
        al = paths.CURATED / "name_aliases.csv"             # hand entries, each citing a source
        if al.exists():
            a = pd.read_csv(al, dtype=str)
            for c in ("valid_from", "valid_to"):
                if c not in a:
                    a[c] = None
            for r in a.itertuples():
                nb.add(r.company, r.symbol, f"alias:{r.source}", r.valid_from, r.valid_to)
        return nb

    def candidates(self, company: str, on=None) -> set[str]:
        k = norm_name(company)
        out = set()
        for sym in self.by_name.get(k, set()):
            w = self.window.get((k, sym))
            if w and on is not None and ((w[0] is not None and on < w[0]) or (w[1] is not None and on > w[1])):
                continue
            out.add(sym)
        return out

    def suggest(self, company: str, n=3):
        return difflib.get_close_matches(norm_name(company), list(self.by_name), n=n, cutoff=0.88)


def resolve(events: pd.DataFrame, nb: NameBook, seg_map: pd.DataFrame, slack_days: int = 45) -> pd.DataFrame:
    """Attach sec_id to each event. A symbol candidate is accepted if it traded within slack_days
    of the event date; if several securities qualify the event is left ambiguous."""
    seg_by_sym = {s: g for s, g in seg_map.groupby("symbol")}
    sids, notes = [], []
    cache = {}
    data_start = seg_map["start"].min()
    sec_range = {sid: (g["start"].min(), g["end"].max()) for sid, g in seg_map.groupby("sec_id")}
    for r in events.itertuples():
        key = (r.company, r.date if r.company in nb.by_name or True else r.date)
        if key in cache:
            sid, note = cache[key]
        else:
            cands = nb.candidates(r.company, r.date)
            hit = set()
            at = max(r.date, data_start)
            for sym in cands:
                g = seg_by_sym.get(sym)
                if g is None:
                    continue
                for sid in set(g.sec_id):       # the security behind this ticker, whatever it was called then
                    lo, hi = sec_range[sid]
                    if lo <= at + pd.Timedelta(days=slack_days) and hi >= at - pd.Timedelta(days=slack_days):
                        hit.add(sid)
            if len(hit) == 1:
                sid, note = next(iter(hit)), "OK"
            elif len(hit) > 1:
                sid, note = None, "AMBIGUOUS:" + ",".join(sorted(hit))
            elif cands:
                sid, note = None, "NOT_TRADING_AT_EVENT_DATE:" + ",".join(sorted(cands))
            else:
                sid, note = None, "NAME_UNKNOWN"
            cache[key] = (sid, note)
        sids.append(sid); notes.append(note)
    out = events.copy()
    out["sec_id"] = sids
    out["resolution"] = notes
    return out


def mark_relevance(ev: pd.DataFrame, since="2004-01-01") -> pd.DataFrame:
    """relevant = the company is a member of that index on or after `since` (by name replay).
    Events of companies that joined and left before `since` cannot affect any covered date."""
    ev = ev.copy()
    since = pd.Timestamp(since)
    rel = {}
    orphan = set()
    ev["_nk"] = ev["company"].map(norm_name)
    for (k, c), g in ev.sort_values(["date", "action"], kind="mergesort").groupby(["index_key", "_nk"]):
        start, ok = None, False
        for r in g.itertuples():
            if r.action == "IN" and start is None:
                start = r.date
            elif r.action == "OUT" and start is not None:
                ok = ok or r.date > since
                start = None
            else:      # OUT with no recorded IN (a launch member) or IN while already a member: informational only
                orphan.add(r.Index)
        rel[(k, c)] = ok or start is not None
    ev["relevant"] = [rel[(k, c)] for k, c in zip(ev.index_key, ev["_nk"])]
    ev["orphan"] = ev.index.isin(orphan)
    return ev.drop(columns="_nk")


def replay(ev: pd.DataFrame) -> pd.DataFrame:
    """Events (resolved) -> membership intervals [from_date, to_date). to_date NaT = still a member."""
    rows = []
    for (k, sid), g in ev[ev.sec_id.notna()].sort_values(["date", "action"], kind="mergesort").groupby(["index_key", "sec_id"]):
        start = None
        for r in g.itertuples():
            if r.action == "IN" and start is None:
                start = r.date
            elif r.action == "OUT" and start is not None:
                rows.append({"index_key": k, "sec_id": sid, "from_date": start, "to_date": r.date})
                start = None
        if start is not None:
            rows.append({"index_key": k, "sec_id": sid, "from_date": start, "to_date": pd.NaT})
    return pd.DataFrame(rows, columns=["index_key", "sec_id", "from_date", "to_date"])


def members(intervals: pd.DataFrame, index_key: str, as_of) -> set[str]:
    t = pd.Timestamp(as_of)
    x = intervals[intervals.index_key == index_key]
    m = (x.from_date.isna() | (x.from_date <= t)) & (x.to_date.isna() | (x.to_date > t))
    return set(x.loc[m, "sec_id"])


def size_series(intervals: pd.DataFrame, index_key: str, days) -> pd.Series:
    x = intervals[intervals.index_key == index_key]
    days = pd.DatetimeIndex(days)
    delta = pd.Series(0, index=days)
    for r in x.itertuples():
        i = days.searchsorted(r.from_date, side="left")
        delta.iloc[i:] += 1 if i < len(days) else 0
        if pd.notna(r.to_date):
            j = days.searchsorted(r.to_date, side="left")
            if j < len(days):
                delta.iloc[j:] -= 1
    return delta


def build(build_dir: Path | None = None) -> dict:
    from . import bhavcopy
    build_dir = build_dir or paths.BUILD
    out = build_dir / "membership"
    out.mkdir(parents=True, exist_ok=True)
    t = bhavcopy.load(build_dir=build_dir)
    seg_map = pd.read_parquet(build_dir / "identity" / "segments.parquet")
    nb = NameBook.build(t[["name", "symbol"]].drop_duplicates() if "name" in t else None)
    ev = load_workbook()
    ev = resolve(ev, nb, seg_map)
    ev = mark_relevance(ev)
    ev["suggestion"] = [(", ".join(nb.suggest(c)) if n != "OK" else "") for c, n in zip(ev.company, ev.resolution)]
    ev.to_parquet(out / "events_resolved.parquet", index=False, compression="zstd", compression_level=9)
    iv, cov = build_anchored(ev, seg_map, t[["date", "sec_id", "series"]], paths.ROOT)
    others = sorted(set(ev.index_key) - set(ANCHORED))
    rel = ev[ev.relevant]
    for k in others:
        g = rel[rel.index_key == k]
        cov = pd.concat([cov, pd.DataFrame([(k, pd.NaT, pd.NaT, "UNVERIFIED",
            f"no launch list in the source and no constituent anchor loaded; {int((g.resolution != 'OK').sum())} of {len(g)} relevant events have unresolved company names")],
            columns=cov.columns)], ignore_index=True)
    iv.to_parquet(out / "intervals.parquet", index=False, compression="zstd", compression_level=9)
    cov.to_parquet(out / "coverage.parquet", index=False, compression="zstd", compression_level=9)
    un = ev[(ev.resolution != "OK") & ev.relevant].drop_duplicates(["company", "resolution"])
    un[["company", "index_key", "date", "resolution", "suggestion"]].to_csv(out / "unresolved.csv", index=False)
    return {"events": len(ev), "resolved": int((ev.resolution == "OK").sum()), "intervals": len(iv), "verified_windows": int((cov.status == "VERIFIED").sum()),
            "unresolved_distinct_names": int(un.company.nunique())}


def anchor_intervals(anchor: set[str], anchor_date, events: pd.DataFrame) -> pd.DataFrame:
    """Membership intervals by rolling events BACKWARD from a known constituent list.

    The workbook lists changes after launch, not the launch list, so a forward replay cannot
    start from empty. The official list on `anchor_date` is the one complete set we have; undoing
    each event (an inclusion on day d means the company was absent before d; an exclusion means it
    was present before d) gives the set on every earlier date. A company still a member before the
    earliest event gets from_date = NaT (member since before the first recorded change).
    `events` needs columns date, sec_id, action (IN/OUT), effective = first day the change applies."""
    ev = events[events.date <= pd.Timestamp(anchor_date)].sort_values("date", ascending=False, kind="mergesort")
    open_to = {s: pd.NaT for s in anchor}        # sec_id -> end of the interval being built (NaT = still a member)
    rows = []
    for d, g in ev.groupby("date", sort=False):
        for r in g[g.action == "IN"].itertuples():
            if r.sec_id in open_to:
                rows.append((r.sec_id, d, open_to.pop(r.sec_id)))
        for r in g[g.action == "OUT"].itertuples():
            if r.sec_id not in open_to:
                open_to[r.sec_id] = d
    rows += [(s, pd.NaT, t) for s, t in open_to.items()]
    return pd.DataFrame(rows, columns=["sec_id", "from_date", "to_date"])


def size_on(iv: pd.DataFrame, days) -> pd.Series:
    """Number of members on each day for intervals [from_date, to_date); NaT from = since forever."""
    days = pd.DatetimeIndex(days)
    out = np.zeros(len(days), dtype=int)
    for r in iv.itertuples():
        lo = 0 if pd.isna(r.from_date) else days.searchsorted(r.from_date, side="left")
        hi = len(days) if pd.isna(r.to_date) else days.searchsorted(r.to_date, side="left")
        if hi > lo:
            out[lo:hi] += 1
    return pd.Series(out, index=days)


# index_key -> (official size, anchor file of current constituents). Only indices with a fixed
# size can be checked day by day; others stay UNVERIFIED until a stronger check exists.
ANCHORED = {"NIFTY50": (50, "data/raw/constituents/2026-11-15/ind_nifty50list.csv")}
TRADE_WINDOW = 3     # a member must have traded in an equity series within +-3 sessions of each day


def _sid(seg: pd.DataFrame, symbol: str, at, slack=10):
    g = seg[(seg.symbol == symbol) & (seg.start <= at + pd.Timedelta(days=slack)) & (seg.end >= at - pd.Timedelta(days=slack))]
    return g.sec_id.iloc[0] if len(g) else None


def _ranges(days: pd.DatetimeIndex, ok: np.ndarray):
    out, start = [], None
    for i, flag in enumerate(ok):
        if flag and start is None:
            start = i
        if (not flag or i == len(ok) - 1) and start is not None:
            end = i if flag else i - 1
            out.append((days[start], days[end]))
            start = None
    return out


def build_anchored(ev_resolved: pd.DataFrame, seg: pd.DataFrame, t: pd.DataFrame, root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    from . import series
    t = t[t["series"].isin(series.EQUITY_SERIES)]
    days = pd.DatetimeIndex(sorted(t["date"].unique()))
    pos = {d: i for i, d in enumerate(days)}
    traded = {sid: np.array(sorted(pos[d] for d in g["date"].unique())) for sid, g in t.groupby("sec_id")}
    cur = pd.read_csv(paths.CURATED / "index_events_press.csv", parse_dates=["date"]) if (paths.CURATED / "index_events_press.csv").exists() else pd.DataFrame()
    ivs, cov = [], []
    for k, (n, anchor_file) in ANCHORED.items():
        w = ev_resolved[(ev_resolved.index_key == k) & (ev_resolved.resolution == "OK")][["date", "sec_id", "action"]]
        c = cur[cur.index_key == k].copy() if len(cur) else pd.DataFrame(columns=["date", "symbol", "action"])
        c["sec_id"] = [_sid(seg, s, d - pd.Timedelta(days=3) if a == "OUT" else d + pd.Timedelta(days=3))
                       for s, d, a in zip(c.symbol, c.date, c.action)]
        last_wb = w.date.max()
        events = pd.concat([w[w.date <= c.date.min()] if len(c) else w, c[["date", "sec_id", "action"]]]).dropna()
        anchor_syms = pd.read_csv(root / anchor_file).Symbol.tolist()
        anchor_date = pd.Timestamp(Path(anchor_file).parent.name)
        asids = {_sid(seg, s, days[-1] - pd.Timedelta(days=2)) for s in anchor_syms}
        iv = anchor_intervals(asids - {None}, anchor_date, events)
        iv.insert(0, "index_key", k)
        sz = size_on(iv, days).values
        ok = sz == n
        # every member must have traded within +-TRADE_WINDOW sessions of the day
        for r in iv.itertuples():
            lo = 0 if pd.isna(r.from_date) else int(days.searchsorted(r.from_date, side="left"))
            hi = len(days) if pd.isna(r.to_date) else int(days.searchsorted(r.to_date, side="left"))
            tr = traded.get(r.sec_id, np.array([], dtype=int))
            for i in range(lo, hi):
                j = np.searchsorted(tr, i)
                near = (j < len(tr) and tr[j] - i <= TRADE_WINDOW) or (j > 0 and i - tr[j - 1] <= TRADE_WINDOW)
                if not near:
                    ok[i] = False
        good = _ranges(days, ok)
        for a, b in good:
            cov.append((k, a, b, "VERIFIED", f"exactly {n} members on every trading day and every member traded within +-{TRADE_WINDOW} sessions"))
        bad_days = int((~ok).sum())
        cov.append((k, days[0], days[-1], "PARTIAL", f"{bad_days} of {len(days)} trading days fail the size/trading check; "
                                                 f"gaps come from names or tickers not yet linked (see unresolved.csv)"))
        ivs.append(iv)
    return (pd.concat(ivs, ignore_index=True) if ivs else pd.DataFrame(columns=["index_key", "sec_id", "from_date", "to_date"]),
            pd.DataFrame(cov, columns=["index_key", "from_date", "to_date", "status", "reason"]))
