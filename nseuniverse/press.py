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
