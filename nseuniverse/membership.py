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
    s = s.replace("(", " ").replace(")", " ")
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
        self.exclusive: dict[str, list] = {}             # name -> [(symbol, valid_from, valid_to)]: inside its window the alias replaces every other candidate

    def add(self, name, symbol, source, valid_from=None, valid_to=None, exclusive=False):
        if not isinstance(name, str) or not isinstance(symbol, str) or not name.strip():
            return
        k = norm_name(name)
        if k:
            self.by_name.setdefault(k, set()).add(symbol.strip())
            self.src.setdefault((k, symbol.strip()), source)
            lo = pd.Timestamp(valid_from) if isinstance(valid_from, str) else None
            hi = pd.Timestamp(valid_to) if isinstance(valid_to, str) else None
            if exclusive:
                self.exclusive.setdefault(k, []).append((symbol.strip(), lo, hi))
            elif lo is not None or hi is not None:
                self.window[(k, symbol.strip())] = (lo, hi)

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
        ca = paths.HELD / "raw_corporate_actions_1995_2026.json"
        if ca.exists():
            import json
            for r in json.loads(ca.read_text(encoding="utf-8")):
                comp, sym = r.get("comp"), r.get("symbol")
                if comp and sym:
                    nb.add(comp, sym, "corporate_actions")
        al = paths.CURATED / "name_aliases.csv"             # hand entries, each citing a source
        if al.exists():
            a = pd.read_csv(al, dtype=str)
            for c in ("valid_from", "valid_to", "exclusive"):
                if c not in a:
                    a[c] = None
            for r in a.itertuples():
                nb.add(r.company, r.symbol, f"alias:{r.source}", r.valid_from, r.valid_to, exclusive=(str(r.exclusive).strip().lower() in ("yes", "true", "1")))
        return nb

    def candidates(self, company: str, on=None) -> set[str]:
        k = norm_name(company)
        if on is not None:
            ex = {sym for sym, lo, hi in self.exclusive.get(k, []) if (lo is None or on >= lo) and (hi is None or on <= hi)}
            if ex:
                return ex
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
    ev = mark_relevance(ev, since="2007-01-01")
    ev["suggestion"] = [(", ".join(nb.suggest(c)) if n != "OK" else "") for c, n in zip(ev.company, ev.resolution)]
    ev.to_parquet(out / "events_resolved.parquet", index=False, compression="zstd", compression_level=9)
    iv, cov = build_anchored(ev, seg_map, t[["date", "sec_id", "series"]], paths.ROOT, contradictions_out=out / "contradictions.csv")
    cov = clip_to_launch(cov)
    uni = pd.read_csv(paths.CURATED / "index_universe.csv") if (paths.CURATED / "index_universe.csv").exists() else pd.DataFrame(columns=["category", "index_name", "index_key"])
    scope = dict(zip(uni.index_key, uni.category))
    others = sorted((set(ev.index_key) | set(scope)) - set(ANCHORED))
    rel = ev[ev.relevant]
    for k in others:
        g = rel[rel.index_key == k]
        if len(g):
            why = (f"no launch list in the source and no constituent anchor loaded; "
                   f"{int((g.resolution != 'OK').sum())} of {len(g)} relevant events have unresolved company names")
        else:
            why = "no change history for this index in the held sources (NSE workbook ends 2020 and does not list it); press releases only from ~2020"
        cov = pd.concat([cov, pd.DataFrame([(k, pd.NaT, pd.NaT, "UNVERIFIED", why)], columns=cov.columns)], ignore_index=True)
    cov["category"] = cov["index_key"].map(scope).fillna("outside_scope")
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
    open_to = {s: pd.NaT for s in sorted(anchor)}        # sec_id -> end of the interval being built (NaT = still a member)
    rows = []
    for d, g in ev.groupby("date", sort=False):
        for r in g[g.action == "IN"].itertuples():
            if r.sec_id in open_to:
                rows.append((r.sec_id, d, open_to.pop(r.sec_id)))
        for r in g[g.action == "OUT"].itertuples():
            if r.sec_id not in open_to:
                open_to[r.sec_id] = d
    rows += [(s, pd.NaT, open_to[s]) for s in sorted(open_to)]  # sorted: set/dict order must not leak into output
    return pd.DataFrame(rows, columns=["sec_id", "from_date", "to_date"])


