# Handoff for a new session (updated 2026-11-22, end of day)

Project: Nifty Universe (`nseuniverse`), a deterministic, source-traceable NSE point-in-time dataset for selecting backtest universes. Read first: `CHECKPOINT.md`, `docs/AUDIT_PLAN.md`, `docs/AUDIT_REPORT.md`, `docs/OPEN_ISSUES.md`.

## State
- Data start is **2007-01-01** (owner decision); the API refuses unverified index/date. 27 indices have verified membership; start dates per index are in `data/build/membership/coverage.parquet` (Nifty 50/Next 50/100 from 2007-01-02, Nifty 200 from 2010-11-01, Nifty 500 from 2013-08-26, 2016-09-30 for LargeMidcap 250/Midcap 150/Smallcap 250, later for sector indices).
- Commands: `python -m nseuniverse.cli build|verify [--only NAME]|update` (no `__main__`). Full `verify` is 13 checks, about 11 minutes; `build` several minutes. Last full verify: 13/13 without FAIL (2026-11-22, after the S2-6 identity join and ratchet re-key); the later S2-9 composite fix was checked with membership, provenance and both baselines (PASS).
- 90 tests pass. Local commits are ahead of origin (last push was `06a8264`; later commits include the S2-9 fix, Stage 6.4b/6.4c and 250 archive CSVs). **Push only on the owner's explicit yes.**
- `data/raw/` now holds 13,548 manifest files, including `constituents_archive/` (250 archived NSE constituent lists from the Internet Archive).

## Working rules (owner)
Nothing is estimated. Every curated row cites a file in `data/raw/`. Ask before pushing, deleting, or saving downloads into `data/raw/` (state names, source, size); audit downloads go to the scratchpad first. Do not bypass NSE or BSE bot protection (scripted calls to NSE's corporate-actions API and BSE bhavcopy were refused; stop there). Add a unit test for every new code path. `999 dump/`, `Project Requirement.docx` and untracked scratch stay as they are (owner decision).

## Done today (see AUDIT_REPORT.md)
Stage 0 reproducibility, Stage 1 for `symbolchange.csv`, `EQUITY_L.csv` and the corporate-actions feed (all match fresh NSE copies; only `IndexInclExcl.xls` has no live source), Stage 2 (bhavcopy cell-for-cell, calendar, outliers, Yahoo price checks: 40 stocks and a 150-stock wide sample), Stage 3 identity (S2-6 join built), Stage 6 membership incl. archive checks 6.4b/6.4c (207 of 216 archived NSE lists match, 9 explained differences, S2-9 DVR error found and fixed), Stage 7 mutation tests (a price edit with a consistent manifest is caught only by an independent source; ratchet check added), API flags (`DataQualityWarning`, `attrs['flagged']`, `mask_gaps`, `mask_conflicts`, `source=`), press releases fully fetched (B7, B12 closed), B9 closed, dead aliases deleted, inferred aliases reviewed for 2007+.

## Pending, in order
1. **Stage 4 adjusted prices:** independent rebuild of adjustment factors for about 60 stocks (splits, bonuses, rights, mergers, demergers) from the raw corporate-action JSON, compare factor by factor and the adjusted close; also audit the **dividend entries** that `total_return` mode uses. Report any difference as a finding.
2. **Stage 5 index values:** the 1,061 two-source conflicts and 929 missing days (24 indices have conflicts; only Nifty 100 Low Vol 30 matters for equity strategies, 141 days, solved with `source="history"` or `mask_conflicts=True`).
3. **Stage 8 point-in-time and API:** as-of correctness, no future leakage, refusals outside coverage.
4. **Stage 9 docs honesty pass:** every README/METHODOLOGY claim backed by a check; state the thin spots below.
5. **Stage 1 sample:** re-download and hash-compare about 150 bhavcopy days, 20 index files, 59 constituent CSVs, 100 press PDFs (downloads to scratch, plain GETs, polite rate).
6. Update stale rows in `docs/OPEN_ISSUES.md`, final full `verify`, then ask the owner about pushing.

## Known thin spots (state them, do not hide them)
- Membership 2007-05..2009-12 has only one archived capture (Nifty 50, 2007-04-30); it rests on the workbook, press releases and the daily size/anchor checks. The owner asked whether to start the bank at 2010; recommendation given: keep 2007, treat 2007-2009 as lower evidence, back-test from 2010 for fully confirmed membership.
- Nifty 500 / Nifty 200 membership has no archived list before 2014.
- `IndexInclExcl.xls` origin unverified (C5). REIT inclusions of 2026-09-30 are absent from NSE CSVs captured 2026-10-09..25 (build follows the release; open note in A14).
- Adjusted prices are not yet independently audited (Stage 4). Index weights, liquidity/circuit limits, bid-ask and costs are not in the data.
- `sec_id` labels are not stable across rebuilds; key anything durable by symbol plus ISIN.
