# Methodology and limitations

## Principles
1. **Only NSE publications are data.** Everything in `data/raw/` was downloaded from NSE/NSE Indices
   (hash-listed in `manifest.csv`), except the held inputs listed in section 8.
2. **Present or absent, never estimated.** No proxy memberships, no forward-filled prices, no
   inferred corporate actions. Missing facts stay missing and the API says so.
3. **Every claim has a check.** `nseuniverse verify` is the release gate; unit tests cover the code.

## 1. Bhavcopy
Two formats (legacy `cmDDMMMYYYYbhav.csv.zip` to 2024-07-05, UDiFF from then) are parsed by header,
not by date, into one table keyed `(date, symbol, series)`. Values are exactly as published: no
filling, clipping or reordering. Fields an era did not publish (ISIN before ~2011, trade counts
before ~2012, ...) are null. Two files use two-digit-year dates (`13-Jul-20`); that single alternative
is accepted. Where both formats exist (24 days) UDiFF is kept and the two are compared in `verify`.
The **equity universe** is the series EQ, BE, BZ, BL, BT, SM, ST, SZ, IL; debt, gold bonds, preference
shares, warrants and InvITs stay in the table but outside the equity universe.

## 2. Calendar
A trading day is a day NSE published a bhavcopy for. Cross-check: from 2012-02-21 the daily index file
must exist on exactly the same days (0 days have an index file without a bhavcopy; 13 have a
bhavcopy without an index file). 317 weekdays are non-sessions (holidays) and 30 weekend days are
special sessions.

## 3. Identity
`sec_id` identifies a security across ticker changes. Segments (one symbol, continuous) are joined
only on evidence: a dated `symbolchange.csv` record, or the same full ISIN on adjacent
non-overlapping equity segments. A ticker reappearing after 400+ days, or an ISIN issuer change
(`INE`/`INF` only; partly-paid `IN9...` ISINs are ignored), starts a new security. A join that would
put two symbols on one day into one security is rejected. Mergers and demergers are not joined.
Before ~2011 there are no ISINs, so identity rests on symbol history alone; renames missing from
`symbolchange.csv` stay unjoined (e.g. NIIT's 2004 ticker change, Nestlé's pre-2010 data).

## 4. Corporate actions and adjustment
Source: the held NSE feed (`raw_corporate_actions_1995_2026.json`, 43,816 records of free text).
Each record becomes components: SPLIT, BONUS, CONSOLIDATION, RIGHTS, DIVIDEND (parsed quantity),
SCHEME (demerger/merger/buyback, not quantified), NOEFFECT (AGM etc.), UNPARSED, UNKNOWN. For share
factor S (shares after / before): bonus A:B → (A+B)/B; split X→Y → X/Y. Price multiplier 1/S, volume
multiplier S; rights use the theoretical ex-rights price; dividends adjust only `total_return`.
Records carry today's ticker, so events are attached by symbol on the ex-date, else by any security
that carried the symbol or ISIN and traded within 14 days (accepted only if unique).

**Evidence gate.** NSE's `PREVCLOSE` is *not* adjusted, so the printed price move is the evidence. For each
security and ex-date the combined factor must match previous-close/open (or /close) within 25%.
Testable days that fail are searched ±5 sessions for a unique matching day (shift) or rejected.
Untestable (|S| < 1.5) actions are kept as parsed.
Result: 1,277 kept, 114 untestable, 15 rejected, 0 shifted.

## 5. Index values
Daily files (2012-02-21 →) and the niftyindices.com history API (from each index's base date; the path
is `/BackPage/...`, which differs from older documentation). Old names (`CNX …`, `S&P CNX Nifty`) map to
current names through `data/curated/index_renames.csv`, each row backed by the count of days where the
closes are equal. A daily file with two rows for one index/date (2023-10-04, one row wrong) is resolved
only by evidence: the row the history API confirms is kept, the other dropped and logged in
`build/indices/daily_duplicate_resolution.csv`.

## 6. Membership
NSE's workbook gives inclusions/exclusions with company names, but not launch lists. Therefore the set
on a date is rebuilt **backward from today's official constituent list**: undo each change. Names are
mapped to securities only by exact normalised match against NSE-published names or reviewed aliases
(`data/curated/name_aliases.csv`, with optional validity dates); near misses are suggestions, never applied.
A window is VERIFIED only if every trading day has exactly the official count of members and every
member traded within ±3 sessions. Press-release changes after the workbook (2020-09 →) are entered from
the PDFs into `data/curated/index_events_press.csv`, each citing its file.

## 7. Known limitations (all surfaced by `verify`)
- Adjusted prices before 2007-01-01 are unverified (feed gap).
- 15 share actions in the feed are contradicted by prices and are not applied (`build/actions_rejected_or_shifted.csv`).
- 108 demergers/schemes/rights-without-price leave documented breaks (`data/curated/waivers.csv`); 176 further
  overnight moves have no explanation in the feed (SME and ETF unit events, missing splits, crashes).
- Rights adjustments use the theoretical price and differ from the market move by >25% on 3 days.
- Index sources disagree on 1,061 index-days (338 by ≥0.1%), flagged per row; 925 index-days are missing
  inside index lives (non-publication days).
- Membership: only Nifty 50 (2017-09-29 →) is verified. Before that the replay has wrong members
  (e.g. Apollo Hospitals/Idea in, Kotak out in 2010) from name-resolution errors.
- 2004 prices for some large companies are absent from NSE's own files (e.g. L&T before 2004-06-23).

## 8. Held inputs (origin not re-verified)
`IndexInclExcl.xls` (NSE Indices workbook format, ends 2020-09-14), `raw_corporate_actions_1995_2026.json`,
`symbolchange.csv`, `EQUITY_L.csv`. They were obtained before this rebuild; the corporate-action feed
could not be re-fetched because nseindia.com refuses scripted requests. 521 manifest rows lost to a
concurrent-write bug were reconstructed from the files on disk and are marked as such.