def contradictions(anchor: set[str], anchor_date, events: pd.DataFrame) -> pd.DataFrame:
    """Events that cannot be undone consistently when rolling back from `anchor`.

    An IN for a security that is not a member at that point (it left later, but no exclusion is
    recorded), or an OUT for one already a member, means a change is missing from the sources.
    `anchor_intervals` has to skip such an event, so every date from it onward may hold wrong members
    even when the count is right. Returns columns date, sec_id, action."""
    ev = events[events.date <= pd.Timestamp(anchor_date)].sort_values("date", ascending=False, kind="mergesort")
    open_ = set(anchor)
    bad = []
    for d, g in ev.groupby("date", sort=False):
        for r in g[g.action == "IN"].itertuples():
            if r.sec_id in open_:
                open_.discard(r.sec_id)
            else:
                bad.append((d, r.sec_id, "IN"))
        for r in g[g.action == "OUT"].itertuples():
            if r.sec_id in open_:
                bad.append((d, r.sec_id, "OUT"))
            open_.add(r.sec_id)
    return pd.DataFrame(bad, columns=["date", "sec_id", "action"])


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
ANCHORED = {"NIFTY50": (50, "data/raw/constituents/2026-11-15/ind_nifty50list.csv"),
            "NIFTYNEXT50": (50, "data/raw/constituents/2026-11-15/ind_niftynext50list.csv"),
            "NIFTY100": (100, "data/raw/constituents/2026-11-15/ind_nifty100list.csv"),
            "NIFTY500": (500, "data/raw/constituents/2026-11-15/ind_nifty500list.csv"),
            "NIFTY200": (200, "data/raw/constituents/2026-11-19/ind_nifty200list.csv"),
            "NIFTYLARGEMIDCAP250": (250, "data/raw/constituents/2026-11-19/ind_niftylargemidcap250list.csv"),
            "NIFTYMIDCAP100": (100, "data/raw/constituents/2026-11-19/ind_niftymidcap100list.csv"),
            "NIFTYMIDCAP50": (50, "data/raw/constituents/2026-11-19/ind_niftymidcap50list.csv"),
            "NIFTYSMALLCAP100": (100, "data/raw/constituents/2026-11-19/ind_niftysmallcap100list.csv"),
            "NIFTYSMALLCAP50": (50, "data/raw/constituents/2026-11-19/ind_niftysmallcap50list.csv"),
            "NIFTYAUTO": (15, "data/raw/constituents/2026-11-19/ind_niftyautolist.csv"),
            "NIFTYBANK": (12, "data/raw/constituents/2026-11-19/ind_niftybanklist.csv"),
            "NIFTYFINANCIALSERVICES": (20, "data/raw/constituents/2026-11-19/ind_niftyfinancelist.csv"),
            "NIFTYFMCG": (15, "data/raw/constituents/2026-11-19/ind_niftyfmcglist.csv"),
            "NIFTYIT": (10, "data/raw/constituents/2026-11-19/ind_niftyitlist.csv"),
            "NIFTYMEDIA": (10, "data/raw/constituents/2026-11-19/ind_niftymedialist.csv"),
            "NIFTYMETAL": (15, "data/raw/constituents/2026-11-19/ind_niftymetallist.csv"),
            "NIFTYPHARMA": (10, "data/raw/constituents/2026-11-19/ind_niftypharmalist.csv"),
            "NIFTYPSUBANK": (12, "data/raw/constituents/2026-11-19/ind_niftypsubanklist.csv"),
            "NIFTYREALTY": (10, "data/raw/constituents/2026-11-19/ind_niftyrealtylist.csv")}

