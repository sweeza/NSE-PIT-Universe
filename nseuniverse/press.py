"""Extract index inclusion/exclusion events for ONE index from press-release text.

Only sections whose heading is exactly that index (e.g. "a) Nifty 50", "1) NIFTY 50") are read;
the symbols come from the table under 'excluded' / 'included'. The output is a candidate list
that is reviewed by hand before it is copied into data/curated/ (each curated row cites the
release file). PDF table layout is lossy, so nothing here is applied automatically."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pandas as pd

from . import indices

_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
     "November", "December"], 1)}
_STOP = {"SR", "NO", "NAME", "SYMBOL", "COMPANY", "LTD", "THE", "NIFTY", "NSE", "INDIA", "AND", "OF", "SEC", "S"}


def _eff_date(text: str, pos: int):
    pat = re.compile(r"effective\s+(?:from|on)\s+([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})")
    ms = list(pat.finditer(text))
    if not ms:
        return None
    before = [m for m in ms if m.start() <= pos]
    m = before[-1] if before else ms[0]
    return dt.date(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2)))


def _symbols(block: str) -> list[str]:
    out = []
    for tok in re.findall(r"[A-Z][A-Z0-9&-]{1,15}", block):
        if tok not in _STOP and not tok.isdigit():
            out.append(tok)
    return out


def index_events(path: Path, heading: str = "Nifty 50") -> list[dict]:
    t = path.read_text(errors="ignore")
    t = re.split(r"About (?:NSE Indices|India Index)", t, maxsplit=1, flags=re.I)[0]
    h = re.compile(r"^\s*(?:[A-Za-z]?\d*[\).]\s*)*" + re.escape(heading).replace(r"\ ", r"\s*") + r"\s*(?:index)?\s*:?\s*$",
                   re.I | re.M)
    res = []
    for m in h.finditer(t):
        rest = t[m.end():]
        nxt = re.search(r"^\s*(?:[A-Za-z]|\d+)\)\s+\S", rest, re.M)
        sec = rest[:nxt.start()] if nxt else rest[:1500]
        sec = re.split(r"\n\s*Note\b|The above replacement", sec, maxsplit=1)[0]
        mo = re.search(r"being excluded", sec, re.I)
        mi = re.search(r"being included", sec, re.I)
        if not (mo or mi):
            continue
        ex = sec[mo.end(): mi.start() if (mi and mi.start() > mo.end()) else None] if mo else ""
        inc = sec[mi.end():] if mi else ""
        d = _eff_date(t, m.start())
        res.append({"file": path.name, "effective": d, "excluded": _symbols(ex), "included": _symbols(inc)})
    return res


_FLAG_RE = re.compile(
    r"\b(revok(?:e|ed|ing)|withdrawn|corrigendum|cancell?ed|postponed|also\s+applicable\s+to)\b",
    re.I,
)


def extract_all_events(
    text_dir: Path,
    since_date: str = "2020-09-01",
    known_symbols: set[str] | None = None,
) -> pd.DataFrame:
    """Scan press-release .txt files and extract candidate (index_key, date, symbol, action, company, source, flag) rows.
    Purely read-only candidate extraction; never writes curated files."""
    cols = ["index_key", "date", "symbol", "action", "company", "source", "flag"]
    if not text_dir.exists():
        return pd.DataFrame(columns=cols)

    nmap = indices.name_map()
    since_dt = dt.date.fromisoformat(since_date)
    rows = []

    # Build canonical heading patterns from name_map keys
    # Prefer longer keys first to avoid partial prefix matches
    canon_keys = sorted(set(nmap.values()))
    heading_re = re.compile(
        r"^\s*(?:[A-Za-z]?\d*[\).]\s*)+(?P<name>[A-Za-z0-9 &/-]{3,60}?)\s*(?:index|indices)?\s*:?\s*$",
        re.I | re.M,
    )

    for p in sorted(text_dir.glob("*.txt")):
        t = p.read_text(encoding="utf-8", errors="ignore")
        t_body = re.split(r"About (?:NSE Indices|India Index)", t, maxsplit=1, flags=re.I)[0]
        file_flags = sorted({m.group(1).lower() for m in _FLAG_RE.finditer(t_body)})
        flag_str = "; ".join(file_flags)

        for m in heading_re.finditer(t_body):
            raw_name = m.group("name").strip()
            k = nmap.get(indices.key(raw_name))
            if not k or k not in canon_keys:
                continue
            rest = t_body[m.end():]
            nxt = re.search(r"^\s*(?:[A-Za-z]|\d+)\)\s+\S", rest, re.M)
            sec = rest[:nxt.start()] if nxt else rest[:2000]
            sec = re.split(r"\n\s*Note\b|The above replacement", sec, maxsplit=1)[0]
            mo = re.search(r"being excluded", sec, re.I)
            mi = re.search(r"being included", sec, re.I)
            if not (mo or mi):
                continue
            d = _eff_date(t_body, m.start())
            if d is None or d < since_dt:
                continue
            ex_blk = sec[mo.end(): mi.start() if (mi and mi.start() > mo.end()) else None] if mo else ""
            in_blk = sec[mi.end():] if mi else ""
            for action, blk in (("OUT", ex_blk), ("IN", in_blk)):
                for sym in _symbols(blk):
                    if known_symbols is not None and sym not in known_symbols:
                        continue
                    rows.append({
                        "index_key": k,
                        "date": d.isoformat(),
                        "symbol": sym,
                        "action": action,
                        "company": "",
                        "source": p.name,
                        "flag": flag_str,
                    })

    return pd.DataFrame(rows, columns=cols)
