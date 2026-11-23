# Handoff for a new session (updated 2026-11-23, end of session 4)

Project: Nifty Universe (`nseuniverse`), a deterministic, source-traceable NSE point-in-time dataset for selecting backtest universes. Read first: `CHECKPOINT.md`, `docs/AUDIT_PLAN.md`, `docs/AUDIT_REPORT.md`, `docs/OPEN_ISSUES.md`.

## State
- Data start is **2007-01-01** (owner decision); the API refuses unverified index/date. 27 indices have verified membership; start dates per index are in `data/build/membership/coverage.parquet` (Nifty 50/Next 50/100 from 2007-01-02, Nifty 200 from 2010-11-01, Nifty 500 from 2013-08-26, 2016-09-30 for LargeMidcap 250/Midcap 150/Smallcap 250, later for sector indices).
- Commands: `python -m nseuniverse.cli build|verify [--only NAME]|update` (no `__main__`). Full `verify` is 13 checks, about 11 minutes; `build` several minutes. Last full verify: 13/13 without FAIL (2026-11-23, after the Stage 4 parser fixes; ratchet baseline regenerated: rejected actions 15 to 6).
- 122 tests pass. Everything up to the end of session 3 was pushed to origin on 2026-11-22 with the owner's approval; the session-4 commit is local until the owner says push.
- `data/raw/` now holds 13,548 manifest files, including `constituents_archive/` (250 archived NSE constituent lists from the Internet Archive).

## Working rules (owner)
Nothing is estimated. Every curated row cites a file in `data/raw/`. Ask before pushing, deleting, or saving downloads into `data/raw/` (state names, source, size); audit downloads go to the scratchpad first. Do not bypass NSE or BSE bot protection (scripted calls to NSE's corporate-actions API and BSE bhavcopy were refused; stop there). Add a unit test for every new code path. `999 dump/`, `Project Requirement.docx` and untracked scratch stay as they are (owner decision).

## Done (see AUDIT_REPORT.md)
Stages 0-9 are done except the items below. Session 4 finished Stage 4: 30 stocks against Yahoo on every common day (26 clean, 4 with one explained demerger/rights stretch; 47 of 50 split dates match, the other 3 are bonus-plus-split days), all 15 rejected actions, 31 of 108 waivers and all 177 unexplained moves reviewed (`audit/stage43_review.csv`), dividend differences reviewed, GENESYS 2019 and SBT 2009 decided. Parser fixes: glued face-value splits (BHARTIARTL, ERAINFRA, COREEDUTEC), bonus of debentures/NCRPS/preference shares is SCHEME not a share bonus (two wrong factors, RADIOCITY 1.10 and TVSHLTD 1.0086, removed; 9 rejections gone), dividends next to splits, `Rs:-` amounts, `Rs.0125` unparsed. A5 test written.

## Pending, in order (next session)
1. **Owner decisions:** A18 (b)-(d): the 5 non-round ETFs, GULFPETRO/AHLEAST, SUNTV. SME stays out, flagged. A21: delivery quantity, price bands, market cap/free float, impact cost need a fetch route (owner downloads, or approves scripted NSE archive access). Index base dates were checked against the methodology PDF (no mismatch); the five Method_*.pdf in `999 dump/` are one 352-page document.
2. Unreviewed thin spots: Stage 5.3 base date/value vs NSE methodology (no document held, ask the owner); the other 77 waivers (Yahoo covers only 31; the rest rest on the feed text); A20 rights without issue price (needs a source).
3. After any change: `python -m nseuniverse.cli build`, then `verify` (13 checks, about 10 minutes; prints nothing until done), regenerate baselines only for deliberate changes (`verify.write_ratchet_baseline()`, `write_coverage_baseline()`), ask before pushing.

## Tool notes
- Yahoo comparison scripts live in the session scratchpad only; `audit/stage24_prices.py` is the committed sample version. Yahoo `close` is split-adjusted and also adjusts demergers; its single-day bars differ from NSE's close on some days (2025-03-18 in 28 of 30 stocks).
- Windows: files here use CRLF; edit with newline-preserving code.

## Known thin spots (state them, do not hide them)
- Membership 2007-05..2009-12 has only one archived capture (Nifty 50, 2007-04-30); it rests on the workbook, press releases and the daily size/anchor checks. The owner asked whether to start the bank at 2010; recommendation given: keep 2007, treat 2007-2009 as lower evidence, back-test from 2010 for fully confirmed membership.
- Nifty 500 / Nifty 200 membership has no archived list before 2014.
- `IndexInclExcl.xls` origin unverified (C5). REIT inclusions of 2026-09-30 are absent from NSE CSVs captured 2026-10-09..25 (build follows the release; open note in A14).
- Adjusted prices are audited against Yahoo for 30 large stocks and by an independent factor rebuild for 60 securities; SME securities (97 unexplained moves) and ETF unit splits (60) are not adjusted at all. Index weights, liquidity/circuit limits, bid-ask and costs are not in the data.
- `sec_id` labels are not stable across rebuilds; key anything durable by symbol plus ISIN.
