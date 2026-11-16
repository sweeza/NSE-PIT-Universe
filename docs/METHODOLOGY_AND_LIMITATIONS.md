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
the PDFs into `data/curated/index_events_press.csv`, each citing its file. Rolling back, an inclusion of a security that is
not a member at that point (or an exclusion of one that is) is a **contradiction**: a change is missing from the sources,
so no date from that event onward is VERIFIED.

**Scope.** The indices in scope are NSE's "Broad Market" (23) and "Sectoral" (34) categories, listed with their
source in `data/curated/index_universe.csv`. `api.coverage()` has a `category` column; 20 of the 57 appear in NSE's
workbook (the rest have no change history before ~2020 in the sources held). Other workbook indices (thematic,
strategy) are marked `outside_scope`.

## 7. Known limitations (all surfaced by `verify`)
- Adjusted prices before 2007-01-01 are unverified. The gap is in what NSE's Corporate Actions page lists for
  2004-2006, not in the held copy: a fresh download of that page for 2004-01-01..2006-12-31 (2,062 records) is
  identical, record for record, to the held feed's 2004-2006 records (`data/raw/corporate_actions/`, 2026-11-16).
  No evidence exists to move `COVERAGE_START`.
- 15 share actions in the feed are contradicted by prices and are not applied (`build/actions_rejected_or_shifted.csv`).
- 108 demergers/schemes/rights-without-price leave documented breaks (`data/curated/waivers.csv`); 176 further
  overnight moves have no explanation in the feed (SME and ETF unit events, missing splits, crashes).
- Rights adjustments use the theoretical price and differ from the market move by >25% on 3 days.
- Index sources disagree on 1,061 index-days (338 by ≥0.1%), flagged per row; 925 index-days are missing
  inside index lives (non-publication days).
- Membership (Nifty 50): VERIFIED 2004-05-24 → today. Not verified:
  - 2004-01-01 → 2004-05-23: L&T (a member until 2004-05-24) has no NSE bhavcopy before 2004-06-23, so the trading check fails.
  - 2016-04-01 → 2017-09-28 is VERIFIED as 51 securities of 50 companies: the Tata Motors DVR (TATAMTRDVR) was in the index
    (NSE 22 Feb 2016 release, A.1.e: "the Nifty 50 index will have 51 securities but continue to have 50 companies"). Inclusion
    2016-04-01 comes from the NSE workbook `IndexInclExcl.xls` (no held release names it); exclusion effective 2017-09-29 is in
    `ind_prs28082017.pdf`. `data/curated/index_dual_class.csv` allows +1 security on a day only while both the DVR and its parent
    (TATAMOTORS) are members, and the DVR still has to pass the +-3 session trading check (it traded on all 371 sessions).
  - Before 2004-01-01 there is no bhavcopy.
  History of the 2017→today window: it was once VERIFIED on count alone while Indian Oil (in per the Feb 2017 release, out
  2022-03-31) and Apollo Hospitals (in 2022-03-31) were wrong. The missing release is `ind_prs24022022_1.pdf`, which the press
  download skipped with ~300 other suffixed files (`ind_prsDDMMYYYY_1.pdf`) listed on niftyindices.com. It was added and the build
  now ends verification at any event it cannot undo (`membership.contradictions`). Other suffixed releases may hold more
  Nifty 50 changes; none are known to be missing, since the check reports no contradiction.
- Membership floor: `membership.FLOORS` lets an index be verified from a later date than the start of the data (planned: 2007-01-01 for
  Nifty 500 and Midsmallcap 400). Days before the floor are out of scope (neither verified nor counted as failures), and events before it
  cannot raise a contradiction for later days. Nifty 50, Next 50 and Nifty 100 have no floor.
- Membership (Nifty 100): anchored on `data/raw/constituents/2026-11-15/ind_nifty100list.csv` (100 symbols). VERIFIED 2004-01-01 (first bhavcopy day) → today
  (one window; full build/verify 2026-11-16, no FAIL). Events: NSE workbook sheet "Nifty 100" to 2020, then the Nifty 100 section of 16 review
  releases 2020-09-25 → 2026-09-30 and the DVR exclusion of 2024-08-30 (`ind_prs23082024_1.pdf`), all in `index_events_press.csv`.
  The real members number exactly 100 and trade within ±3 sessions. Documented extras (cited in `index_dual_class.csv` and
  `index_size_exceptions.csv`): Tata Motors DVR 2016-04-01 → 2020-06-25 and 2023-09-29 → 2024-08-29 (101 securities, 100 companies);
  zero-price demerger entities for Jio Financial (2023-07-20 → 09-06), ITC Hotels (2025-01-06 → 02-07), Siemens Energy, Tata Motors
  (TMCV), Kwality Wall's (2025-12-05 → 2026-02-23) and the Vedanta four (2026-04-30 → 06-23). Name links from held files, all in
  `name_aliases.csv` with their evidence: ABB Ltd. (INFERRED, EQUITY_L), Colgate (COLGATE until 2007-11-28), "Larsen & Toubro Ltd.-Sus" -> L&T,
  "NIIT Ltd.-Sus" -> NIIT (workbook "-Sus" suffix stripped, INFERRED), "JSW Steel Ltd." -> JINDVIJSTL (INFERRED, same issuer ISIN INE019A) and
  "Merck Ltd." -> EMERCK (INFERRED, symbolchange.csv; EMERCK trades in the raw 2004 bhavcopy). Identity joins for these tickers are NOT made
  (the old/new tickers are more than 30 days apart, so `identity_links.csv` cannot join them); the aliases resolve each event by date.
  Cross-check (not a source): Nifty 100 equals Nifty 50 + Next 50 on every day all three are verified, except the DVR days and
  2004-05-24 → 05-27, when the NSE workbook has Vijaya Bank in Nifty 100 from 2004-05-24 but in Next 50 only from 2004-05-28 (a conflict
  inside the workbook; not resolved). Not verified: nothing, except that other suffixed mid-cycle releases (e.g. ind_prs20012026_2,
  ind_prs20052026_1, ind_prs17062026_2, ind_prs13072026_1) are not held; a membership change in one of them would show only as a
  contradiction if it touched a current member.
