"""Stage 4.1 audit: independent rebuild of adjustment factors for a seeded sample of 60 securities.

Own parser (does not import nseuniverse.actions), own placement and own factor product.
Only inputs shared with the project: the raw feed JSON, the built bhavcopy parquet (checked
cell-for-cell against the zips in Stage 2) and the identity tables (checked in Stage 3), plus the
project's adjustments.parquet, which is the thing under test.
Usage: python -I audit/stage4_factors.py [outdir]
"""
import json, re, sys, random
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "audit" / "out"
OUT.mkdir(parents=True, exist_ok=True)
SEED = 20261122
N = r"(\d+(?:\.\d+)?)"


def parse(subject, fv):
    """Return list of (kind, value dict). Strict, written separately from the project parser."""
    s = " ".join((subject or "").lower().replace("–", "-").split())
    out = []
    m = re.search(r"\bbon(?:us)?\b\D{0,12}" + N + r"\s*:\s*" + N, s)
    if m and re.search(r"ncrps?|ccps?|preference|debenture|ncd", s):
        out.append(("BONUS_NONEQUITY", {"txt": s[:60]}))   # bonus of a non-ordinary instrument
    elif m:
        a, b = float(m.group(1)), float(m.group(2))
        out.append(("BONUS",{"S": (a + b) / b, "txt": f"{a:g}:{b:g}"}))
    if re.search(r"split|sub-?\s?division|consolidation", s) and "capital reduction" not in s:
        m = re.search(r"(?:from|split|spl|division)\D{0,6}?" + N + r"\D{0,25}?to\s*(?:rs|re)?\.?\s*" + N, s)
        if m:
            x, y = float(m.group(1)), float(m.group(2))
            out.append(("SPLIT" if x > y else "CONSOL", {"S": x / y, "txt": f"{x:g}->{y:g}"}))
        else:
            out.append(("SPLIT?", {"txt": s[:60]}))
    if re.search(r"\brig?h?ts?\b|\brghts?\b|\brhgts?\b", s):
        m = re.search(r"(?:rights?|rghts?|rhgts?|rhts?)\D{0,14}" + N + r"\s*:\s*" + N, s)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            rest = s[m.end():]
            mp = re.search(r"prem\w*\.?\s*(?:of\s*)?(?:rs|re)?\.?\s*" + N, rest)
            if re.search(r"prem\w*\s*@", rest):
                out.append(("RIGHTS?", {"txt": s[:70]}))
            elif mp and fv:
                out.append(("RIGHTS", {"a": a, "b": b, "issue": fv + float(mp.group(1)),
                                       "txt": f"{a:g}:{b:g}@{fv + float(mp.group(1)):g}"}))
            elif "at par" in rest and fv:
                out.append(("RIGHTS", {"a": a, "b": b, "issue": fv, "txt": f"{a:g}:{b:g}@par"}))
            else:
                out.append(("RIGHTS?", {"txt": s[:70]}))
        else:
            out.append(("RIGHTS?", {"txt": s[:70]}))
    if re.search(r"demerger|de-merger|arrangement|amalgam|merger|spin|buy ?-?back|reorgani", s):
        out.append(("SCHEME", {"txt": s[:60]}))
    if re.search(r"\bdi?v(?:idend)?|\bdistribution\b", s) and not out:
        body = re.sub(r"\(\s*pur[^)]*\)", "", s)
        rs = re.findall(r"\b(?:rs|re)\b\.?\s*" + N, body)
        pct = re.findall(N + r"\s*%", body)
        if rs:
            v = [float(x) for x in rs]
            out.append(("DIV", {"amt": v[0] if re.search(r"inclusive|including", body) else sum(v),
                                "txt": "rs " + "+".join(rs)}))
        elif pct and fv:
            out.append(("DIV", {"amt": sum(float(x) for x in pct) * fv / 100, "txt": "pct"}))
        else:
            out.append(("DIV?", {"txt": s[:60]}))
    return out


def load():
    raw = json.load(open(ROOT / "data/raw/held/raw_corporate_actions_1995_2026.json", encoding="utf-8"))
    rows = []
    for i, r in enumerate(raw):
        try:
            fv = float(r["faceVal"]) if r.get("faceVal") not in (None, "", "-") else None
        except ValueError:
            fv = None
        ex = pd.to_datetime(r.get("exDate"), format="%d-%b-%Y", errors="coerce")
        for k, v in parse(r.get("subject", ""), fv):
            rows.append(dict(rec=i, symbol=(r.get("symbol") or "").strip(), isin=(r.get("isin") or "").strip(),
                             ex=ex, fv=fv, kind=k, subject=r.get("subject", ""), **v))
    return pd.DataFrame(rows)


def load_prices(min_year=2006):
    px = pd.concat([pd.read_parquet(f) for f in sorted((ROOT / "data/build/bhavcopy").glob("bhavcopy_20*.parquet"))
                    if int(f.stem[-4:]) >= min_year], ignore_index=True)
    px = px[px.series.isin(["EQ", "BE", "BZ", "BL", "SM", "ST"])].copy()
    px["pri"] = (px.series != "EQ").astype(int)
    return px.sort_values(["sec_id", "date", "pri"]).drop_duplicates(["sec_id", "date"])