# Verified Composite / Identical-Constituent Index Support:
# index_key -> (official size, anchor file on 2026-11-19, rule tuple)
# Rule is ("EQ", parent) or ("DIFF", parent1, parent2)
COMPOSITE_ANCHORS: dict[str, tuple[int, str, tuple[str, ...]]] = {
    "NIFTY500MULTICAP502525": (500, "data/raw/constituents/2026-11-19/ind_nifty500multicap502525_list.csv", ("EQ", "NIFTY500")),
    "NIFTY500LARGEMIDSMALLEQUALCAPWEIGHTED": (500, "data/raw/constituents/2026-11-19/ind_nifty500largemidsmallequalcapweighted_list.csv", ("EQ", "NIFTY500")),
    "NIFTYMIDSMALLCAP400": (400, "data/raw/constituents/2026-11-19/ind_niftymidsmallcap400list.csv", ("DIFF", "NIFTY500", "NIFTY100")),
    "NIFTYMIDSMALLCAP4005050": (400, "data/raw/constituents/2026-11-19/ind_niftymidsmallcap4005050_list.csv", ("DIFF", "NIFTY500", "NIFTY100")),
    "NIFTYMIDCAP150": (150, "data/raw/constituents/2026-11-19/ind_niftymidcap150list.csv", ("DIFF", "NIFTYLARGEMIDCAP250", "NIFTY100")),
    "NIFTYSMALLCAP250": (250, "data/raw/constituents/2026-11-19/ind_niftysmallcap250list.csv", ("DIFF", "NIFTY500", "NIFTYLARGEMIDCAP250")),
    "NIFTYFINANCIALSERVICES2550": (20, "data/raw/constituents/2026-11-19/ind_niftyfinancialservices25-50list.csv", ("EQ", "NIFTYFINANCIALSERVICES")),
}

# index_key -> first date that must be verified. New indices use 2007-01-01 (adjusted prices are not verified before it, and the
# backward replay then never has to resolve earlier events). Days before the floor are out of scope: they are neither verified nor
# counted as failures. Decision 2026-11-16: every index is verified from 2007-01-01 only.
FLOORS: dict[str, str] = {
    "NIFTY50": "2010-01-01",
    "NIFTYNEXT50": "2010-01-01",
    "NIFTY100": "2010-01-01",
    "NIFTY500": "2010-01-01",
    "NIFTY200": "2011-07-19",   # launched 2011-07-19 (ind_prs18072011)
    "NIFTYLARGEMIDCAP250": "2016-04-01",   # index launched 2016-04-01; earlier history has no documented source (audit S2-4, A10)
    "NIFTYMIDCAP100": "2010-01-01",
    "NIFTYMIDCAP50": "2010-01-01",
    "NIFTYSMALLCAP100": "2010-01-01",
    "NIFTYSMALLCAP50": "2010-01-01",
    "NIFTYAUTO": "2010-01-01", "NIFTYBANK": "2010-01-01", "NIFTYFINANCIALSERVICES": "2010-01-01", "NIFTYFMCG": "2010-01-01",
    "NIFTYIT": "2010-01-01", "NIFTYMEDIA": "2010-01-01", "NIFTYMETAL": "2011-07-12",   # launched 2011-07-12 (ind_prs11072011)
    "NIFTYPHARMA": "2010-01-01",
    "NIFTYPSUBANK": "2010-01-01", "NIFTYREALTY": "2010-01-01",
    "NIFTY500MULTICAP502525": "2010-01-01",
    "NIFTY500LARGEMIDSMALLEQUALCAPWEIGHTED": "2010-01-01",
    "NIFTYMIDSMALLCAP400": "2010-01-01",
    "NIFTYMIDSMALLCAP4005050": "2010-01-01",
    "NIFTYMIDCAP150": "2010-01-01",
    "NIFTYSMALLCAP250": "2010-01-01",
    "NIFTYFINANCIALSERVICES2550": "2010-01-01",
}
# index_key -> public launch date (the release announcing it, in data/raw/pressreleases/pdf/). Nothing before it is
# VERIFIED: the index did not exist. Applied after composites are derived, because a parent's computed days before its
# own launch still define a child that did exist (LargeMidcap 250 -> Midcap 150, Smallcap 250).
LAUNCHED: dict[str, str] = {
    "NIFTYMIDCAP150": "2016-04-01",                          # ind_prs22022016_1
    "NIFTYSMALLCAP250": "2016-04-01",                        # ind_prs22022016_1
    "NIFTYSMALLCAP50": "2016-04-01",                         # ind_prs22022016_1
    "NIFTYMIDSMALLCAP400": "2016-04-01",                     # ind_prs01042016
    "NIFTYLARGEMIDCAP250": "2017-11-30",                     # ind_prs30112017
    "NIFTYFINANCIALSERVICES2550": "2020-05-20",              # ind_prs20052020
    "NIFTY500MULTICAP502525": "2020-12-02",                  # ind_prs02122020
    "NIFTY500LARGEMIDSMALLEQUALCAPWEIGHTED": "2024-06-07",   # ind_prs07062024_1
    "NIFTYMIDSMALLCAP4005050": "2026-02-04",                 # ind_prs04022026
}


