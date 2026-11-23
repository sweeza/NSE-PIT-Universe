"""The only module that touches the network.

Rules
- Raw bytes are written once and never overwritten.
- A response counts as a file only if it passes the source's content check
  (NSE answers some missing days with HTTP 200 + an HTML page).
- Every stored file is recorded in manifest.csv with its SHA-256.
- Days with no file are recorded in absent.csv; that list is evidence for the calendar.
- Resumable: existing files and recorded absences are skipped (absences from the last
  7 days are retried because the file may simply not be published yet).
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import os
import threading
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import paths

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
_lock = threading.Lock()
_MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _is_zip(b: bytes) -> bool:
    return b[:2] == b"PK" and zipfile.is_zipfile(io.BytesIO(b))


def _is_index_csv(b: bytes) -> bool:
    return b[:10].lower().startswith(b"index name")


@dataclass(frozen=True)
class Source:
    name: str
    first: dt.date
    last_fn: Callable[[], dt.date]
    url: Callable[[dt.date], str]
    dest: Callable[[dt.date], Path]
    valid: Callable[[bytes], bool]


def _legacy_url(d):
    return (f"https://nsearchives.nseindia.com/content/historical/EQUITIES/{d.year}/"
            f"{_MON[d.month-1]}/cm{d.day:02d}{_MON[d.month-1]}{d.year}bhav.csv.zip")


SOURCES = {
    "bhav_legacy": Source(
        "bhav_legacy", dt.date(2004, 1, 1), lambda: min(dt.date(2024, 7, 31), dt.date.today()),
        _legacy_url,
        lambda d: paths.BHAV_RAW / "legacy" / f"{d.year}" / f"cm{d.day:02d}{_MON[d.month-1]}{d.year}bhav.csv.zip",
        _is_zip),
    "bhav_udiff": Source(
        "bhav_udiff", dt.date(2024, 6, 1), dt.date.today,
        lambda d: f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip",
        lambda d: paths.BHAV_RAW / "udiff" / f"{d.year}" / f"BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip",
        _is_zip),
    "index_daily": Source(
        "index_daily", dt.date(2012, 1, 1), dt.date.today,
        lambda d: f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv",
        lambda d: paths.INDEX_DAILY_RAW / f"{d.year}" / f"ind_close_all_{d:%d%m%Y}.csv",
        _is_index_csv),
}


def _starts(prefix: bytes) -> Callable[[bytes], bool]:
    return lambda b: b[:len(prefix)] == prefix


def _market(kind: str, name: Callable[[dt.date], str]) -> Callable[[dt.date], Path]:
    return lambda d: paths.MARKET_RAW / kind / f"{d.year}" / name(d)


# Market-activity files. They are only fetched for days on which a bhavcopy exists (the session calendar), see
# session_days(). A missing file on such a day is recorded in absent.csv: for band changes it can simply mean "no
# change that day".
SOURCES.update({
    "delivery_mto": Source(
        "delivery_mto", dt.date(2004, 1, 1), dt.date.today,
        lambda d: f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{d:%d%m%Y}.DAT",
        _market("delivery", lambda d: f"MTO_{d:%d%m%Y}.DAT"), _starts(b"Security Wise Delivery Position")),
    "band_changes": Source(
        "band_changes", dt.date(2010, 1, 1), dt.date.today,
        lambda d: f"https://nsearchives.nseindia.com/content/equities/eq_band_changes_{d:%d%m%Y}.csv",
        _market("bandchanges", lambda d: f"eq_band_changes_{d:%d%m%Y}.csv"), _starts(b"Sr. No")),
    "sec_list": Source(
        "sec_list", dt.date(2020, 1, 1), dt.date.today,
        lambda d: f"https://nsearchives.nseindia.com/content/equities/sec_list_{d:%d%m%Y}.csv",
        _market("seclist", lambda d: f"sec_list_{d:%d%m%Y}.csv"), _starts(b"Symbol,Series")),
    "fo_secban": Source(
        "fo_secban", dt.date(2010, 1, 1), dt.date.today,
        lambda d: f"https://nsearchives.nseindia.com/archives/fo/sec_ban/fo_secban_{d:%d%m%Y}.csv",
        _market("fosecban", lambda d: f"fo_secban_{d:%d%m%Y}.csv"), _starts(b"Securities in Ban")),
    # Derivatives bhavcopy: F&O eligibility on a day = the stock has futures contracts that day.
    "fo_bhav_legacy": Source(
        "fo_bhav_legacy", dt.date(2004, 1, 1), lambda: min(dt.date(2024, 7, 5), dt.date.today()),
        lambda d: (f"https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{d.year}/"
                   f"{_MON[d.month-1]}/fo{d.day:02d}{_MON[d.month-1]}{d.year}bhav.csv.zip"),
        _market("fobhav/legacy", lambda d: f"fo{d.day:02d}{_MON[d.month-1]}{d.year}bhav.csv.zip"), _is_zip),
    "fo_bhav_udiff": Source(
        "fo_bhav_udiff", dt.date(2024, 7, 5), dt.date.today,
        lambda d: f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip",
        _market("fobhav/udiff", lambda d: f"BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"), _is_zip),
    # Monthly NSE Clearing (NCL) security category & 6-month rolling mean impact cost (Rs 1 lakh order).
    "impact_cost": Source(
        "impact_cost", dt.date(2019, 1, 1), dt.date.today,
        lambda d: f"https://nsearchives.nseindia.com/content/nsccl/C_CATG_{_MON[d.month-1]}{d.year}.T01",
        _market("impactcost", lambda d: f"C_CATG_{_MON[d.month-1]}{d.year}.T01"), _starts(b"10,")),
    # NSE daily MII security master (gzip CSV): IssdCptl = issued capital (shares), FreeFltCptl, ParVal, ListgDt.
    # First file on the archive host is 2024-02-05 (404 before).
    "mii_security": Source(
        "mii_security", dt.date(2024, 2, 5), dt.date.today,
        lambda d: f"https://nsearchives.nseindia.com/content/cm/NSE_CM_security_{d:%d%m%Y}.csv.gz",
        _market("mii", lambda d: f"NSE_CM_security_{d:%d%m%Y}.csv.gz"), _starts(b"\x1f\x8b")),
})
SESSION_ONLY = {"delivery_mto", "band_changes", "sec_list", "fo_secban", "fo_bhav_legacy", "fo_bhav_udiff", "mii_security"}
MONTHLY_ONLY = {"impact_cost"}


def session_days() -> set[dt.date]:
    """Days on which NSE published an equity bhavcopy (taken from the raw files held): weekdays and the few
    weekend special sessions. The calendar is evidence, not an assumption."""
    out = set()
    for f in list((paths.BHAV_RAW / "legacy").rglob("cm*bhav.csv.zip")) + list((paths.BHAV_RAW / "udiff").rglob("BhavCopy_NSE_CM_*.zip")):
        n = f.name
        try:
            if n.startswith("cm"):
                out.add(dt.datetime.strptime(n[2:11], "%d%b%Y").date())
            else:
                out.add(dt.datetime.strptime(n[len("BhavCopy_NSE_CM_0_0_0_"):][:8], "%Y%m%d").date())
        except ValueError:
            continue
    return out


_queue: dict[str, list] = {"manifest": [], "absent": []}


def _queue_row(kind: str, row: list) -> None:
    with _lock:
        _queue[kind].append(row)


def flush_queue() -> int:
    """Write queued manifest and absent rows with one append each (a Drive-synced CSV is slow to append to, one row
    at a time). Rows stay queued if the write fails; reconcile_manifest() repairs a lost manifest tail."""
    n = 0
    for kind, path, header in (("manifest", paths.MANIFEST, ["path", "url", "sha256", "bytes", "fetched_utc"]),
                               ("absent", paths.ABSENT, ["source", "date", "http", "note", "checked"])):
        with _lock:
            rows, _queue[kind] = _queue[kind], []
        if not rows:
            continue
        try:
            _append_many(path, header, rows)
            n += len(rows)
        except RuntimeError:
            with _lock:
                _queue[kind] = rows + _queue[kind]
    return n


def _read_absent() -> dict[tuple[str, str], dt.date]:
    out = {}
    if paths.ABSENT.exists():
        with open(paths.ABSENT, newline="") as f:
            for r in csv.DictReader(f):
                out[(r["source"], r["date"])] = dt.date.fromisoformat(r["checked"]) if r.get("checked") else dt.date.min
    return out


def _append(path: Path, header: list[str], row: list):
    _append_many(path, header, [row])


def _append_many(path: Path, header: list[str], rows: list[list]):
    """Append one CSV row. Safe across threads and across processes: a lock file serialises
    writers and the row is written with a single write call."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lockfile = path.with_suffix(path.suffix + ".lock")
    with _lock:
        for _ in range(4000):
            try:
                fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                try:                       # a lock older than two minutes belongs to a process that died
                    if time.time() - lockfile.stat().st_mtime > 120:
                        lockfile.unlink()
                except OSError:
                    pass
                time.sleep(0.05)
        else:
            raise RuntimeError(f"could not lock {path}")
        try:
            new = not path.exists()
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator=chr(13) + chr(10))
            if new:
                w.writerow(header)
            w.writerows(rows)
            with open(path, "a", newline="") as f:
                f.write(buf.getvalue())
        finally:
            os.close(fd)
            os.unlink(lockfile)


