"""Security identity: link ticker segments into persistent securities (sec_id).

A "segment" is one symbol observed over a continuous period. Segments are joined into a
security only on evidence:
  1. symbolchange.csv (old -> new, effective date) when the old segment ends and the new one
     starts around that date;
  2. the same full ISIN on adjacent, non-overlapping segments of different symbols.
Never joined on ticker alone: a ticker that vanishes for more than GAP_DAYS or whose ISIN issuer
changes starts a new segment (recycled ticker = different security).
A join that would put two symbols on the same trading day into one security is rejected and
reported. Mergers and demergers are not joined; they end one sec_id and start another.

sec_ids are assigned by (first trading date, first symbol): a security first seen later always
sorts after earlier ones, so existing ids do not move when new days are appended.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import paths
from .series import EQUITY_SERIES

GAP_DAYS = 400
RENAME_WINDOW_BEFORE = 45   # old segment must end this close before the effective date
RENAME_WINDOW_AFTER = 45    # new segment must start this close after it


def _issuer(isin):
    """Issuer part of an equity/fund ISIN. Partly-paid and other special ISINs (IN9...) are not an
    issuer change and are ignored for continuity."""
    return isin[:8] if isinstance(isin, str) and len(isin) >= 8 and isin[:3] in ("INE", "INF") else None


def segments(t: pd.DataFrame) -> pd.DataFrame:
    """Per-symbol continuous segments from the canonical long table."""
    d = t[["date", "symbol", "isin", "series"]].copy()
    d["issuer"] = d["isin"].map(_issuer)
    d["is_eq"] = d["series"].isin(EQUITY_SERIES)
    g = d.groupby(["symbol", "date"], sort=True).agg(isin=("isin", "first"), issuer=("issuer", "first"),
                                                     is_eq=("is_eq", "max")).reset_index()
    out = []
    for sym, h in g.groupby("symbol", sort=True):
        h = h.sort_values("date")
        dates = h["date"].tolist()
        # newer pandas turns a missing string into NaN (truthy); normalise so "missing" is always None
        issuers = [x if isinstance(x, str) else None for x in h["issuer"].tolist()]
        isins = [x if isinstance(x, str) else None for x in h["isin"].tolist()]
        eqs = [bool(x) for x in h["is_eq"].tolist()]
        start = 0
        last_iss = issuers[0]
        for i in range(1, len(h) + 1):
            brk = i == len(h)
            if not brk:
                if (dates[i] - dates[i - 1]).days > GAP_DAYS:
                    brk = True
                elif issuers[i] and last_iss and issuers[i] != last_iss:
                    brk = True
                elif issuers[i]:
                    last_iss = issuers[i]
            if brk:
                sl = slice(start, i)
                isn = {x for x in isins[sl] if x}
                out.append({"symbol": sym, "start": dates[start], "end": dates[i - 1],
                            "n_days": i - start, "isins": tuple(sorted(isn)), "is_equity": any(eqs[sl])})
                start = i
                last_iss = issuers[i] if i < len(h) else None
    seg = pd.DataFrame(out).sort_values(["start", "symbol"], kind="mergesort").reset_index(drop=True)
    seg["seg_id"] = range(len(seg))
    return seg


def _load_symbolchange(path=None) -> pd.DataFrame:
    p = path or (paths.HELD / "symbolchange.csv")
    df = pd.read_csv(p, dtype=str, encoding="latin1", keep_default_na=False)
    df.columns = [c.strip().upper() for c in df.columns]
    df = df.rename(columns={"OLD SYMBOL": "old", "NEW SYMBOL": "new", "EFFECTIVE DATE": "eff"})
    df["old"] = df["old"].str.strip()
    df["new"] = df["new"].str.strip()
    df["eff"] = pd.to_datetime(df["eff"].str.strip(), format="%d-%b-%Y", errors="coerce")
    return df[(df["old"] != df["new"]) & df["eff"].notna()].drop_duplicates(["old", "new", "eff"]).reset_index(drop=True)


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def link(seg: pd.DataFrame, t: pd.DataFrame, symbolchange: pd.DataFrame | None = None):
    """Return (seg with sec_key, links table)."""
    sc = symbolchange if symbolchange is not None else _load_symbolchange()
    by_sym = {s: g for s, g in seg.groupby("symbol")}
    sym_dates = {s: np.sort(g["date"].unique()) for s, g in t[["symbol", "date"]].groupby("symbol")}
    dates_by_seg: dict[int, set] = {}

    def dset(sid):
        if sid not in dates_by_seg:
            r = seg.loc[sid]
            a = sym_dates[r.symbol]
            lo = a.searchsorted(np.datetime64(r.start), side="left")
            hi = a.searchsorted(np.datetime64(r.end), side="right")
            dates_by_seg[sid] = set(a[lo:hi].tolist())
        return dates_by_seg[sid]

    uf = _UF(len(seg))
    members: dict[int, set] = {i: {i} for i in range(len(seg))}
    log = []

    def try_join(a, b, source, note):
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb:
            return
        da = set().union(*[dset(i) for i in members[ra]])
        db = set().union(*[dset(i) for i in members[rb]])
        if da & db:
            log.append({"seg_a": a, "seg_b": b, "source": source, "status": "REJECTED_OVERLAP", "note": note})
            return
        uf.union(ra, rb)
        keep = uf.find(ra)
        other = rb if keep == ra else ra
        members[keep] = members[ra] | members[rb]
        members.pop(other, None)
        log.append({"seg_a": a, "seg_b": b, "source": source, "status": "JOINED", "note": note})

    # 1. symbol-change records
    for r in sc.sort_values(["eff", "old", "new"]).itertuples():
        if r.old not in by_sym or r.new not in by_sym:
            continue
        olds = by_sym[r.old]
        news = by_sym[r.new]
        olds = olds[(olds["end"] >= r.eff - pd.Timedelta(days=RENAME_WINDOW_BEFORE)) &
                    (olds["end"] <= r.eff + pd.Timedelta(days=10))]
        news = news[(news["start"] >= r.eff - pd.Timedelta(days=10)) &
                    (news["start"] <= r.eff + pd.Timedelta(days=RENAME_WINDOW_AFTER))]
        if len(olds) == 1 and len(news) == 1:
            try_join(int(olds.iloc[0].seg_id), int(news.iloc[0].seg_id), "symbolchange",
                     f"{r.old}->{r.new} {r.eff.date()}")
        elif len(olds) > 1 or len(news) > 1:
            log.append({"seg_a": -1, "seg_b": -1, "source": "symbolchange", "status": "AMBIGUOUS",
                        "note": f"{r.old}->{r.new} {r.eff.date()} olds={len(olds)} news={len(news)}"})

    # 2. same ISIN, different symbols, adjacent in time
    isin_idx: dict[str, list] = {}
    for r in seg.itertuples():
        if not r.is_equity:
            continue
        for i in r.isins:
            isin_idx.setdefault(i, []).append(r.seg_id)
    for isin, ids in sorted(isin_idx.items()):
        ids = sorted(set(ids), key=lambda i: seg.loc[i, "start"])
        for a, b in zip(ids, ids[1:]):
            ra, rb = seg.loc[a], seg.loc[b]
            if ra.symbol != rb.symbol and 0 <= (rb.start - ra.end).days <= 30:
                try_join(a, b, "isin", isin)

    seg = seg.copy()
    seg["root"] = [uf.find(i) for i in seg["seg_id"]]
    return seg, pd.DataFrame(log, columns=["seg_a", "seg_b", "source", "status", "note"])


def build(t: pd.DataFrame, symbolchange: pd.DataFrame | None = None):
    """Return (securities, symbol_history, links, seg_map)."""
    seg = segments(t)
    seg, links = link(seg, t, symbolchange)
    first = seg.groupby("root").agg(first_date=("start", "min"), last_date=("end", "max"),
                                    n_days=("n_days", "sum")).reset_index()
    fs = seg.sort_values("start").groupby("root").first()["symbol"].rename("first_symbol")
    ls = seg.sort_values("end").groupby("root").last()["symbol"].rename("last_symbol")
    sec = first.merge(fs, on="root").merge(ls, on="root")
    sec = sec.sort_values(["first_date", "first_symbol"], kind="mergesort").reset_index(drop=True)
    sec["sec_id"] = ["S%05d" % (i + 1) for i in range(len(sec))]
    isin_last = (seg.sort_values("end").groupby("root")["isins"]
                 .last().map(lambda x: x[-1] if x else None).rename("isin_last"))
    sec = sec.merge(isin_last, on="root")
    seg = seg.merge(sec[["root", "sec_id"]], on="root")
    sh = seg[["sec_id", "symbol", "start", "end", "isins"]].rename(columns={"start": "from_date", "end": "to_date"})
    sh["isins"] = sh["isins"].map(lambda x: ",".join(x))
    sh = sh.sort_values(["sec_id", "from_date"], kind="mergesort").reset_index(drop=True)
    sec = sec.drop(columns="root")[["sec_id", "first_symbol", "last_symbol", "first_date", "last_date", "n_days", "isin_last"]]
    return sec, sh, links, seg[["seg_id", "symbol", "start", "end", "sec_id"]]


def attach(t: pd.DataFrame, seg_map: pd.DataFrame) -> pd.DataFrame:
    """Add sec_id to the long table via (symbol, date in segment)."""
    out = []
    for sym, g in t.groupby("symbol", sort=False):
        s = seg_map[seg_map["symbol"] == sym].sort_values("start")
        idx = s["start"].searchsorted(g["date"].values, side="right") - 1
        sid = s["sec_id"].values[idx]
        ok = g["date"].values <= s["end"].values[idx]
        if not ok.all():
            raise ValueError(f"observations of {sym} fall outside every segment")
        out.append(pd.Series(sid, index=g.index))
    t = t.copy()
    t["sec_id"] = pd.concat(out).reindex(t.index)
    return t