def clip_to_launch(cov: pd.DataFrame) -> pd.DataFrame:
    """Cut coverage rows (VERIFIED and PARTIAL) so none starts before its index existed."""
    launch = pd.to_datetime(cov.index_key.map(LAUNCHED))
    out = cov.copy()
    early = launch.notna() & (out.from_date < launch)
    out.loc[early, "from_date"] = launch[early]
    return out[~(early & (out.to_date < launch))].reset_index(drop=True)


TRADE_WINDOW = 3     # a member must have traded in an equity series within +-3 sessions of each day


def _sid(seg: pd.DataFrame, symbol: str, at, slack=10):
    g = seg[(seg.symbol == symbol) & (seg.start <= at + pd.Timedelta(days=slack)) & (seg.end >= at - pd.Timedelta(days=slack))]
    return g.sec_id.iloc[0] if len(g) else None


def extra_members(days: pd.DatetimeIndex, exc: pd.DataFrame, index_key: str) -> np.ndarray:
    """Number of documented zero-price dummy-symbol constituents held on each day (curated; each row cites its release).

    A demerger entity enters an index under a dummy symbol without anyone leaving, so the index officially has
    size + extras constituents until it is excluded. A day is VERIFIED only if the real members number exactly the
    official size AND the total equals size + extras; the dummies themselves cannot trade and are not counted as members."""
    out = np.zeros(len(days), dtype=int)
    if exc is None or not len(exc):
        return out
    for r in exc[exc.index_key == index_key].itertuples():
        out += ((days >= pd.Timestamp(r.from_date)) & (days <= pd.Timestamp(r.to_date))).astype(int) * int(r.extra_members)
    return out


def _member_mask(iv: pd.DataFrame, days: pd.DatetimeIndex, sec_id) -> np.ndarray:
    m = np.zeros(len(days), dtype=bool)
    for r in iv[iv.sec_id == sec_id].itertuples():
        lo = 0 if pd.isna(r.from_date) else int(days.searchsorted(r.from_date, side="left"))
        hi = len(days) if pd.isna(r.to_date) else int(days.searchsorted(r.to_date, side="left"))
        m[lo:hi] = True
    return m


def dual_class_securities(days: pd.DatetimeIndex, dc: pd.DataFrame, index_key: str, iv: pd.DataFrame, seg: pd.DataFrame) -> np.ndarray:
    """Extra REAL, traded securities allowed on top of the official size (curated; each row cites its release).

    NSE (22 Feb 2016 release, A.1.e): a DVR of an existing constituent makes the index hold size+1 securities but
    still `size` companies. A row counts on a day only if BOTH the named DVR security and its parent company's
    security are members on that day (so the number of companies is still the official size); otherwise it adds 0 and
    the day fails the size check. The extras are real securities: they stay subject to the trading check."""
    out = np.zeros(len(days), dtype=int)
    if dc is None or not len(dc):
        return out
    for r in dc[dc.index_key == index_key].itertuples():
        a, b = pd.Timestamp(r.from_date), pd.Timestamp(r.to_date)
        sid_x, sid_p = _sid(seg, r.symbols, a), _sid(seg, r.parent_symbol, a)
        if sid_x is None or sid_p is None:
            continue
        inside = (days >= a) & (days <= b)
        out += (inside & _member_mask(iv, days, sid_x) & _member_mask(iv, days, sid_p)).astype(int) * int(r.extra_securities)
    return out


