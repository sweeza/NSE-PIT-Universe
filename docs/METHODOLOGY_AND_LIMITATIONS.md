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
special sessions (5,684 trading days 2004-01-01..2026-11-19).

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
Result: 1,281 kept, 112 untestable, 6 rejected, 0 shifted (108 waived breaks). A bonus of debentures, NCRPS or preference shares is not a share bonus: it is recorded as SCHEME and never gets a share factor (before 2026-11-23 nine of these were rejected by this gate and two untestable ones were applied wrongly).

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
member traded within ±3 sessions (two weekend special sessions, 2010-05-16 and 2012-11-11, have partial bhavcopies, so members appear untraded on those two days). Press-release changes after the workbook (2020-09 →) are entered from
the PDFs into `data/curated/index_events_press.csv`, each citing its file. Rolling back, an inclusion of a security that is
not a member at that point (or an exclusion of one that is) is a **contradiction**: a change is missing from the sources,
so no date from that event onward is VERIFIED.

**Scope.** The indices in scope are NSE's "Broad Market" (23) and "Sectoral" (34) categories, listed with their
source in `data/curated/index_universe.csv`. Following Phase 4, 27 indices have active `VERIFIED` coverage windows:
20 directly anchored indices in `membership.ANCHORED` and 7 composite benchmark indices in `membership.COMPOSITE_ANCHORS`
(e.g., `NIFTY500MULTICAP502525`, `NIFTYMIDSMALLCAP400`, `NIFTYTOTALMARKET`). Across all 27 verified indices, there are 40
distinct verified windows and **0 contradictions** remaining in the entire dataset (the historical `NIFTYMIDCAP100 2009-03-27` Areva T&D demerger exclusion was verified and resolved via official NSE release `ind_prs12122011.pdf`).
Subset invariance rules align strictly with official NSE index governance (including the `2018-04-02` restructuring of Midcap/Smallcap benchmarks under `ind_prs05012018.pdf` and `ind_prs22022016_1.pdf`), yielding 0 subset violations across all 4,929 trading days from `2007-01-02` through `2026-11-19`.
The remaining 30 indices in `index_universe.csv` lack historical workbook sheets in `IndexInclExcl.xls` and legitimately
remain `UNVERIFIED` per strict PIT methodology.

## 7. Known limitations (all surfaced by `verify`)
- Adjusted prices before 2007-01-01 are unverified. The gap is in what NSE's Corporate Actions page lists for
  2004-2006, not in the held copy: a fresh download of that page for 2004-01-01..2006-12-31 (2,062 records) is
  identical, record for record, to the held feed's 2004-2006 records (`data/raw/corporate_actions/`, 2026-11-16).
  No evidence exists to move `COVERAGE_START`.
- 6 share actions in the feed are contradicted by prices and are not applied (`build/actions_rejected_or_shifted.csv`); two of them (GULFPETRO 2013, AHLEAST 2022) are real actions that a second source confirms but the one-day price test cannot (price band, same-day demerger); see AUDIT_REPORT Stage 4.3.
- 108 demergers/schemes/rights-without-price leave documented breaks (`data/curated/waivers.csv`); 177 further
  overnight moves have no explanation in the feed: 97 SME-platform securities (the feed holds no SM/ST records at all), 60 ETF unit splits, 12 real price moves with no corporate action, 8 after the feed ends (2026-10-16). Review: `audit/stage43_review.csv`.
- Rights adjustments use the theoretical price and differ from the market move by >25% on 3 days.
- Index sources disagree on 1,061 index-days (338 by ≥0.1%), flagged per row; 929 index-days are missing
  inside index lives across 208 indices (869,785 index-days total).
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
- Membership floor (decision 2026-11-16): every index is verified from 2007-01-01 only (`membership.FLOORS`; adjusted prices are not
  verified before that date). Days before the floor are out of scope: neither verified nor counted as failures, and events before it
  cannot raise a contradiction for later days. Nifty 50, Next 50 and Nifty 100 are each VERIFIED 2007-01-02 → today in one window.
  The 2004-2006 findings below are kept as history only: they no longer affect any claim.
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
    Audit note (2026-11-22): the build checks only the real-member count; the dummy rows in `index_size_exceptions.csv` do not change any
    result (removing each of the 29 changed nothing), so they are documentation, not evidence. The Bank, Pharma and PSU Bank rows are real size changes and do matter.
  - Before 2004-01-01 there is no bhavcopy.
  History of the 2017→today window: it was once VERIFIED on count alone while Indian Oil (in per the Feb 2017 release, out
  2022-03-31) and Apollo Hospitals (in 2022-03-31) were wrong. The missing release is `ind_prs24022022_1.pdf`, which the press
  download skipped with ~300 other suffixed files (`ind_prsDDMMYYYY_1.pdf`) listed on niftyindices.com. It was added and the build
  now ends verification at any event it cannot undo (`membership.contradictions`). Other suffixed releases may hold more
  Nifty 50 changes; none are known to be missing, since the check reports no contradiction.
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
