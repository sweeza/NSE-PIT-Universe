"""Corporate actions: raw NSE records -> typed events with exact quantities.

Every record component ends in exactly one class:
  SPLIT / BONUS / CONSOLIDATION / RIGHTS   share-structure events with parsed quantities
  DIVIDEND                                 cash dividend with a parsed amount
  SCHEME                                   demerger/merger/buyback/capital reduction: recorded,
                                           NOT quantified (needs a curated entry)
  NOEFFECT                                 matches an explicit no-price-effect pattern (AGM, etc.)
  UNPARSED                                 looks price-affecting but the text gave no exact quantity
  UNKNOWN                                  matches nothing known
UNPARSED / UNKNOWN / SCHEME are reported, never estimated. verify.py later checks each against
the price discontinuity NSE itself publishes (bhavcopy PREVCLOSE) before it may be waived.

share_factor S for share-structure events = (shares after) / (shares before):
  BONUS A:B (A new for every B held)      S = (A+B)/B
  SPLIT face value X -> Y                 S = X/Y
  CONSOLIDATION face value X -> Y (X<Y)   S = X/Y  (< 1)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from . import paths

_NUM = r"(\d+(?:\.\d+)?)"
_NOEFFECT = re.compile(
    r"^\s*(?:-|nil)?\s*$|annual general|\bagm\b|\begm\b|extra.?ordinary|book closure|annual clos|"
    r"\bpostal\b|ballot|elct?n|election|\binterest\b|redemption|maturity|repay|\bcall\b|"
    r"partial paid|conversion|\bncd\b|debenture|e-?\s?voting|general corporate|^\s*accounts?\s*$|"
    r"an?n?u?a?l (?:gen|general)|genee?rl meeting", re.I)
_SCHEME = re.compile(r"demerger|de-merger|arrangement|amalgam|merger|\bspin|reduction|buy ?-?back|"
                     r"reorgani[sz]ation", re.I)
_DIV = re.compile(r"\bdi?v(?:idend)?\w*|\bintdiv\b|\bdistribution\b|dividnd|dvdnd", re.I)
# "Bonus Debentures 6:1", "Bonus Ncrps 4:1", "Bonus Preference Shares 21:1": a bonus of another instrument, not of
# equity shares; it does not split the share count, so it must never get a share factor
_BONUS_OTHER = re.compile(r"\b(?:deb\w*|ncrps?|ncprs?|nc?cps?|cprs?|rps|prefer\w*|pref|ncd|ncds)(?=\W|\d|$)", re.I)
_INSTR = re.compile(r"\b(?:ncd|ccps?|pcd|fcds?|bond|warrants?|debenture)", re.I)


def classify(subject: str, face_value: float | None) -> list[dict]:
    """Return the component events found in one subject string."""
    s = (subject or "").strip()
    low = s.lower().replace("\u2013", "-")
    low = re.sub(r"\b(?:rights?|rghts?|rhgts?|rhts?|rhs|rgts?|rht|rght|rigths?)(?=[\s:/@.\-0-9]|$)", "rights", low)
    low = re.sub(r"\bfv\s*spl(?:t|it)?\b|\bsplt\b", "split", low)
    low = re.sub(r"\bfrm\b", "from", low)
    # "Rs10tors5", "Rs10to2", "Rs10to 4": the word "to" glued to the figures
    low = re.sub(r"(?<=\d)to(?=\s*(?:rs|re)?\.?\s*\d)", " to ", low)
    # "Fv Rs10 To Rs5", "Fv Sp Rs10 To 4": a face-value change written without the word split
    low = re.sub(r"\bfv\s*(?:sp\b)?\s*(?=(?:rs|re)\.?\s*\d+(?:\.\d+)?\s*/?-?\s*to\b)", "split ", low)
    # "Spl-Rs10 To Rs2", "Spl-Rs 5/ To 2/", "Spl Rs10-Rs2": a face-value split, not a special dividend
    low = re.sub(r"\bspl\b[\s.-]*(?=(?:rs|re)\.?\s*\d+(?:\.\d+)?\s*(?:/?-?\s*to\b|-\s*(?:rs|re)\.?\s*\d))",
                 "split ", low)
    comps: list[dict] = []
    if re.search(r"\bnil\b", low) and not re.search(r"bonus|split|rights", low):
        return [{"kind": "NOEFFECT", "detail": "nil"}]

    # bonus  "Bonus 1:1", "Bon 1:1/Fv Spl ..."
    mb = re.search(r"\bbon(?:us)?\b[^0-9:]{0,28}?" + _NUM + r"\s*:\s*" + _NUM, low) or \
        re.search(r"\bbon(?:us)?" + _NUM + r"\s*:\s*" + _NUM, low)
    if mb:
        a, b = float(mb.group(1)), float(mb.group(2))
        if _BONUS_OTHER.search(mb.group(0)):
            comps.append({"kind": "SCHEME", "detail": "bonus of a non-equity instrument: " + s[:60]})
        elif a > 0 and b > 0:
            comps.append({"kind": "BONUS", "share_factor": (a + b) / b, "detail": f"{mb.group(1)}:{mb.group(2)}"})
        else:
            comps.append({"kind": "UNPARSED", "detail": "bonus ratio"})

    # split / sub-division / consolidation: first two rupee numbers after the keyword
    ms = re.search(r"(split|sub-?\s?division|consolidation)", low)
    if ms:
        tail = low[ms.end():]
        nums = re.findall(_NUM, tail)
        if len(nums) < 2:
            nums = re.findall(_NUM, low[:ms.start()] + " " + tail)
        kw = ms.group(1)
        is_cons = kw.startswith("consol")
        if "capital reduction" in low and is_cons:
            comps.append({"kind": "SCHEME", "detail": "capital reduction + consolidation"})
        elif len(nums) >= 2 and float(nums[0]) > 0 and float(nums[1]) > 0:
            x, y = float(nums[0]), float(nums[1])
            if (not is_cons and x > y) or (is_cons and x < y):
                comps.append({"kind": "CONSOLIDATION" if is_cons else "SPLIT",
                              "share_factor": x / y, "detail": f"{nums[0]}->{nums[1]}"})
            else:
                comps.append({"kind": "UNPARSED", "detail": f"{kw} direction {nums[:2]}"})
        else:
            comps.append({"kind": "UNPARSED", "detail": f"{kw} quantities"})

    # rights  "Rights 1:5 @ Premium Rs 120", "Rights/2:5/Prem Of Rs 30", "Rights 4:7 At Par"
    if re.search(r"\brights\b", low):
        mr = re.search(r"\brights\b[^0-9]{0,14}" + _NUM + r"\s*:\s*" + _NUM, low)
        if mr and not _INSTR.search(low[mr.start():mr.end() + 25]):
            a, b = float(mr.group(1)), float(mr.group(2))
            rest = low[mr.end():]
            mp = re.search(r"prem\w*\.?\s*(?:of\s*)?(?:rs|re)?\.?\s*" + _NUM, rest)
            mi = re.search(r"(?:@|\bat\b)\s*(?:rs|re)\.?\s*" + _NUM, rest)
            issue = None
            ambiguous = re.search(r"prem\w*\s*@", rest) is not None   # "Prem@Rs.6": premium or issue price?
            if ambiguous:
                issue = None
            elif mp and face_value:
                issue = face_value + float(mp.group(1))
            elif re.search(r"at par", rest) and face_value:
                issue = face_value
            elif mi:
                issue = float(mi.group(1))
            if a > 0 and b > 0 and issue:
                comps.append({"kind": "RIGHTS", "rights_new": a, "rights_held": b,
                              "issue_price": issue, "detail": f"{mr.group(1)}:{mr.group(2)} issue {issue:g}"})
            else:
                comps.append({"kind": "UNPARSED", "detail": "rights issue price"})
        else:
            comps.append({"kind": "UNPARSED", "detail": "rights ratio/instrument"})

    if _SCHEME.search(low) and not any(c["kind"] in ("SCHEME", "SPLIT", "BONUS", "CONSOLIDATION") for c in comps):
        comps.append({"kind": "SCHEME", "detail": s[:60]})

    # dividends. Rupee amounts win over percentages (a subject often gives both for one
    # payment). Several labelled parts (final + special) are summed; "inclusive of" keeps the first.
    # A dividend written next to a face-value change ("Fv Spl-Rs10to2/Div-Rs2.50"): cut the keyword and its two
    # figures out first, so the face values are not read as dividend rupees. Only when both figures follow
    # the keyword; otherwise the split text stays and the dividend is not read (as before).
    dlow = low
    if ms and re.search(ms.group(1) + r"[^\d]*" + _NUM + r"[^\d]*" + _NUM, low[ms.start():]):
        dlow = low[:ms.start()] + " " + re.sub(ms.group(1) + r"[^\d]*" + _NUM + r"[^\d]*" + _NUM, " ", low[ms.start():], count=1)
    if _DIV.search(dlow) and not _SCHEME.search(low) and (not ms or dlow != low):
        low = dlow
        body = re.sub(r"\(\s*pur[^)]*\)", "", low)
        # a rights issue in the same subject carries its own rupee figures (premium, issue price):
        # they are not dividend amounts. Cut from the rights keyword to the next "/" (or the end).
        body = re.sub(r"\brights(?![a-z])[^/]*", " ", body)
        body = re.sub(r"\bprm\b[^/]*", " ", body)
        # "Rs. 1.50/- Per Equity Share Of Rs. 10/- Each": the second figure is the face value
        body = re.sub(r"\bof\s*(?:rs|re)\b\.?\s*\d+(?:\.\d+)?\s*/?-?\s*each", " ", body)
        rs = re.findall(r"\b(?:rs|re)(?![a-z])\.?\s*:?\s*-?\s*" + _NUM, body)   # "Rs.5", "Rs -3.60", "Rs:- 5.50"
        if not rs:
            rs = re.findall(r"\bdi?v(?:idend)?\w*[\s.@-]*" + _NUM + r"(?![\d.]*\s*%)(?![\d.]*\s*:)", body)
        # "Rs.0125": a figure of 3+ digits with a leading zero and no point is a typing error of unknown size (0.125 or
        # 1.25); it is reported, not read as 125
        if any(re.fullmatch(r"0\d{2,}", x) for x in rs):
            return comps + [{"kind": "UNPARSED", "detail": "dividend amount ambiguous: " + s[:60]}]
        pct = re.findall(_NUM + r"\s*%", body)
        if low.startswith("distribution") or " distribution" in low[:20]:
            # trust/REIT distribution. A headline total ("Distribution - Rs 2 Per Unit Consisting Of ...")
            # is the whole payout; with only listed components (interest, return of capital, ...) the
            # payout is their sum, since every part leaves the unit price.
            mh = re.search(r"distri\w*\s*-?\s*(?:(?:rs|re)\b\.?\s*)?" + _NUM +
                           r"\s*(?:/-)?\s*(?:per\s+unit\s*)?(?:consist|compris)", body)
            if mh:
                comps.append({"kind": "DIVIDEND", "amount": float(mh.group(1)), "detail": "distribution total rs " + mh.group(1)})
            elif rs:
                comps.append({"kind": "DIVIDEND", "amount": sum(float(x) for x in rs),
                              "detail": "distribution parts rs " + "+".join(rs)})
            else:
                comps.append({"kind": "UNPARSED", "detail": "distribution amount"})
        elif rs:
            vals = [float(x) for x in rs]
            amt = vals[0] if re.search(r"inclusive|including", body) else sum(vals)
            comps.append({"kind": "DIVIDEND", "amount": amt, "detail": "rs " + "+".join(rs)})
        elif pct and ms:
            pass   # a percentage next to a face-value change: of the old or the new face value? Not read (as before).
        elif pct and face_value:
            amt = sum(float(x) for x in pct) * face_value / 100.0
            comps.append({"kind": "DIVIDEND", "amount": amt, "detail": f"{'+'.join(pct)}% of fv {face_value:g}"})
        else:
            comps.append({"kind": "UNPARSED", "detail": "dividend amount missing: " + s[:60]})

    if not comps:
        comps.append({"kind": "NOEFFECT" if _NOEFFECT.search(low) else "UNKNOWN", "detail": s[:80]})
    return comps


def _date(x):
    if x in (None, "", "-"):
        return pd.NaT
    return pd.to_datetime(x, format="%d-%b-%Y", errors="coerce")


def load_raw(path: Path | None = None) -> list[dict]:
    p = path or (paths.HELD / "raw_corporate_actions_1995_2026.json")
    return json.loads(p.read_text(encoding="utf-8"))


def build_events(records: list[dict] | None = None) -> pd.DataFrame:
    """One row per component event. Deterministic ordering."""
    records = records if records is not None else load_raw()
    rows = []
    for i, r in enumerate(records):
        fv = None
        try:
            fv = float(r.get("faceVal")) if r.get("faceVal") not in (None, "", "-") else None
        except ValueError:
            pass
        for j, c in enumerate(classify(r.get("subject", ""), fv)):
            rows.append({
                "rec_id": i, "comp": j, "symbol": (r.get("symbol") or "").strip(),
                "isin": (r.get("isin") or "").strip() or None, "series": r.get("series"),
                "ex_date": _date(r.get("exDate")), "record_date": _date(r.get("recDate")),
                "face_value": fv, "subject": (r.get("subject") or "").strip(),
                "knowledge_date": _date(r.get("caBroadcastDate")), **c})
    df = pd.DataFrame(rows)
    for col in ("share_factor", "amount", "rights_new", "rights_held", "issue_price"):
        if col not in df:
            df[col] = float("nan")
    return df.sort_values(["ex_date", "symbol", "rec_id", "comp"], kind="mergesort").reset_index(drop=True)