def main():
    ev = load()
    ev = ev[ev.ex >= "2006-12-01"]
    sec = pd.read_parquet(ROOT / "data/build/identity/securities.parquet")
    sh = pd.read_parquet(ROOT / "data/build/identity/symbol_history.parquet")
    adj = pd.read_parquet(ROOT / "data/build/actions/adjustments.parquet")
    gl = pd.read_parquet(ROOT / "data/build/actions/gate_log.parquet")
    px = load_prices()
    syms = sh.groupby("sec_id").symbol.apply(set).to_dict()
    isins = sh.groupby("sec_id").isins.apply(lambda s: {i for x in s for i in str(x).split(",") if i}).to_dict()
    ev_by_sym = {k: g for k, g in ev.groupby("symbol")}
    ev_by_isin = {k: g for k, g in ev.groupby("isin")}
    secs = sec[sec.is_equity & (sec.last_date >= "2007-01-01") & (sec.n_days >= 250)].copy()

    def events_for(r):
        parts = [ev_by_sym.get(s) for s in syms.get(r.sec_id, ())] + [ev_by_isin.get(i) for i in isins.get(r.sec_id, ())]
        parts = [p for p in parts if p is not None]
        if not parts:
            return ev.iloc[0:0]
        e = pd.concat(parts).drop_duplicates(["rec", "kind"])
        return e[(e.ex >= r.first_date - pd.Timedelta(days=14)) & (e.ex <= r.last_date + pd.Timedelta(days=14))]

    cache = {r.sec_id: events_for(r) for r in secs.itertuples()}
    rng = random.Random(SEED)
    chosen = []
    for k, n in {"BONUS": 15, "SPLIT": 15, "RIGHTS": 15, "SCHEME": 15}.items():
        pool = sorted(s for s, e in cache.items() if (e.kind == k).any() and s not in chosen)
        chosen += rng.sample(pool, n)
    print("sample", len(chosen))
    pxg = {s: g.sort_values("date").reset_index(drop=True) for s, g in px[px.sec_id.isin(chosen)].groupby("sec_id")}
    rows, fac_rows = [], []
    for sid in chosen:
        g = pxg.get(sid)
        if g is None:
            continue
        days = g.date.values
        e = cache[sid]
        mine = {}
        for r in e.itertuples():
            if r.kind in ("BONUS", "SPLIT", "CONSOL", "RIGHTS") and r.ex >= pd.Timestamp("2007-01-01"):
                k = days.searchsorted(r.ex.to_datetime64())
                if k >= len(days):
                    continue
                d = pd.Timestamp(days[k])
                if r.kind == "RIGHTS":
                    p = g.close.iloc[k - 1] if k > 0 else np.nan
                    if not p or np.isnan(p):
                        continue
                    terp = (p * r.b + r.issue * r.a) / (r.a + r.b)
                    mine.setdefault((d, "PRICE"), []).append((r.kind, terp / p, 1.0, r.txt, r.rec))
                else:
                    mine.setdefault((d, "SHARE"), []).append((r.kind, 1 / r.S, r.S, r.txt, r.rec))
        mine = {k: list({(x[0], x[3]): x for x in v}.values()) for k, v in mine.items()}
        theirs = adj[(adj.sec_id == sid) & adj.kind.isin(["SPLIT", "BONUS", "CONSOLIDATION", "RIGHTS"])
                     & (adj.eff_date >= "2007-01-01")]
        gl_s = gl[gl.sec_id == sid]
        keys = set(mine) | {(r.eff_date, "PRICE" if r.kind == "RIGHTS" else "SHARE") for r in theirs.itertuples()}
        for d, cls in sorted(keys):
            m = mine.get((d, cls), [])
            t = theirs[(theirs.eff_date == d) & (theirs.kind.eq("RIGHTS") == (cls == "PRICE"))]
            mf = float(np.prod([x[1] for x in m])) if m else 1.0
            tf = float(np.prod(t.price_mult)) if len(t) else 1.0
            i = days.searchsorted(d.to_datetime64())
            obs = np.nan
            if 0 <= i < len(g) and g.prev_close.iloc[i] and g.open.iloc[i]:
                obs = g.prev_close.iloc[i] / g.open.iloc[i]
            if not m:
                note = "PROJECT_ONLY"
            elif t.empty:
                lg = gl_s[gl_s.eff_date == d]
                note = "MINE_ONLY:" + (",".join(lg.decision) if len(lg) else "no_gate_row")
            elif abs(mf / tf - 1) > 1e-6:
                note = "FACTOR_DIFF"
            else:
                note = "MATCH"
            rows.append(dict(sec_id=sid, date=d, cls=cls, mine=mf, project=tf, observed_ratio=obs,
                             mine_txt=";".join(x[3] for x in m), project_detail=";".join(t.detail), note=note,
                             subject=" | ".join(e[e.rec.isin([x[4] for x in m])].subject.unique())[:90]))
        mult = pd.Series(1.0, index=g.date)
        for (d, cls), v in mine.items():
            mult[mult.index < d] *= float(np.prod([x[1] for x in v]))
        tm = pd.Series(1.0, index=g.date)
        for r in theirs.itertuples():
            tm[tm.index < r.eff_date] *= r.price_mult
        ratio = mult / tm
        fac_rows.append(dict(sec_id=sid, n_days=len(ratio), max_abs_dev=float((ratio - 1).abs().max()),
                             days_off_1e6=int(((ratio - 1).abs() > 1e-6).sum())))
    cmp_ = pd.DataFrame(rows)
    cmp_.to_csv(OUT / "stage4_factor_compare.csv", index=False)
    ser = pd.DataFrame(fac_rows)
    ser.to_csv(OUT / "stage4_series_compare.csv", index=False)
    print(cmp_.note.str.split(":").str[0].value_counts())
    print(ser.describe())
    print("securities with any day off:", int((ser.days_off_1e6 > 0).sum()))


if __name__ == "__main__":
    main()
