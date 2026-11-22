# Audit report (interim): Stages 0, 7 and part of 6

Date: 2026-11-22. Code at commit 34deb34. Scripts: `audit/rehash.py`, `audit/mutate.py` (written by the auditor, no project parsers used for the re-hash).

## Stage 0: reproducibility

| Test | Result |
|---|---|
| Independent SHA-256 and size re-hash of all 13,286 manifest rows | PASS: 0 missing, 0 hash or size differences, 0 duplicate paths |
| Clean venv from `requirements-lock.txt`, `pytest -q` | PASS: 76 passed |
| Rebuild from raw into an empty `data/build` (5 min 46 s) | PASS: all 35 parquet SHA-256 equal the committed `checksums.txt` |

Limits: same machine and Python 3.12.10 only; the scratch copy came from the working tree (equal to HEAD), not `git clone`, because cloning from the Google Drive folder stalled.

## Stage 7: does the gate catch injected errors?

One error injected into a scratch copy of `data/curated`, membership rebuilt, `check_curated_provenance` and `check_membership` run, and verified coverage compared to the baseline.

| Injected error | Gate result | Coverage effect | Verdict |
|---|---|---|---|
| Baseline, no change | PASS | none | OK |
| Fake source file in a press event | FAIL (provenance) | n/a | Caught |
| Drop Nifty 50 inclusion (LTIM, 2023-07-13) | PASS | NIFTY50 loses 6,036 verified days | Caught by coverage loss (fails safe) |
| Swap that inclusion to ASIANPAINT | PASS | NIFTY50 loses 7,262 days; one fewer verified window | Caught by coverage loss |
| Flip an exclusion to an inclusion (SHREECEM) | PASS | NIFTY50 loses 2,437 days | Caught by coverage loss |
| Move an exclusion by 1 day (IOC) | PASS | NIFTY50 loses 1 day | Caught, 1-day sensitivity |
| Move an exclusion by 7 days | PASS | NIFTY50 loses 7 days | Caught |
| Drop dual-class row (TATAMTRDVR) | PASS | NIFTY50 loses 546 days | Caught by coverage loss |
| Point an alias (EIHOTEL) at WIPRO | PASS | none | **NOT caught** (see S2-2) |
| Drop a Nifty 100 size exception (Siemens dummy) | PASS | none | **NOT caught** (see S2-3) |
| Swap a symbol in Nifty 500 | not run: my row selector found no rows | | Rerun needed |

Reading: membership errors do not make `verify` FAIL. They shrink the VERIFIED coverage, which is a safe failure, but only if someone compares coverage with a baseline. Nothing in the release gate does that, so a PASS does not say how much is verified.

## Findings

| ID | Sev | Finding | Suggested fix |
|---|---|---|---|
| S2-1 | S2 | Five raw files are not in `manifest.csv`: `held/EQUITY_L.csv`, `held/IndexInclExcl.xls`, `held/raw_corporate_actions_1995_2026.json`, `held/symbolchange.csv`, `indexhist/IndexMapping.json`. They feed identity, actions and membership, and `check_manifest` exempts them, so a change would go undetected. | Add them to the manifest, marked "held, origin unverified". |
| S2-2 | S2 | A wrong alias that coexists with the right one is not detected (EIHOTEL to WIPRO changed nothing). The resolver picks among candidates, so a wrong extra alias is only harmless while the right one exists. A sole wrong alias is untested. | Rerun with the correct alias removed. Audit aliases per Stage 6.7. |
| S2-3 | S2 | The `index_size_exceptions.csv` rows for the Nifty 100 Siemens dummy have no effect on coverage: with the row dropped, Nifty 100 stays VERIFIED. The build counts only real members, so the exception rows are documentation, as OPEN_ISSUES B16 already says. README and METHODOLOGY say dummies are "verified via index_size_exceptions.csv". | Reword the docs, or make the build enforce the dummy count. |
| S3-1 | S3 | The release gate has no coverage regression check. | Store a baseline of verified days per index and fail when it drops. |

## Stage 6 (membership), partly done

Scripts: `audit/stage6_*.py`. Data: the rebuilt `data/build` (identical to the committed checksums).