def _active_masks(iv_df: pd.DataFrame, days: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """Map sec_id -> boolean array of length len(days) indicating active membership."""
    masks: dict[str, np.ndarray] = {}
    for r in iv_df.itertuples():
        lo = 0 if pd.isna(r.from_date) else int(days.searchsorted(r.from_date, side="left"))
        hi = len(days) if pd.isna(r.to_date) else int(days.searchsorted(r.to_date, side="left"))
        if r.sec_id not in masks:
            masks[r.sec_id] = np.zeros(len(days), dtype=bool)
        if hi > lo:
            masks[r.sec_id][lo:hi] = True
    return masks


def _masks_to_intervals(days: pd.DatetimeIndex, masks: dict[str, np.ndarray], index_key: str) -> pd.DataFrame:
    """Convert per-sec_id daily boolean masks into half-open [from_date, to_date) intervals."""
    n_days = len(days)
    rows = []
    for sid in sorted(masks.keys()):
        mask = masks[sid]
        diff = np.diff(np.pad(mask.astype(np.int8), (1, 1), "constant"))
        starts = np.where(diff == 1)[0]
        ends = np.where(diff == -1)[0] - 1
        for s_idx, e_idx in zip(starts, ends):
            from_dt = pd.NaT if s_idx == 0 else days[s_idx]
            to_dt = pd.NaT if e_idx == n_days - 1 else days[e_idx + 1]
            rows.append((index_key, sid, from_dt, to_dt))
    return pd.DataFrame(rows, columns=["index_key", "sec_id", "from_date", "to_date"])


def build_composites(ivs: list[pd.DataFrame], cov: list[tuple], days: pd.DatetimeIndex, traded: dict, seg: pd.DataFrame, exc: pd.DataFrame, root: Path) -> None:
    """Build membership intervals and verified coverage windows for composite / derived indices."""
    if not ivs:
        return

    parent_anchor_files = {
        "NIFTY500": "data/raw/constituents/2026-11-19/ind_nifty500list.csv",
        "NIFTY100": "data/raw/constituents/2026-11-19/ind_nifty100list.csv",
        "NIFTYLARGEMIDCAP250": "data/raw/constituents/2026-11-19/ind_niftylargemidcap250list.csv",
        "NIFTYFINANCIALSERVICES": "data/raw/constituents/2026-11-19/ind_niftyfinancelist.csv",
    }

    def _get_clean_syms(p_rel: str) -> set[str]:
        df = pd.read_csv(root / p_rel)
        return set(df.Symbol.dropna().astype(str).str.strip()) - {s for s in df.Symbol if str(s).startswith("DUMMY")}

    # 1. First verify exact constituent parity (sym_diff == 0) against parent anchor(s)
    for k, (n, fpath, rule) in COMPOSITE_ANCHORS.items():
        if not (root / fpath).exists():
            continue
        comp_syms = _get_clean_syms(fpath)
        op = rule[0]
        p1 = rule[1]
        p1_file = parent_anchor_files.get(p1)
        if not p1_file or not (root / p1_file).exists():
            continue
        p1_syms = _get_clean_syms(p1_file)
        if op == "EQ":
            diff = comp_syms.symmetric_difference(p1_syms)
        elif op == "DIFF":
            p2 = rule[2]
            p2_file = parent_anchor_files.get(p2)
            if not p2_file or not (root / p2_file).exists():
                continue
            p2_syms = _get_clean_syms(p2_file)
            diff = comp_syms.symmetric_difference(p1_syms - p2_syms)
        else:
            raise ValueError(f"Unknown composite rule op {op!r} for {k}")
        if len(diff) != 0:
            raise ValueError(f"Constituent parity check failed on 2026-11-19 for composite {k}: sym_diff={len(diff)}")

    # 2. Collect existing parent intervals & verified day masks
    all_iv = pd.concat(ivs, ignore_index=True)
    n_days = len(days)
    masks_by_index = {idx_k: _active_masks(all_iv[all_iv.index_key == idx_k], days) for idx_k in all_iv.index_key.unique()}

    v_days_by_index: dict[str, np.ndarray] = {}
    for item in cov:
        idx_k, a, b, status = item[0], item[1], item[2], item[3]
        if status == "VERIFIED":
            if idx_k not in v_days_by_index:
                v_days_by_index[idx_k] = np.zeros(n_days, dtype=bool)
            v_days_by_index[idx_k] |= (days >= a) & (days <= b)

    dc_p = paths.CURATED / "index_dual_class.csv"
    dcls = pd.read_csv(dc_p) if dc_p.exists() else None
    dual_by_index = {idx_k: dual_class_securities(days, dcls, idx_k, all_iv[all_iv.index_key == idx_k], seg) for idx_k in all_iv.index_key.unique()}

    # 3. For each composite, build intervals and emit coverage windows
    for k, (n, fpath, rule) in COMPOSITE_ANCHORS.items():
        op = rule[0]
        p1 = rule[1]
        if op == "EQ":
            parents = [p1]
            if p1 not in masks_by_index or p1 not in v_days_by_index:
                continue
            comp_masks = masks_by_index[p1]
            parent_v = v_days_by_index[p1]
            dual = dual_by_index.get(p1, np.zeros(n_days, dtype=int))
            # Direct interval copy with new index_key
            iv_comp = all_iv[all_iv.index_key == p1].copy()
            iv_comp["index_key"] = k
        elif op == "DIFF":
            p2 = rule[2]
            parents = [p1, p2]
            if p1 not in masks_by_index or p2 not in masks_by_index:
                continue
            if p1 not in v_days_by_index or p2 not in v_days_by_index:
                continue
            parent_v = v_days_by_index[p1] & v_days_by_index[p2]
            m1 = masks_by_index[p1]
            m2 = masks_by_index[p2]
            # NSE's derived lists do not carry a dual-class DVR that sits in the parent but not in the subtracted index
            # (archived NSE lists: MidSmallcap 400 on 2023-08-12 has 400 rows and no Tata Motors DVR while Nifty 500 had it).
            # So named dual-class securities are removed from the difference and no size allowance is made for them.
            dvr_sids = set()
            if dcls is not None and len(dcls):
                for r in dcls[dcls.index_key == p1].itertuples():
                    s_x = _sid(seg, r.symbols, pd.Timestamp(r.from_date))
                    if s_x is not None:
                        dvr_sids.add(s_x)
            comp_masks = {}
            for sid in m1:
                if sid in dvr_sids:
                    continue
                diff_m = m1[sid] & (~m2.get(sid, np.zeros(n_days, dtype=bool)))
                if np.any(diff_m):
                    comp_masks[sid] = diff_m
            dual = np.zeros(n_days, dtype=int)
            iv_comp = _masks_to_intervals(days, comp_masks, k)

        # Check membership size on each day
        sz = np.zeros(n_days, dtype=int)
        for sid, m_arr in comp_masks.items():
            sz += m_arr.astype(int)

        ok = parent_v & (sz == n + dual)

        # Trading check: every member in comp_masks traded within +-TRADE_WINDOW sessions
        for sid, m_arr in comp_masks.items():
            tr = traded.get(sid, np.array([], dtype=int))
            active_indices = np.where(m_arr & ok)[0]
            for i in active_indices:
                j = np.searchsorted(tr, i)
                near = (j < len(tr) and tr[j] - i <= TRADE_WINDOW) or (j > 0 and i - tr[j - 1] <= TRADE_WINDOW)
                if not near:
                    ok[i] = False

        floor = FLOORS.get(k)
        ok, in_scope = apply_floor(ok, days, floor)
        extra = extra_members(days, exc, k)
        good = _ranges(days, ok)
        for a, b in good:
            nx = int((extra[(days >= a) & (days <= b)] > 0).sum())
            nd = int((dual[(days >= a) & (days <= b)] > 0).sum())
            parents_str = rule[1] if op == "EQ" else f"{rule[1]} - {rule[2]}"
            cov.append((k, a, b, "VERIFIED", f"composite {op} parity (sym_diff == 0) with verified parent ({parents_str}); "
                                             f"exactly {n} members on every trading day and every member traded within +-{TRADE_WINDOW} sessions"
                        + (f"; {nd} of these days held {n + 1} securities of {n} companies (a DVR, index_dual_class.csv)" if nd else "")
                        + (f"; {nx} of these days also had documented zero-price dummy-symbol constituents on top (index_size_exceptions.csv)" if nx else "")))
        bad_days = int((~ok & in_scope).sum())
        if bad_days and np.any(in_scope):
            cov.append((k, days[in_scope][0], days[-1], "PARTIAL", f"{bad_days} of {int(in_scope.sum())} trading days fail parent verification or size/trading check; "
                                                                   f"gaps inherit from parent index coverage"))
        ivs.append(iv_comp)
        masks_by_index[k] = comp_masks
        v_days_by_index[k] = ok


def apply_floor(ok: np.ndarray, days: pd.DatetimeIndex, floor) -> tuple[np.ndarray, np.ndarray]:
    """Return (ok with days before the floor set False, in_scope mask). No floor: everything is in scope."""
    if floor is None:
        return ok, np.ones(len(days), dtype=bool)
    in_scope = np.asarray(days >= pd.Timestamp(floor))
    return ok & in_scope, in_scope


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


def build_anchored(ev_resolved: pd.DataFrame, seg: pd.DataFrame, t: pd.DataFrame, root: Path, contradictions_out: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    from . import series
    t = t[t["series"].isin(series.EQUITY_SERIES | {"RR", "IV"})]
    days = pd.DatetimeIndex(sorted(t["date"].unique()))
    pos = {d: i for i, d in enumerate(days)}
    traded = {sid: np.array(sorted(pos[d] for d in g["date"].unique())) for sid, g in t.groupby("sec_id")}
    # curated: listed members with no trade for longer than the window; those days count as present
    quiet_p = paths.CURATED / "index_no_trade.csv"
    if quiet_p.exists():
        for r in pd.read_csv(quiet_p, parse_dates=["from_date", "to_date"]).itertuples():
            sid = _sid(seg, r.symbol, r.from_date)
            if sid is not None:
                extra_pos = np.flatnonzero((days >= r.from_date) & (days <= r.to_date))
                traded[sid] = np.union1d(traded.get(sid, np.array([], dtype=int)), extra_pos).astype(int)
    cur = pd.read_csv(paths.CURATED / "index_events_press.csv", parse_dates=["date"]) if (paths.CURATED / "index_events_press.csv").exists() else pd.DataFrame()
    exc_p = paths.CURATED / "index_size_exceptions.csv"
    exc = pd.read_csv(exc_p) if exc_p.exists() else pd.DataFrame(columns=["index_key", "from_date", "to_date", "reason", "source"])
    ivs, cov, bad_all = [], [], []
    last_sym = seg.sort_values("end").drop_duplicates("sec_id", keep="last").set_index("sec_id")["symbol"].to_dict() if len(seg) else {}
    for k, (n, anchor_file) in ANCHORED.items():
        w = ev_resolved[(ev_resolved.index_key == k) & (ev_resolved.resolution == "OK")][["date", "sec_id", "action"]].drop_duplicates(["date", "sec_id", "action"])
        c = cur[cur.index_key == k].copy() if len(cur) else pd.DataFrame(columns=["date", "symbol", "action"])
        c["sec_id"] = [_sid(seg, s, d - pd.Timedelta(days=3) if a == "OUT" else d + pd.Timedelta(days=3))
                       for s, d, a in zip(c.symbol, c.date, c.action)]
        unmapped_c = c[c["sec_id"].isna()]
        if len(unmapped_c):
            bad_rows = ", ".join(f"{r.date.strftime('%Y-%m-%d')}:{r.symbol}:{r.action}" for r in unmapped_c.itertuples())
            raise ValueError(f"Unmapped press events for {k}: {bad_rows}")
        c = c[["date", "sec_id", "action"]].drop_duplicates(["date", "sec_id", "action"])
        frames_to_cat = [f for f in (w, c) if len(f)]
        events = pd.concat(frames_to_cat, ignore_index=True).drop_duplicates(["date", "sec_id", "action"]) if frames_to_cat else pd.DataFrame(columns=["date", "sec_id", "action"])
        anchor_syms = pd.read_csv(root / anchor_file).Symbol.tolist()
        anchor_date = pd.Timestamp(Path(anchor_file).parent.name)
        real_syms = [s for s in anchor_syms if not str(s).startswith("DUMMY")]
        asid_map = {s: _sid(seg, s, days[-1] - pd.Timedelta(days=2)) for s in real_syms}
        unmapped_a = [s for s, sid in asid_map.items() if sid is None]
        if unmapped_a:
            raise ValueError(f"Unmapped anchor symbols for {k}: {unmapped_a}")
        asids = set(asid_map.values())
        iv = anchor_intervals(asids, anchor_date, events)
        iv.insert(0, "index_key", k)
        sz = size_on(iv, days).values
        dc_p = paths.CURATED / "index_dual_class.csv"
        dcls = pd.read_csv(dc_p) if dc_p.exists() else None
        dual = dual_class_securities(days, dcls, k, iv, seg)
        # documented dummy-symbol constituents or official size expansions:
        extra = extra_members(days, exc, k)
        exc_days = extra > 0
        has_expansion = bool(len(exc) and exc[exc.index_key == k]["reason"].fillna("").str.contains("expanded|constituents between", case=False).any())
        ok = (sz == n + dual + extra) if has_expansion else (sz == n + dual)
        # an event that cannot be undone means a change is missing: nothing from its date on can be verified
        floor = FLOORS.get(k)
        bad = contradictions(asids - {None}, anchor_date, events)
        if floor is not None:      # an event before the floor cannot affect any day on or after it
            bad = bad[bad.date >= pd.Timestamp(floor)]
        if len(bad):
            ok[days >= bad.date.min()] = False
            b_df = bad.copy()
            b_df.insert(0, "index_key", k)
            b_df["last_symbol"] = b_df["sec_id"].map(last_sym).fillna("")
            bad_all.append(b_df[["index_key", "date", "sec_id", "last_symbol", "action"]])
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
        ok, in_scope = apply_floor(ok, days, floor)
        good = _ranges(days, ok)
        for a, b in good:
            nx = int((extra[(days >= a) & (days <= b)] > 0).sum())
            nd = int((dual[(days >= a) & (days <= b)] > 0).sum())
            cov.append((k, a, b, "VERIFIED", f"exactly {n} members on every trading day and every member traded within +-{TRADE_WINDOW} sessions"
                        + (f"; {nd} of these days held {n + 1} securities of {n} companies (a DVR, index_dual_class.csv)" if nd else "")
                        + (f"; {nx} of these days also had documented zero-price dummy-symbol constituents on top (index_size_exceptions.csv)" if nx else "")))
        bad_days = int((~ok & in_scope).sum())
        if bad_days:          # a PARTIAL row only when some day actually fails; a fully verified index has none
            cov.append((k, days[in_scope][0], days[-1], "PARTIAL", f"{bad_days} of {int(in_scope.sum())} trading days fail the size/trading check; "
                                                     f"gaps come from names or tickers not yet linked (see unresolved.csv)"
                                                     + (f"; {len(bad)} event(s) contradict the anchor (earliest {bad.date.min().date()}): a change is missing from the sources, so nothing from that date is verified" if len(bad) else "")))
        ivs.append(iv)
    if COMPOSITE_ANCHORS:
        build_composites(ivs, cov, days, traded, seg, exc, root)
    if contradictions_out is not None:
        contradictions_out.parent.mkdir(parents=True, exist_ok=True)
        cdf = pd.concat(bad_all, ignore_index=True) if bad_all else pd.DataFrame(columns=["index_key", "date", "sec_id", "last_symbol", "action"])
        cdf.to_csv(contradictions_out, index=False)
    return (pd.concat(ivs, ignore_index=True) if ivs else pd.DataFrame(columns=["index_key", "sec_id", "from_date", "to_date"]),
            pd.DataFrame(cov, columns=["index_key", "from_date", "to_date", "status", "reason"]))
