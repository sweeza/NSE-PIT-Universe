"""Step 1 of PLAN_BACKFILL_2010.md: paid-up capital and face value from NSE result filings, 2008-2021.

One filing per security per half-year is enough for a semi-annual review. Responses are appended as served to
data/staging/share_filings/ (not yet part of data/raw or its manifest). Safe to stop and re-run: finished work is skipped.

    python tools/fetch_share_counts.py [--limit N] [--workers N] [--rate REQUESTS_PER_SECOND]

Workers share one request rate. All pause COOL_S after each WORK_S, and BACKOFF_S after a run of failures; if requests
still fail after that, the run stops. --recent fetches 2021-2026 (legacy and integrated filings) into
share_filings_recent/. securities.json in the output folder replaces the price tables (see --export).
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nifty_earnings import config as C  # noqa: E402
from nifty_earnings.http_client import NSEHttpClient  # noqa: E402

OUT = ROOT / "data" / "staging" / "share_filings"
FIRST, LAST = 2008, 2021
PRICE_YEARS = range(2009, 2022)
MAX_TRIES = 3        # filings tried per half-year before giving up on it
BACKOFF_AFTER = 5    # consecutive failed requests before a long pause; the same again afterwards stops the run
WORK_S, COOL_S, BACKOFF_S = 20 * 60, 2 * 60, 10 * 60


def securities() -> list[tuple[str, list[str]]]:
    """Every non-fund security traded in EQ/BE in 2009-2021, with its symbols, newest first."""
    saved = OUT / "securities.json"
    if saved.exists():
        return json.loads(saved.read_text(encoding="utf-8"))
    px = pd.concat([pd.read_parquet(ROOT / f"data/final/prices/prices_{y}.parquet", columns=["series", "sec_id", "isin"])
                    for y in PRICE_YEARS])
    px = px[px.series.isin(["EQ", "BE"]) & ~px["isin"].fillna("").str.startswith("INF")]
    seg = pd.read_parquet(ROOT / "data/final/_work/identity/segments.parquet")
    seg = seg[seg.sec_id.isin(set(px.sec_id))].sort_values("end", ascending=False)
    out = []
    for sid, g in seg.groupby("sec_id", sort=True):
        syms = list(g.symbol.unique())
        if not re.search(r"(BEES|ETF|IETF)$", syms[0]):
            out.append((sid, syms))
    return out


class Gate:
    """One request rate and one set of pauses for all workers. Sleeping under the lock pauses every worker."""

    def __init__(self, rate: float):
        self.gap, self.lock = 1.0 / rate, threading.Lock()
        self.next, self.started = 0.0, time.monotonic()
        self.failures, self.backed_off, self.stop = 0, False, False

    def wait(self) -> bool:
        with self.lock:
            if self.stop:
                return False
            if time.monotonic() - self.started >= WORK_S:
                print(f"cooldown {COOL_S}s", flush=True)
                time.sleep(COOL_S)
                self.started = time.monotonic()
            time.sleep(max(0.0, self.next - time.monotonic()))
            self.next = time.monotonic() + self.gap
            return True

    def ok(self):
        self.failures, self.backed_off = 0, False

    def failed(self):
        with self.lock:
            self.failures += 1
            if self.failures < BACKOFF_AFTER or self.stop:
                return
            if self.backed_off:
                self.stop = True
                print("STOP: requests still fail after a back-off", flush=True)
                return
            print(f"{self.failures} failures in a row, backing off {BACKOFF_S}s", flush=True)
            time.sleep(BACKOFF_S)
            self.failures, self.backed_off, self.started = 0, True, time.monotonic()


class Log:
    def __init__(self, path: Path):
        self.path = path
        self.rows = []
        self.lock = threading.Lock()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    self.rows.append(json.loads(line))
                except json.JSONDecodeError:      # a line cut short by an interrupted run
                    pass

    def add(self, row: dict):
        self.lock.acquire()
        self.rows.append(row)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        self.lock.release()


def pack(b: bytes) -> str:
    return base64.b64encode(gzip.compress(b)).decode()


def end_date(row: dict):
    try:
        return datetime.strptime(str(row.get("toDate")).strip()[:11], "%d-%b-%Y")
    except ValueError:
        return None


def request_url(row: dict) -> str | None:
    xbrl = str(row.get("xbrl") or "").strip()
    if xbrl.lower().endswith(".xml"):
        return xbrl
    seq, params = str(row.get("seqNumber") or "").strip(), str(row.get("params") or "").strip()
    if not (seq and params):
        return None
    ind = str(row.get("reInd") or ("A" if row.get("bank") == "B" else "N")).strip()
    return C.NSE_LEGACY_DETAIL_URL.format(params=quote(params, safe=""), seq_id=quote(seq, safe=""),
                                          industry=quote(str(row.get("industry") or "-").strip(), safe="-"),
                                          ind=quote(ind, safe=""), fmt="New")


def values(body: bytes) -> tuple[float | None, float | None]:
    """(paid-up capital as filed, face value). Units differ by source and are reconciled in step 2."""
    def num(x):
        try:
            return float(str(x).replace(",", "")) or None
        except ValueError:
            return None
    if body.lstrip()[:1] == b"<":
        t = body.decode("utf-8", errors="replace")
        def tag(name):
            m = re.search(rf"<[\w-]+:{name}\b[^>]*>\s*([\d.,Ee+-]+)\s*<", t)
            return num(m[1]) if m else None
        return tag("PaidUpValueOfEquityShareCapital"), tag("FaceValueOfEquityShareCapital")
    v = (json.loads(body) or {}).get("resultsData2") or {}
    return num(v.get("re_pdup")), num(v.get("re_face_val"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--rate", type=float, default=1.0)
    ap.add_argument("--recent", action="store_true")
    ap.add_argument("--export", action="store_true", help="write securities.json and exit")
    a = ap.parse_args()
    global OUT, FIRST, LAST, PRICE_YEARS
    if a.recent:
        OUT, FIRST, LAST, PRICE_YEARS = OUT.with_name("share_filings_recent"), 2021, 2026, range(2021, 2027)
    OUT.mkdir(parents=True, exist_ok=True)
    if a.export:
        (OUT / "securities.json").write_text(json.dumps(securities()), encoding="utf-8")
        return
    listings, filings, done = Log(OUT / "listings.jsonl"), Log(OUT / "filings.jsonl"), Log(OUT / "done.jsonl")
    finished = {r["sec_id"] for r in done.rows}
    listed = {r["symbol"]: r for r in listings.rows}
    fetched = {r["url"]: r for r in filings.rows}
    todo = [s for s in securities() if s[0] not in finished]
    print(f"{len(finished)} securities done, {len(todo)} to do", flush=True)
    gate, local = Gate(a.rate), threading.local()
    batch = todo[: a.limit]

    def get(url, api):
        if not gate.wait():
            return None
        if not hasattr(local, "http"):
            local.http = NSEHttpClient(delay_sec=0)
        try:
            b = local.http.get_bytes(url, is_nse_api=api)
            if api:
                json.loads(b)       # a block page is not JSON
            gate.ok()
            return b
        except Exception as e:
            print("  failed:", type(e).__name__, str(e)[:120], flush=True)
            if "404" in str(e) and not api:
                return b""               # the file does not exist: record it as empty, do not retry on every run
            gate.failed()
            return None

    def integrated(sym, sid):
        key = f"{sym}|Integrated"
        if key not in listed:
            found = []
            for page in range(1, 51):
                b = get(C.NSE_INTEGRATED_RESULTS_URL.format(symbol=quote(sym, safe=""), page=page), True)
                if b is None:
                    return [], 1
                d = json.loads(b)
                part = (d.get("data") or []) if isinstance(d, dict) else []
                new = [r for r in part if r not in found]
                found += new
                if not new or len(found) >= int(d.get("totalCount") or 0):
                    break
            row = {"symbol": key, "sec_id": sid, "utc": datetime.now(timezone.utc).isoformat(), "body": pack(json.dumps(found).encode())}
            listings.add(row)
            listed[key] = row
        d = json.loads(gzip.decompress(base64.b64decode(listed[key]["body"])))
        return [{"toDate": r.get("qe_Date"), "xbrl": r.get("xbrl"), "consolidated": r.get("consolidated"),
                 "filingDate": r.get("broadcast_Date") or r.get("creation_Date"), "_symbol": sym}
                for r in d if "financial" in str(r.get("type", "")).lower()], 0

    def one(item):
        n, (sid, syms) = item
        if gate.stop:
            return
        rows, errors = [], 0
        for sym in syms:
            for period in ("Quarterly", "Annual"):
                key = f"{sym}|{period}"
                if key not in listed:
                    b = get(C.NSE_LEGACY_RESULTS_URL.format(symbol=quote(sym, safe=""), period=period), True)
                    if b is None:
                        errors += 1
                        continue
                    row = {"symbol": key, "sec_id": sid, "utc": datetime.now(timezone.utc).isoformat(), "body": pack(b)}
                    listings.add(row)
                    listed[key] = row
                d = json.loads(gzip.decompress(base64.b64decode(listed[key]["body"])))
                rows += [dict(r, _symbol=sym) for r in d] if isinstance(d, list) else []

        if a.recent:
            more, e = integrated(syms[0], sid)
            rows, errors = rows + more, errors + e
        halves: dict[tuple[int, int], list] = {}
        for r in rows:
            e = end_date(r)
            if e and FIRST <= e.year <= LAST and request_url(r):
                halves.setdefault((e.year, (e.month - 1) // 6), []).append(r)
        got = 0
        for half, cand in sorted(halves.items()):
            # quarter-ends that close a half first, then standalone, then newest
            cand.sort(key=lambda r: (end_date(r).month not in (3, 9), str(r.get("consolidated", "")).startswith("Con"),
                                     -end_date(r).timestamp()))
            for r in cand[:MAX_TRIES]:
                url = request_url(r)
                if url not in fetched:
                    b = get(url, "/api/" in url)
                    if b is None:
                        errors += 1
                        continue
                    try:
                        paid, face = values(b)
                    except Exception:
                        paid, face = None, None
                    row = {"url": url, "sec_id": sid, "symbol": r["_symbol"], "period_end": end_date(r).date().isoformat(),
                                 "filed": r.get("filingDate") or r.get("broadCastDate"), "paid_up": paid, "face_value": face,
                                 "utc": datetime.now(timezone.utc).isoformat(), "body": pack(b)}
                    filings.add(row)
                    fetched[url] = row
                if fetched[url]["paid_up"] and fetched[url]["face_value"]:
                    got += 1
                    break
        if not errors:     # a security with a failed request is retried on the next run
            done.add({"sec_id": sid, "symbol": syms[0], "listed": len(rows), "halves": len(halves), "with_count": got})
        print(f"{n}/{len(batch)} {syms[0]} listed={len(rows)} halves={len(halves)} with_count={got} errors={errors}", flush=True)

    with ThreadPoolExecutor(a.workers) as pool:
        list(pool.map(one, enumerate(batch, 1)))
    if gate.stop:
        sys.exit(1)
    print("FINISHED", flush=True)


if __name__ == "__main__":
    main()