| Test | Result |
|---|---|
| 6.1 Recount of members per day from `intervals.parquet`, all 27 verified indices, every verified day | Sizes equal the official size on every day except documented extra-security periods: Nifty 50 +1 (2016-04-01..2017-09-28, Tata Motors DVR); Nifty 100 and 200 +1 (2016-04-01..2020-06-25 and 2023-09-29..2024-08-29); Nifty 500 +1 (2016-04-01..2024-08-29); Smallcap 250 and Midsmallcap 400 +1 (2020-06-26..2023-09-28). Each matches a row in `index_dual_class.csv`. No day is off-size without a curated reason. |
| 6.1 Every member has a bhavcopy row on that day | Passes except on two weekend special sessions (2010-05-16, 2012-11-11), where the bhavcopy holds only a few symbols, so about 50 members per index show as not traded. Not a data error, but the claim "every member traded" needs that caveat. |
| 6.2 Churn per year (entries) | Nifty 50: 1 to 6 a year; Next 50: 6 to 19; Nifty 100: 5 to 17; Nifty 500: 18 to 106. Peaks are 2016 (April restructuring) and 2011 to 2012. Nothing implausible. |
| 6.3 Known-event probes (31) | 22 matched, 9 did not. I checked Zomato and Jio Financial (Nifty 50 from 2025-03-28), BEL and Trent (2024-09-30) and Adani Enterprises (2022-09-30) against the held releases: the data is right and my probe was wrong. The remaining misses are **inconclusive**, not errors: Satyam exit date (data: out by 2009-01-13), Adani Ports in Nifty 50 on 2016-06-01, IDFC First in Nifty Bank on 2019-01-01, and Jio Financial in Nifty 100 on 2023-07-21 (by design it is a dummy then). My probe list came from memory, not sources, so this test is weak. It needs a sourced list. |
| 6.6 All 3,257 curated press events re-read with PyMuPDF (independent of the project's text files) | 3,257 of 3,257 symbols found in the cited release; direction (IN or OUT) agrees for 3,254. The 3 flagged are false alarms of my heuristic (Nifty Bank "inclusions" wording, and a "BSE Exclusion" row in a revocation table); each is correct on reading. Date is 0 to 150 days after the release date for every row. |

Findings from Stage 6

| ID | Sev | Finding |
|---|---|---|
| S3-2 | S3 | `data/build/press_text/ind_prs23082021.txt` is empty (29 bytes), although the PDF has a normal text layer that PyMuPDF reads (symbols and tables included). OPEN_ISSUES B8 calls this PDF image-only; that is out of date. Any check that reads `press_text` silently sees nothing for this release (94 rows rest on it). Their content matches the PDF. |
| S3-3 | S3 | Two weekend special sessions have partial bhavcopies, so "every member traded within the day" cannot hold there. Document it. |

Still to do in Stage 6: 6.4 blind sample against independent sources (needs the owner to supply factsheets or archives), 6.5 completeness (releases we do not hold, B7 and B12; and any held release with no curated rows). 6.7 and 6.8 are below.

### Stage 6.7 and 6.8 results

Scripts: `audit/stage67_aliases.py`, `audit/stage68_skips.py`, `audit/mutate.py` (modes `dropexc_N`, `dropdc_N`).

**6.8a Date-based skips in `check_membership`.** Removing the pre-2016 skip gives 3,144 violations (mostly Nifty 100 members absent from Nifty LargeMidcap 250 before its April 2016 launch, e.g. PATNI, RAYMOND, ZEEL, ADANIENT in 2008 to 2015). Removing the 2018 Midcap 100 skip gives 919 violations (2016-04 to 2018-04). The 2018 skip is explained in the code comments by held releases (not re-read by me). The pre-2016 one is not.

**6.8b Dropping each curated exemption (39 runs, membership rebuilt each time).**

| Exemption rows | Effect of dropping one | Reading |
|---|---|---|
| Dual-class (7 of 7: Tata Motors DVR in Nifty 50, 100 x2, 200, 500, LargeMidcap 250, Auto) | Each loses verified coverage, from 155 days (Nifty Auto) to 3,073 days (Nifty 500), and the loss spreads to the derived composites | All load-bearing: the gate really depends on them and fails safe without them |
| Size exceptions, demerger dummies (29 of 29: Next 50, Nifty 100, 200, 500, LargeMidcap 250; Siemens, Jio, ITC Hotels, HUL, Tata Motors, Vedanta, Sanofi, HEG and others) | **No effect at all**, every row | Decorative: the build counts only real members, so these rows are documentation, not part of the proof. Confirms S2-3 for every row. |
| Size exceptions, sector indices (3 of 3: Nifty Bank +2 from 2025-12-31, Nifty Pharma +10 from 2021-09-30, PSU Bank +1 2021-03-31..2022-03-30) | Each loses coverage (324, 1,877, 365 days) | Load-bearing. These are real size changes, not dummies. |

All 39 runs: `verify` checks `curated_provenance` and `membership` stayed PASS; only coverage moved.

**6.7 Alias audit (246 aliases).** Name overlap with bhavcopy names: 93 clear, 153 none or low (names are missing for older years, and many are genuine renames). I read all 153 and found no mapping that looks wrong. Date limits (valid_from, valid_to) are present on the risky ones (KPIT/BSOFT/KPITTECH, Kirloskar, Max India). But almost all the evidence is the held corporate-action feed and `EQUITY_L.csv`, which are the unverified-origin inputs (S2-1), so the check is circular until Stage 1 compares them with fresh NSE copies.

| ID | Sev | Finding |
|---|---|---|
| S2-4 | S2 | Nifty LargeMidcap 250 is marked VERIFIED for 2008-03-14..2015-09-24, before the index existed (launched 2016-04-01). On those days Nifty 100 is not a subset of it, which would contradict NSE's definition if the series is a backcast. The source and definition of that pre-2016 history are not documented. |
| S2-5 | S2 | Alias evidence is circular (see 6.7); depends on S2-1. |
| S3-4 | S3 | Two aliases point to symbols with no security in the build (`AGC Networks -> BLACKBOX`, `Pudumjee -> PUDUMJEE`). Dead rows. |
| S3-5 | S3 | The 29 dummy-demerger rows in `index_size_exceptions.csv` do not affect the result. Either make the build enforce them or label them documentation. (The README currently says they verify the dummies.) |

Not yet tested in Stage 7: bhavcopy cell corruption, corporate-action ratio flip, raw-file deletion, the Nifty 500 symbol swap. Stages 1 to 6, 8 and 9 are not started.

### Stage 1 (partial): held inputs vs fresh NSE copies, 2026-11-22

Fresh copies were downloaded from `nsearchives.nseindia.com/content/equities/` into the audit scratch folder only; nothing in `data/raw/` changed.

| Input | Result |
|---|---|
| `symbolchange.csv` | Held 1,066 rows, fresh 1,083. **Every held row is in the fresh file** (0 held-only); the 17 extra rows are changes effective 2026-10/11, after the held snapshot. The alias evidence that rests on this file is therefore authentic for its date range. |
| `EQUITY_L.csv` | 2,598 symbols in common. 8 differ: 7 ISIN changes (new ISIN after a corporate event, e.g. CCAVENUE, JSWDULUX) and one listing date (LANCER). 22 held-only and 33 fresh-only symbols are renames and new listings since the snapshot; series (EQ/BE) differ on many rows because it changes over time. Nothing contradicts a curated alias. |
| `IndexInclExcl.xls` | **Not checkable.** No live NSE link exists (SOURCES.md); origin stays undocumented. |
| `raw_corporate_actions_1995_2026.json` | **Not checked.** The NSE corporate-actions endpoint answered 403/404 to scripted requests; no further attempt was made to get around it. A fresh copy needs a manual download by the owner from the NSE corporate-actions page. |

Effect on S2-2/S2-5: alias evidence from `symbolchange.csv` and `EQUITY_L.csv` is now confirmed authentic; the circularity remains for aliases that rest on the corporate-action feed or the workbook.

Not run in Stage 1: the 150-bhavcopy, 20 daily-index, 59 constituent and 100 press-PDF re-download sample.

## Stage 2: bhavcopy and calendar (2026-11-22)

Scripts: `audit/stage2_bhav.py` (plain `zipfile` + `csv`, no project parser), `audit/stage2_cal_outliers.py`. Seed 20261122.

| Test | Result |
|---|---|
| 2.1 Row count, zip lines minus header vs `data/build/bhavcopy`, all 5,684 selected days | 0 differences; no build day without a raw file |
| 2.1 Cell by cell, 303 days (300 seeded + first/last day and first/last UDiFF day), 5,511,270 cells (ISIN, name, instrument id, all numeric columns) | 0 mismatches, 0 rows missing or extra |
| 2.2 Calendar: weekend sessions | 30, every one with 739 to 3,550 rows except 2010-05-16 (7 rows) and 2012-11-11 (14 rows). From 2012-03-03 on, the daily index file (a second NSE publication) exists for 18 of the 19 weekend sessions in range; 2012-11-11 has none. 11 sessions before 2012-02-21 have only the bhavcopy as evidence. |
| 2.2 Weekday non-sessions | 317 (10 to 19 a year). No index file exists on any of them, no run of 4 or more missing weekdays, and no session on 26 Jan, 15 Aug or 2 Oct. |
| 2.2 Bhavcopy without index file since 2012-02-21 | 13 days (2012-11-11, 2013-10-09, 2014-03-19, 2014-12-15, 2015-02-02, 2015-03-12/13, 2015-05-19, 2015-07-08, 2015-09-04, 2015-10-16, 2015-12-01, 2016-06-20). The reverse (index file with no bhavcopy) is empty. |
| 2.3 Outliers | 0 duplicate (date, symbol, series), 0 negative or zero close, 0 high<low, 0 open outside the range, 0 zero-volume rows with trades, 0 volume rows without trades. `close` outside [low, high] on 217 rows: **all** are series `T0` (T+0 settlement segment, 241 rows in all, 2024-03 onward), where the close is not a last-trade price. |
| 2.3 Jumps | 1,197 `EQ` rows move more than 50% from the previous close with the file's own previous close unchanged. 731 have a non-dividend corporate-action event within 5 days. The other 466 (hand view: tick-size moves at Rs 0.05 to 0.10, relistings, e.g. ARIHANT 39.65 to 907.55 on 2026-04-20, VISESHINFO, VKSPL) are raw NSE values, not build errors; they are the input to Stage 4. Listed in the scratchpad only (`stage2_jumps_noevent.csv`). |
| 2.4 Third-party close check (40 large caps x 20 dates) | **Not run.** Needs an external price source; owner to say which. |

Not tested: the 317 non-sessions were not compared with NSE holiday circulars (no source held); the evidence is that neither NSE publication exists for them. The 11 weekend sessions before 2012-02-21 rest on the bhavcopy alone (their row counts are those of normal sessions, so they are real sessions).

| ID | Sev | Finding |
|---|---|---|
| S3-6 | S3 | Weekend sessions 2010-05-16 and 2012-11-11 hold 7 and 14 symbols. They are in the calendar as trading days (muhurat-type partial sessions); anything that assumes a full cross-section on every trading day breaks there (same cause as S3-3). |
| S3-7 | S3 | 13 trading days since 2012 have no daily index file, so index values are missing on them. Check whether C3's 929 missing index-days include them; the list is now explicit. |
| S3-8 | S3 | `close` is outside [low, high] on 217 `T0` rows. Any consumer that assumes close within the range must exclude series `T0`. Document it in METHODOLOGY. |

## Stage 3: identity (2026-11-22)

Script: `audit/stage3_identity.py` (reads `data/build/identity/*.parquet`). The expectations (rename or different company) are the auditor's, from public corporate history, and are listed in the script so the owner can veto any.

| Test | Result |
|---|---|
| 3.1 Known renames, 30 pairs expected to be one `sec_id` | 24 one `sec_id`; 5 absent because my ticker was wrong (the data uses e.g. ADANIEXPO to ADANIENT, NICOLASPIR to PIRHEALTH to PEL, SESAGOA to SSLT to VEDL, plain PNB, plain KOTAKBANK, and each of those is one `sec_id`); 1 "split" is my error (Oriental Bank of Commerce merged into PNB in 2020, so two ids is right). Net: 0 wrong. |
| 3.1 Known mergers, 12 pairs expected to be different `sec_id` | 8 different (HDFC and HDFCBANK, Ranbaxy and Sun, Satyam and Tech Mahindra, Aditya Birla Nuvo and Grasim, LTI and Mindtree, three PSU banks); 3 absent; 1 "joined" is my error: Bharti Infratel was renamed Indus Towers after the merger, so one `sec_id` is right. |
| Invariant: two symbols on one day inside one `sec_id` | 0 overlapping segments |
| Invariant: one `sec_id` with more than one ISIN issuer | 0 |
| 3.2 The two curated joins (`GESHIPPING` to `GESHIP`, `CASTROL` to `CASTROLIND`) | Both are one `sec_id`; the ISIN issuer is the same, the source rows cite the held feed and `EQUITY_L.csv` |
| 3.2 Symbols used by more than one `sec_id` | 227. Where the ISIN issuer differs on adjacent segments, they are rightly separate. |

| ID | Sev | Finding |
|---|---|---|
| S2-6 | S2 | **One security is split into several `sec_id`s when a symbol is absent for more than 400 days (`GAP_DAYS`), even when the full ISIN is unchanged.** 62 adjacent same-symbol pairs share a full ISIN (46 where both sides are equities), e.g. ARIHANT (S01109 to S07091, gap 2022-02 to 2026-04), SICAGEN, KOVAI (three ids), SHAIVAL (four), GOODYEAR, NOVARTIND, ATLASCYCLE, PVP, VIVIMEDLAB. The rule is documented and conservative, but a same-symbol, same-ISIN return is the same security. Effect: per-security history (adjusted prices, returns) stops at the gap and restarts under a new id. Index membership is not affected: of the 114 ids involved, the 4 that were ever index members (S00054, S00606, S02837, S02891) left every index before their gap. Owner decision: keep (document) or join on same symbol and same full ISIN. |
| S3-9 | S3 | 89 adjacent same-symbol pairs share the ISIN issuer (62 the full ISIN). Of the rest, 124 pairs have no ISIN on one side (mostly G-sec and bond series such as `833GS2036`). They stay separate, which is harmless. |
