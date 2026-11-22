# Handoff for a new session (updated 2026-11-22, end of session 3)

Project: Nifty Universe (`nseuniverse`), a deterministic, source-traceable NSE point-in-time dataset for selecting backtest universes. Read first: `CHECKPOINT.md`, `docs/AUDIT_PLAN.md`, `docs/AUDIT_REPORT.md`, `docs/OPEN_ISSUES.md`.

## State
- Data start is **2007-01-01** (owner decision); the API refuses unverified index/date. 27 indices have verified membership; start dates per index are in `data/build/membership/coverage.parquet` (Nifty 50/Next 50/100 from 2007-01-02, Nifty 200 from 2010-11-01, Nifty 500 from 2013-08-26, 2016-09-30 for LargeMidcap 250/Midcap 150/Smallcap 250, later for sector indices).
- Commands: `python -m nseuniverse.cli build|verify [--only NAME]|update` (no `__main__`). Full `verify` is 13 checks, about 11 minutes; `build` several minutes. Last full verify: 13/13 without FAIL (2026-11-22, after the dividend fixes of A15).
- 97 tests pass. Everything up to the end of session 3 was pushed to origin on 2026-11-22 with the owner's approval; later commits are local until the owner says push.
- `data/raw/` now holds 13,548 manifest files, including `constituents_archive/` (250 archived NSE constituent lists from the Internet Archive).

## Working rules (owner)
Nothing is estimated. Every curated row cites a file in `data/raw/`. Ask before pushing, deleting, or saving downloads into `data/raw/` (state names, source, size); audit downloads go to the scratchpad first. Do not bypass NSE or BSE bot protection (scripted calls to NSE's corporate-actions API and BSE bhavcopy were refused; stop there). Add a unit test for every new code path. `999 dump/`, `Project Requirement.docx` and untracked scratch stay as they are (owner decision).

## Done (see AUDIT_REPORT.md)
Stages 0-3, 5, 6 (incl. archive checks 6.4b/6.4c), 7, 8, 9 and the Stage 1 re-download sample are done. Stage 4 is half done: factors for 60 securities match an independent rebuild (92 of 92 events); the dividend entries had six defects, all fixed and rebuilt (A15). Stage 5: 361 index-days differ >0.1% between sources, history series tracks the parent better; equal-weight correlation 0.967 (Nifty 50). Stage 8: no look-ahead on 10 dates, 0 refusal violations on 2,960 pairs, empty-range now raises. Stage 9: README/CHECKPOINT/METHODOLOGY numbers corrected, audit status and thin spots added to README.

## Pending, in order (next session)
1. **Stage 4 remainder** (A16): (a) third-party adjusted-price comparison for 30 stocks (Infosys bonus 2014/2018, HDFC Bank split 2019, Bajaj Auto demerger 2008, Reliance bonus 2017; Yahoo public chart endpoint as in `audit/stage24_prices.py`, tolerance 0.5 percent, explain each miss; downloads to scratch); (b) review at least 50 of the 15 rejected actions / 108 waivers / 177 unexplained moves (`build/actions_rejected_or_shifted.csv`, `data/curated/waivers.csv`, `build/unexplained_jumps.csv`): each needs a cause or a documented gap; (c) review the ~21 dividend records where the auditor's parser and the project differ (rerun `audit/stage4_dividends.py <scratch>`; the 248 factor-2 rows are InvIT headline totals and the project is right); decide GENESYS 2019 `Rs.0125` and SBT 2009 `130%`; (d) the 15 rejected share actions: confirm none is a true action (WIPRO-style bonus 3:2 inside the continuity band).
2. Unreviewed thin spots: A5 unit test for `build_anchored`; Stage 5.3 base date/value vs NSE methodology (no document held, ask the owner).
3. After any change: `python -m nseuniverse.cli build`, then `verify` (13 checks, about 10 minutes; prints nothing until done), regenerate baselines only for deliberate changes, ask before pushing.

## Known thin spots (state them, do not hide them)
- Membership 2007-05..2009-12 has only one archived capture (Nifty 50, 2007-04-30); it rests on the workbook, press releases and the daily size/anchor checks. The owner asked whether to start the bank at 2010; recommendation given: keep 2007, treat 2007-2009 as lower evidence, back-test from 2010 for fully confirmed membership.
- Nifty 500 / Nifty 200 membership has no archived list before 2014.
- `IndexInclExcl.xls` origin unverified (C5). REIT inclusions of 2026-09-30 are absent from NSE CSVs captured 2026-10-09..25 (build follows the release; open note in A14).
- Adjusted prices are not yet independently audited (Stage 4). Index weights, liquidity/circuit limits, bid-ask and costs are not in the data.
- `sec_id` labels are not stable across rebuilds; key anything durable by symbol plus ISIN.