def _get(url: str, retries: int = 4) -> tuple[int, bytes]:
    """Return (http_status, body). 404 is a normal answer; other errors are retried."""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, b""
            last = e
        except Exception as e:  # network hiccup
            last = e
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"giving up on {url}: {last}")


def fetch_one(src: Source, d: dt.date, absent: dict) -> str:
    dest = src.dest(d)
    if dest.exists():
        return "have"
    key = (src.name, d.isoformat())
    retry_window = 35 if src.name in MONTHLY_ONLY else 7
    if key in absent and (dt.date.today() - d).days > retry_window:
        return "known-absent"
    url = src.url(d)
    status, body = _get(url)
    today = dt.date.today().isoformat()
    if status == 200 and src.valid(body):
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(body)
        tmp.replace(dest)
        row = [dest.relative_to(paths.ROOT).as_posix(), url, hashlib.sha256(body).hexdigest(),
               len(body), dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")]
        if src.name in SESSION_ONLY or src.name in MONTHLY_ONLY:
            _queue_row("manifest", row)
            return "fetched"
        try:
            _append(paths.MANIFEST, ["path", "url", "sha256", "bytes", "fetched_utc"], row)
        except RuntimeError:           # manifest busy: the file is kept, reconcile_manifest() lists it afterwards
            return "fetched-unlisted"
        return "fetched"
    note = "html-or-invalid-body" if status == 200 else "not-found"
    if src.name in SESSION_ONLY or src.name in MONTHLY_ONLY:
        _queue_row("absent", [src.name, d.isoformat(), status, note, today])
    else:
        _append(paths.ABSENT, ["source", "date", "http", "note", "checked"], [src.name, d.isoformat(), status, note, today])
    return "absent"


HIST_ENDPOINTS = {"price": "getHistoricaldatatabletoString",
                  "tri": "getTotalReturnIndexString",
                  "pepb": "getpepbHistoricaldataDBtoString"}
HIST_WINDOWS = [("01-Jan-1990", "31-Dec-2005"), ("01-Jan-2006", "31-Dec-2015"), ("01-Jan-2016", None)]


def index_names() -> list[str]:
    import json
    p = paths.INDEX_HIST_RAW / "IndexMapping.json"
    return sorted({r["Index_long_name"].strip() for r in json.loads(p.read_text(encoding="utf-8-sig"))})


def fetch_index_history(names: list[str] | None = None, workers: int = 3) -> dict[str, int]:
    """Fetch price / total-return / PE-PB history for every index in the site's own list.
    The response body is stored verbatim (an empty list is a valid answer: index did not
    exist in that window)."""
    import http.cookiejar
    import json
    import re

    names = names or index_names()
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    base = "https://www.niftyindices.com"
    opener.open(urllib.request.Request(base + "/reports/historical-data", headers={"User-Agent": UA}), timeout=60).read()
    today = dt.date.today().strftime("%d-%b-%Y")
    jobs = []
    for nm in names:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", nm).strip("_").lower()
        for ep, path in HIST_ENDPOINTS.items():
            for a, b in HIST_WINDOWS:
                is_open = b is None
                end_str = b or today
                dest = paths.INDEX_HIST_RAW / ep / f"{slug}__{a}__{end_str}.json"
                jobs.append((nm, slug, ep, path, a, end_str, is_open, dest))
    counts = {"have": 0, "fetched": 0}

    def one(job):
        nm, slug, ep, path, a, b, is_open, dest = job
        if dest.exists():
            return "have"
        if is_open and any((paths.INDEX_HIST_RAW / ep).glob(f"{slug}__{a}__*.json")):
            return "have"
        body = json.dumps({"cinfo": "{'name':'%s','startDate':'%s','endDate':'%s','indexName':'%s'}" % (nm.upper(), a, b, nm)}).encode()
        last = None
        for i in range(4):
            try:
                req = urllib.request.Request(f"{base}/BackPage/{path}", data=body, method="POST", headers={
                    "User-Agent": UA, "Content-Type": "application/json; charset=UTF-8",
                    "Referer": base + "/reports/historical-data", "Origin": base,
                    "X-Requested-With": "XMLHttpRequest"})
                with urllib.request.urlopen(req, timeout=120) if False else opener.open(req, timeout=120) as r:
                    raw = r.read()
                parsed = json.loads(raw)
                if not isinstance(parsed, list):
                    raise ValueError("non-list reply")
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(".part"); tmp.write_bytes(raw); tmp.replace(dest)
                _append(paths.MANIFEST, ["path", "url", "sha256", "bytes", "fetched_utc"],
                        [dest.relative_to(paths.ROOT).as_posix(), f"{base}/BackPage/{path} name={nm} {a}..{b}",
                         hashlib.sha256(raw).hexdigest(), len(raw),
                         dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")])
                time.sleep(0.4)
                return "fetched"
            except Exception as e:
                last = e
                time.sleep(2 * (i + 1))
        raise RuntimeError(f"index history failed {nm} {ep} {a}: {last}")

    with ThreadPoolExecutor(workers) as ex:
        for k, res in enumerate(ex.map(one, jobs), 1):
            counts[res] = counts.get(res, 0) + 1
            if k % 100 == 0:
                print(f"[index_history] {k}/{len(jobs)} {counts}", flush=True)
    print(f"[index_history] done {counts}", flush=True)
    return counts


def fetch_press_releases(workers: int = 4, since_year: int | None = None) -> dict[str, int]:
    """Download every PDF linked from the NSE Indices press-release page. The page itself is
    stored raw (dated) so the list of links is reproducible. Dead links (HTTP 200 + HTML) are
    recorded in absent.csv."""
    import re
    base = "https://www.niftyindices.com"
    status, body = _get(base + "/press-release")
    today = dt.date.today().strftime("%Y%m%d")
    page = paths.PRESS_RAW / f"press-release-page_{today}.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    if not page.exists():
        page.write_bytes(body)
        _append(paths.MANIFEST, ["path", "url", "sha256", "bytes", "fetched_utc"],
                [page.relative_to(paths.ROOT).as_posix(), base + "/press-release", hashlib.sha256(body).hexdigest(),
                 len(body), dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")])
    links = sorted(set(re.findall(r"/Press_Release/ind_prs\d{8}(?:_\d+)?\.pdf", body.decode("utf-8", "ignore"))))
    if since_year is not None:
        links = [
            lnk for lnk in links
            if (m := re.search(r"ind_prs\d{4}(\d{4})", lnk)) and int(m.group(1)) >= since_year
        ]
    absent = _read_absent()
    counts: dict[str, int] = {}

    def one(link):
        dest = paths.PRESS_RAW / "pdf" / link.rsplit("/", 1)[1]
        if dest.exists():
            return "have"
        key = ("press_release", link)
        if key in absent:
            return "known-absent"
        st, b = _get(base + link)
        time.sleep(0.2)
        if st == 200 and b[:4] == b"%PDF":
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".part"); tmp.write_bytes(b); tmp.replace(dest)
            _append(paths.MANIFEST, ["path", "url", "sha256", "bytes", "fetched_utc"],
                    [dest.relative_to(paths.ROOT).as_posix(), base + link, hashlib.sha256(b).hexdigest(), len(b),
                     dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")])
            return "fetched"
        _append(paths.ABSENT, ["source", "date", "http", "note", "checked"],
                ["press_release", link, st, "not-a-pdf", dt.date.today().isoformat()])
        return "absent"

    with ThreadPoolExecutor(workers) as ex:
        for k, res in enumerate(ex.map(one, links), 1):
            counts[res] = counts.get(res, 0) + 1
            if k % 200 == 0:
                print(f"[press] {k}/{len(links)} {counts}", flush=True)
    print(f"[press] done {counts}", flush=True)
    return counts


def fetch_constituent(slug: str, date_str: str | None = None) -> Path:
    """Download an index constituent CSV into data/raw/constituents/{YYYY-MM-DD}/ind_{slug}list.csv."""
    d_str = date_str or dt.date.today().isoformat()
    dest = paths.RAW / "constituents" / d_str / f"ind_{slug}list.csv"
    if dest.exists():
        return dest
    url = f"https://www.niftyindices.com/IndexConstituent/ind_{slug}list.csv"
    status, body = _get(url)
    if status != 200 or not body.lstrip().startswith(b"Company Name"):
        raise ValueError(f"invalid constituent CSV for {slug}: status={status}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(body)
    tmp.replace(dest)
    _append(
        paths.MANIFEST,
        ["path", "url", "sha256", "bytes", "fetched_utc"],
        [
            dest.relative_to(paths.ROOT).as_posix(),
            url,
            hashlib.sha256(body).hexdigest(),
            len(body),
            dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ],
    )
    return dest


def fetch_range(source: str, start: dt.date | None = None, end: dt.date | None = None,
                workers: int = 4, log_every: int = 250) -> dict[str, int]:
    src = SOURCES[source]
    start = max(start or src.first, src.first)
    end = min(end or src.last_fn(), src.last_fn())
    if source in MONTHLY_ONLY:
        days = []
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            days.append(dt.date(y, m, 1))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    else:
        days = [start + dt.timedelta(n) for n in range((end - start).days + 1)]
        if source in SESSION_ONLY:
            sd = session_days()
            days = [d for d in days if d in sd]
    absent = _read_absent()
    counts: dict[str, int] = {}
    done = 0

    def work(d):
        time.sleep(0.05)
        return fetch_one(src, d, absent)

    with ThreadPoolExecutor(workers) as ex:
        for res in ex.map(work, days):
            counts[res] = counts.get(res, 0) + 1
            done += 1
            if done % 100 == 0:
                flush_queue()
            if done % log_every == 0:
                print(f"[{source}] {done}/{len(days)} {counts}", flush=True)
    flush_queue()
    print(f"[{source}] done {counts}", flush=True)
    if source in SESSION_ONLY or source in MONTHLY_ONLY:
        n = reconcile_manifest()
        if n:
            print(f"[{source}] manifest rows added afterwards: {n}", flush=True)
    return counts


def dedupe_manifest() -> int:
    """Remove repeated manifest rows (same path); the first row stays, every other line is kept byte for byte.
    A queued row and a reconcile can both list a file. Returns the number of rows removed."""
    raw = paths.MANIFEST.read_bytes()
    lines = raw.decode("latin-1").splitlines(keepends=True)
    seen, keep, dropped = set(), [], 0
    for i, line in enumerate(lines):
        key = next(csv.reader([line]))[0] if i else None
        if key is not None and key in seen:
            dropped += 1
            continue
        if key is not None:
            seen.add(key)
        keep.append(line)
    if dropped:
        paths.MANIFEST.write_bytes("".join(keep).encode("latin-1"))
    return dropped


def reconcile_manifest(root: Path | None = None) -> int:
    """Add a manifest row for every file under data/raw/market that has none (a fetch whose manifest write timed out).
    The URL is rebuilt from the source's pattern and fetched_utc is the file's modification time. Returns the count."""
    root = root or paths.MARKET_RAW
    listed = set()
    if paths.MANIFEST.exists():
        with open(paths.MANIFEST, newline="", encoding="latin-1") as f:
            listed = {r["path"] for r in csv.DictReader(f)}
    by_dir = {"delivery": "delivery_mto", "bandchanges": "band_changes", "seclist": "sec_list", "fosecban": "fo_secban", "impactcost": "impact_cost", "mii": "mii_security"}
    n = 0
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix == ".part":
            continue
        rel = f.relative_to(paths.ROOT).as_posix()
        top = f.relative_to(root).parts[0]
        src = by_dir.get(top) or (("fo_bhav_legacy" if f.name.startswith("fo") else "fo_bhav_udiff") if top == "fobhav" else None)
        if rel in listed or src is None:
            continue
        d = None
        m = __import__("re").search(r"(\d{2})(\d{2})(\d{4})", f.name)
        if f.name.startswith("fo") and f.name.endswith("bhav.csv.zip"):
            d = dt.datetime.strptime(f.name[2:11], "%d%b%Y").date()
        elif f.name.startswith("C_CATG_") and f.name.endswith(".T01"):
            d = dt.datetime.strptime(f.name[7:14], "%b%Y").date()
        elif m and not f.name.startswith("BhavCopy"):
            d = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        elif f.name.startswith("BhavCopy"):
            d = dt.datetime.strptime(f.name.split("_")[6], "%Y%m%d").date()
        body = f.read_bytes()
        _append(paths.MANIFEST, ["path", "url", "sha256", "bytes", "fetched_utc"],
                [rel, SOURCES[src].url(d) if d else "", hashlib.sha256(body).hexdigest(), len(body),
                 dt.datetime.fromtimestamp(f.stat().st_mtime, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")])
        n += 1
    dedupe_manifest()
    return n


def fetch_deals_today() -> dict[str, str]:
    """NSE keeps only the latest day of bulk and block deals at a fixed URL; save today's copy under today's date.
    History before the first call has to come from the owner's download (NSE's report page)."""
    out = {}
    for kind in ("bulk", "block"):
        url = f"https://nsearchives.nseindia.com/content/equities/{kind}.csv"
        status, body = _get(url)
        if status != 200 or body[:4] == b"<!DO" or b"<html" in body[:200].lower():
            out[kind] = "absent"
            continue
        dest = paths.MARKET_RAW / "deals" / f"{kind}_{dt.date.today():%Y%m%d}.csv"
        if dest.exists():
            out[kind] = "have"
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        _append(paths.MANIFEST, ["path", "url", "sha256", "bytes", "fetched_utc"],
                [dest.relative_to(paths.ROOT).as_posix(), url, hashlib.sha256(body).hexdigest(), len(body),
                 dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")])
        out[kind] = "fetched"
    return out
