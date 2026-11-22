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
