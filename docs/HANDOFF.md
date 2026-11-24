# Handoff for a new session (updated 2026-11-23, end of session 5)

> **Scope note (2026-11-24):** the data bank was cut to its core (bhavcopy from 2007, split/bonus-adjusted prices, delivery, 27 verified equity indices with membership from 2010). Price bands, ASM/GSM, F&O, deals, impact cost, shares outstanding, dividends/total return, the 30 unverified indices, non-equity index values and 2004-2006 data were removed from the build; sections below that describe them are history. Full version: git tag `full-2026-11-24`; raw files: `archive/`.


Project: Nifty Universe (`nseuniverse`), a deterministic, source-traceable NSE point-in-time dataset for selecting backtest universes. Owner uses it for Nifty 500 (equal-weight and similar) backtests in other projects. Read first: `CHECKPOINT.md`, `docs/OPEN_ISSUES.md`, `docs/AUDIT_REPORT.md`, `docs/INDEX_AVAILABILITY.md`, then `nseuniverse/caveats.py`.

## State (all pushed to origin `sweeza/NSE-PIT-Universe`, branch main, last code commit `6336846`)
- Data start **2007-01-01**; the API refuses unverified index/date. 27 indices have verified membership (`api.index_availability()` and `docs/INDEX_AVAILABILITY.md` give each index's reliable start; Nifty 50/Next 50/100/Bank/Pharma from 2007-01-02, Nifty 200 from 2010-11-01, Nifty 500 and Midsmallcap 400 from 2013-08-26, Midcap 150/Smallcap 250/LargeMidcap 250 from 2016-09-30). 30 in-scope indices have no verified membership (levels only).
- Commands: `python -m nseuniverse.cli build|verify [--only NAME...]|update|fetch market` (no `__main__`). `build` takes about 30 minutes now (it parses about 35,000 raw market files from Google Drive), full `verify` about 12 minutes and prints each check when it ends. Last full verify: 14/14 without FAIL. After the gate-override change only `actions`, `adjusted_continuity`, `curated_provenance` and `ratchet_baseline` were re-run (no FAIL). **Run a full `build` + `verify` at the start of the next session.**
- 144 tests pass (`python -m pytest -q`, about 40 s).
- `data/raw/` holds 34,985 manifest files. `data/raw/market/` (2.9 GB: delivery, band changes, security lists, F&O ban lists, derivatives bhavcopy, deals archives and daily snapshots, 47 monthly impact-cost files) is **kept in Google Drive and deliberately not committed to git** (owner decision 2026-11-23). A fresh clone fails the manifest check until those files are restored.
- Untracked and left alone by owner decision: `999 dump/`, `Project Requirement.docx`.

## Working rules (owner)
Nothing is estimated; missing stays missing and the API refuses it. Every curated row cites a file in `data/raw/`. Ask before pushing, deleting, or saving downloads into `data/raw/` (state names, source, size). Do not bypass NSE or BSE bot protection: no calls to NSE `/api` endpoints, no cookie replay, no stealth tools; a real browser session operated like a person (with pauses) is allowed, plain GETs to `nsearchives.nseindia.com` are allowed (owner permission 2026-11-23); stop on any block or CAPTCHA. Add a unit test for every new code path. After any change: `build`, then `verify`; regenerate baselines (`verify.write_ratchet_baseline()`, `write_coverage_baseline()`) only for deliberate changes. Add every newly found limitation to `nseuniverse/caveats.py` with a test, not only to a document. Files use CRLF; edit with newline-preserving code (a regex `\b` typed in a heredoc can silently become a backspace character: check regexes after writing).

## What exists (public API in `nseuniverse/api.py`)
`prices` (adjusted, with `adj_gap`, `adj_reliable`), `index_values`, `index_members` (opt-in `backfill=True`), `index_availability`, `coverage`, `securities`, `delivery`, `price_band`, `asm_gsm`, `fo_ban`, `fo_eligible`, `deals`, `impact_cost`, `sme_securities`, `unreliable_adjusted`, `adjustment_gaps`, `caveats`, `explain`. Curated inputs in `data/curated/` include `actions_price_evidenced.csv` (55 ETF unit splits), `gate_overrides.csv` (GULFPETRO 2013, AHLEAST 2022), `adjustment_unreliable.csv` (7 names now), `waivers.csv` (108 documented breaks).

## Closing queue: the remaining OPEN rows in `docs/OPEN_ISSUES.md`, in the order to work them
Quick (no owner input needed; close and mark DONE with the evidence):
1. **A3** hard-coded `sec_id` check: grep code, notes and saved queries (the owner's other projects are outside this repo; ask which saved queries exist).
2. **A4** manifest `fetched_utc` estimates for four files: add a note in `docs/SOURCES.md` stating they are estimates; the hashes are real.
3. **B16 / B16a** dummy symbols (DUMMYHEG, DUMMYSKFIN): re-check whether the HEG exclusion release now exists in `data/raw/pressreleases`; if not, keep and document.
4. **B8** four press PDFs without a text layer (none cited by a curated row): close as not needed unless a curated row ever cites one.
5. **A9** coverage-baseline instructions: already done; mark DONE.
6. **A6** `999 dump/` originals: the owner deletes when ready; nothing to do.
Needs real work:
7. **A13** open: 10 same-symbol same-ISIN pairs in non-equity series are not joined (owner call), S3-6..S3-9 doc items, and a price edit that keeps the manifest and creates no flag is caught only by an independent price source.
8. **A14** more 2008-2009 archived membership lists (Internet Archive search, same method as the 250 lists already held); REIT inclusions of 2026-09-30 missing in captured NSE CSVs.
9. **C3** index values: 1,061 conflicting index-days and about 950 missing days (flagged and documented; closing means choosing a source per day, see `index_values(source=)`).
10. **C5** `IndexInclExcl.xls` origin unverified: content corroborated (archived lists, size and subset checks, press releases); only an owner statement of its origin can close it.
11. **A8** independent audit of the curated data and the verify logic: Stages 0-9 of `docs/AUDIT_PLAN.md` are done in this repo; the owner says an independent review was done in another harness; record its result and close.

Owner decisions: **A18** the five ETFs with non-round ratios (UTINEXT50, AXISNIFTY, UTISXN50, UTIBANKETF, SETFGOLD; leave flagged unless fund-house notices are supplied) and SUNTV 2007 (split figure not stated); SME stays out and flagged. **A20** about 90 unquantified rights/instrument events (needs issue prices from exchange notices; the Nifty 500 names from 2010 that matter: LAKSHVILAS 2014, SINTEX 2016, ANDHRAPAP 2010, TRENT 2010, INDHOTEL 2014). **A21** market cap, shares outstanding and free float have no source (look first for a monthly NSE report in the All Reports archives, as impact cost was found under `/content/nsccl/`; or niftyindices factsheet weights, members only).

## Wanted next (owner asked)
- Automate the corporate-action feed refresh: not possible with plain requests (bot protection). Options: a monthly real-browser run (like the deals download) and a warning in `update` when the feed ends more than 14 days before the last bhavcopy. The feed currently ends 2026-11-23.
- Impact cost is monthly only and exists for 47 of about 93 months (2019-03, 2021-01..06, 2023-05..06, 2023-10 onward); the order size (Rs 1 lakh) is the other harness's reading, not checked against an NSE document.

## Known thin spots (state them, do not hide them)
- Membership 2007-05..2009-12: one archived capture (Nifty 50, 2007-04-30), the workbook, press releases and the daily size/subset checks; back-test from 2010 for fully confirmed membership. Nifty 500/200 membership has no archived list before 2014.
- Adjusted prices: audited against Yahoo for 30 large stocks and by an independent factor rebuild for 60 securities. SME securities (the feed has no SM/ST records) and the curated unreliable names are `adj_reliable=False`. 115 unexplained overnight moves remain (97 SME, 12 real price moves, CCAVENUE 2026, 5 ETFs). 77 of the 108 waivers rest only on the feed text.
- Rights without an issue price (A20), dividends from free text, F&O eligibility derived from the derivatives bhavcopy (not NSE's list), price bands exact only from 2020, delivery vs bhavcopy volume differs on 0.072% of rows.
- `sec_id` labels are not stable across rebuilds; key anything durable by symbol plus ISIN.
- Tool notes: Yahoo comparison scripts live in session scratchpads only; Yahoo `close` also adjusts demergers and its single-day bars differ from NSE's on some days.