- Membership (Nifty Next 50): anchored on `data/raw/constituents/2026-11-15/ind_niftynext50list.csv` (50 symbols).
  VERIFIED 2004-01-01 (first bhavcopy day) → today. On days with documented dummy-symbol constituents the rule is:
  the real members number exactly 50 and trade within ±3 sessions, and the published total is 50 + the extras.
  - Dummy-entity days (92): Siemens Energy (DUMMYSIEMS) 2025-04-07 → 2025-06-26; Vedanta Aluminium Metal, Power, Oil and Gas,
    Iron and Steel (DUMMYVEDL1-4) 2026-04-30 → 2026-06-23 (4, then 2, then 1 extras as each is excluded). The extras per day are
    in `data/curated/index_size_exceptions.csv`, each row citing its release (`membership.extra_members`). The dummies cannot
    trade, so they are not checked as members; the dates rest on the releases alone, not on a daily NSE constituent list.
    This relaxes "exactly 50 constituents" to "exactly 50 real members plus documented placeholders" for these days only.
  - Before 2004-01-01 there is no bhavcopy.
  History of the 2017→today window: it was once VERIFIED on count alone while Indian Oil (in per the Feb 2017 release, out
  2022-03-31) and Apollo Hospitals (in 2022-03-31) were wrong. The missing release is `ind_prs24022022_1.pdf`, which the press
  download skipped with ~300 other suffixed files (`ind_prsDDMMYYYY_1.pdf`) listed on niftyindices.com. It was added and the build
  now ends verification at any event it cannot undo (`membership.contradictions`). Other suffixed releases may hold more
  Nifty 50 changes; none are known to be missing, since the check reports no contradiction.
- Membership (Nifty Next 50): anchored on `data/raw/constituents/2026-11-15/ind_niftynext50list.csv` (50 symbols).
  VERIFIED 2004-01-01 (first bhavcopy day) → 2025-04-04, 2025-06-27 → 2026-04-29 and 2026-06-24 → today. Not verified:
  - 2025-04-07 → 2025-06-26 and 2026-04-30 → 2026-06-23: demerger entities (Siemens Energy as DUMMYSIEMS; the four Vedanta
    spin-offs as DUMMYVEDL1-4) were held at zero price, so the index had more than 50 constituents. These days are listed with
    their releases in `data/curated/index_size_exceptions.csv` and are never VERIFIED (`membership.exception_mask`).
  - Before 2004-01-01 there is no bhavcopy, so nothing earlier can be verified. (Himachal Futuristic, out 2004-03-01, traded as
    HIMACHLFUT until 2011-02-07 and only then as HFCL; the workbook's singular "Communication" is aliased to HIMACHLFUT.)
  Name links for 2004-2011 come in three grades, each marked in `name_aliases.csv`: exact name+symbol rows (press releases,
  NSE corporate-actions files); links INFERRED from NSE ticker history (`symbolchange.csv`: Aventis, Mundra Port, United
  Phosphorus, Motor Industries, ICI India, E.Merck, Piramal Healthcare) or from the NSE equity list / a renamed ticker
  (Escorts, India Cement, Polaris, the "Vijaynagar" spelling of Jindal Vijayanagar Steel). The inferred grade was accepted by the
  project owner on 2026-11-16. GESHIPPING -> GESHIP (NSE re-issued the share under a new ISIN, ticker change with a 20-day gap)
  is joined by a curated identity link (`data/curated/identity_links.csv`, citing the corporate-actions rows), a new third join
  rule in `identity.link`; it changes `sec_id` numbering of later securities.
  Changes from 2020-09 are entered from 16 press releases (`index_events_press.csv`). Three were not in the original download:
  `ind_prs17022023_1.pdf` and `ind_prs25062025_2.pdf` (suffixed files, saved by hand) and `ind_prs23082021.pdf`, which was held
  but is an image-only PDF with no extractable text (read from page renders). Aliases come from name/symbol pairs on the same
  table row of a held release or an exact name match in NSE's corporate-actions files, each citing its source. An alias may be
  `exclusive` inside a date window (used only for United Breweries Ltd. -> UBL, not United Breweries (Holdings) -> UBHOLDINGS).
  One workbook typo ("Punjab & National Bank", Next 50 exit 2004-05-28) is aliased to PNB for that month only.
- 2004 prices for some large companies are absent from NSE's own files (e.g. L&T before 2004-06-23).

## 8. Held inputs (origin not re-verified)
`IndexInclExcl.xls` (NSE Indices workbook format, ends 2020-09-14), `raw_corporate_actions_1995_2026.json`,
`symbolchange.csv`, `EQUITY_L.csv`. They were obtained before this rebuild; the corporate-action feed
could not be re-fetched by script because nseindia.com refuses scripted requests. For 2004-2006 it was
checked against a manual download from NSE's own Corporate Actions page: 2,062 of 2,062 records match
(symbol, ex-date, purpose), so that slice of the feed is confirmed as NSE-published; other years are not re-checked. 521 manifest rows lost to a
concurrent-write bug were reconstructed from the files on disk and are marked as such.
