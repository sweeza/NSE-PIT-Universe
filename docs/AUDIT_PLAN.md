# Independent audit plan

Purpose: show that the dataset is valid, not just that `verify` passes. `verify` is written by the same
project as the data, so it can share its blind spots. Every step below uses a separate code path, a
separate source, or deliberately breaks the data to see whether the gate notices.

Ground rules
- The auditor writes its own scripts in `audit/` (not `nseuniverse/`) and does not import project parsers.
- Sample with a fixed seed and record it, so results are repeatable.
- Every finding gets an ID, severity (S1 wrong data, S2 undocumented gap, S3 doc/cosmetic), evidence, and a fix or waiver.
- Nothing is downloaded or pushed without the owner's yes (file name, source, size first).

## Stage 0: Reproducibility (about 1 hour, mostly waiting)
1. Fresh clone, create a clean venv from `requirements-lock.txt`, run `pytest -q`.
2. Rebuild from `data/raw/` alone; compare every `data/build` file hash to `checksums.txt`. Run the build twice.
3. Re-hash every file in `manifest.csv` with an independent tool (`sha256sum`/`Get-FileHash`), and list files on disk that are not in the manifest.
Pass: byte-identical rebuild, zero hash differences.

## Stage 1: Raw source authenticity (S1 risk: bad inputs)
1. Re-download a seeded sample from NSE: 150 bhavcopy days (all era boundaries: first/last legacy, first UDiFF, 2008, 2020), 20 daily index files, all 59 constituent CSVs, 100 press PDFs. Compare hashes.
2. The four inputs of unverified origin (`IndexInclExcl.xls`, `raw_corporate_actions_1995_2026.json`, `symbolchange.csv`, `EQUITY_L.csv`, issue C5): fetch fresh copies and diff. Record every difference.
3. Check the `fetched_utc` estimates (issue A4) are labelled as estimates.

## Stage 2: Bhavcopy and calendar
1. Independent reader: plain `zipfile` + `csv`, no project code. Compare 300 seeded days cell by cell to the build; also total row counts for all 5,684 days (zip line count minus header).
2. Calendar: compare trading days to an independent list (NSE holiday circulars for sampled years). Investigate the 30 weekend sessions and the 317 weekday non-sessions flagged by `calendar`; each must be a known special session or holiday.
3. Outlier scan on the raw table: close outside [low, high], zero or negative volume with trades, price jumps over 50% that are not corporate actions, duplicate (symbol, series, date).
4. Third-party spot check: closing prices of 40 large caps on 20 dates each against a second public source (Yahoo/BSE). Tolerance 0.5%; explain every miss.

## Stage 3: Identity
1. Test 30 known renames/mergers (INFOSYSTCH to INFY, ZEETELE to ZEEL, VSNL to TATACOMM, HDFC into HDFCBANK, Hero Honda to HEROMOTOCO and others): one `sec_id`, continuous ISIN, no day with two symbols.
2. Review the two curated joins (`GESHIPPING`, `CASTROL`) and all symbol-reuse cases (same symbol, different company), which is the dangerous direction.

## Stage 4: Adjusted prices (verified claim starts 2007-01-01)
1. Rebuild adjustment factors independently from the raw corporate-action JSON for 60 stocks covering splits, bonuses, rights, mergers, demergers. Compare factor by factor and the resulting adjusted close.
2. Compare adjusted closes to a third-party adjusted series for 30 stocks (Infosys bonus 2014/2018, HDFC Bank split 2019, Bajaj Auto demerger 2008, Reliance bonus 2017). Tolerance 0.5%, explain every miss.
3. Manually review the 15 rejected actions, 108 waivers, 177 unexplained moves (sample at least 50). Each must have a cause or be moved to a documented gap.
4. Confirm the API refuses pre-2007 adjusted prices.

## Stage 5: Index values
1. For every index, compare daily-file and history-API values on overlap; list all 338 conflicts above 0.1% and decide which source is right (check against NSE factsheets for a sample).
2. Sanity: Nifty 50 daily return vs an equal-weight return of the held members. Correlation must be above 0.97; investigate days below.
3. Base date and base value of each index match NSE methodology documents.

## Stage 6: Membership (the highest risk)
1. Recount independently from `intervals.parquet`: Nifty 50/100/500 etc. must have the official size on every VERIFIED day (allowing only the cited dummy extras). Also check every member has a bhavcopy row that day, with no market-holiday intervals.
2. Churn profile: changes per year per index. Flag any year or rebalance with unusual counts (too many or too few) and check each against the press releases.
3. Known-event test, about 60 hand-picked facts from NSE and news: Satyam out (Jan 2009), Tata Motors DVR (2016-17), Zomato in (Mar 2025), HDFC merger (Jul 2023), Jio Financial in/out (Jul-Sep 2023), Vedanta/ITC/Siemens demergers. Each must hold on the exact date.
4. Blind sample: 150 random (index, date) pairs. For each, the auditor reconstructs membership from the nearest official source (constituent archive, factsheet, press release) without looking at the build, then compares.
5. Press-event completeness: extract text from every held press PDF with a different method (render pages and read, not the same text layer), find all "Replacements in indices" notices, and diff against `index_events_press.csv`. Missing events are S1. Also quantify the unheld releases (issues B7, B12) and which indices they could touch.
6. Press-event accuracy: audit a 5% random sample of the roughly 3,500 new rows (and every row for the five fully verified indices) against the PDF page.
7. Alias audit: every row marked INFERRED and every "ticker present in bhavcopy" row (the 335 new ones). Confirm same company via ISIN continuity or an official rename notice. A wrong alias would not show up in `verify`.
8. Exemptions audit: list every FLOORS entry, size exception, dual-class row, and the date-based skips in `check_membership`. Remove each one in a scratch copy and confirm that exactly the expected checks fail (shows the exemptions are necessary and not hiding errors).

## Stage 7: Test the gate itself (mutation testing)
In a scratch copy, inject known errors and confirm `verify` goes FAIL for each:
- swap one Nifty 50 member for a non-member on one date; shift one event date by one trading day;
- delete one press event; add a fake alias to the wrong company; corrupt one bhavcopy cell; flip one corporate-action ratio; remove one raw file referenced by curated data.
Record which injected errors the gate misses. Each miss is a gap in the gate and gets a new check or test.

## Stage 8: Point-in-time and API
1. Look-ahead test: `as_of=D` results must be identical whether the build contains data after D or not (truncate raw data to D, rebuild, compare).
2. API contract: `CoverageError` on every UNVERIFIED or PARTIAL date range; no silent empty results; error messages name the reason.
3. Add the missing `build_anchored` test (issue A5).

## Stage 9: Documentation honesty
Every number in `README.md`, `CHECKPOINT.md`, `docs/*.md` is regenerated by a script from the build and compared to the text. Claims such as "complete" must match `OPEN_ISSUES.md`.

## Exit criteria
- Stages 0, 1, 7, 8 pass with no S1 finding open.
- Stage 6 blind sample has zero S1 errors, and any S2 is documented.
- Stage 4 and 2 third-party comparisons are within tolerance or every miss is explained.
- Report in `docs/AUDIT_REPORT.md`: findings table, sample sizes and seeds, error rate with confidence interval, what was not tested.

## Suggested order and effort
Stage 0 and 7 first (cheap, and tell you whether the gate is worth trusting), then 6, 1, 4, 2, 3, 5, 8, 9. Roughly 3-5 working days for one auditor, plus owner time to save any NSE files that Stage 1 and Stage 6 need.
