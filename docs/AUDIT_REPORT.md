# Audit report (interim): Stages 0, 7 and part of 6

> **Scope note (2026-11-24):** the data bank was cut to its core (bhavcopy from 2007, split/bonus-adjusted prices, delivery, 27 verified equity indices with membership from 2010). Price bands, ASM/GSM, F&O, deals, impact cost, shares outstanding, dividends/total return, the 30 unverified indices, non-equity index values and 2004-2006 data were removed from the build; sections below that describe them are history. Full version: git tag `full-2026-11-24`; raw files: `archive/`.


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

### Stage 1 (continued): corporate-actions feed vs fresh NSE download, 2026-11-22

The owner downloaded `CF-CA-equities-01-01-1995-to-22-11-2026.csv` (44,032 rows, 5,580,662 bytes) from NSE's Corporate Actions page; it is in `999 dump/` (not in `data/raw/`). Compared with `held/raw_corporate_actions_1995_2026.json` (43,816 records) on (symbol, ex-date, purpose text).

- **Every held record is in the fresh file**, except 29 whose symbol NSE has since renamed (NOVARTIS/NOVARTIND to EVONILE, ICICIPRULI to ICICILIFE). After mapping renames with the fresh `symbolchange.csv`, 10 held rows remain unmatched, all of them part of the same rename chains (EVONILE) or text revisions.
- **The 216 extra fresh rows** are events after the held snapshot (ex-dates to 2026-11-20); only 7 fresh-only rows have an ex-date on or before the held file's last ex-date (2026-10-16): two EVONILE rows (rename), DTIL x2, SHIVAMAUTO and HINDCOMPOS (events added or revised after the snapshot).
- Reading: the held feed is genuine NSE data, with no altered or missing historical rows found. Issue C5 now rests only on `IndexInclExcl.xls`. The fresh CSV has no ISIN column; the held JSON does.

## Stage 7 (raw layer): bhavcopy cell, corporate-action ratio, raw deletion (2026-11-22)

Script: `audit/mutate_raw.py`. Real `data/raw` untouched; each run uses a scratch root with junctions to unchanged folders and copies of the changed file. "Manifest fixed" means the manifest hash of the changed file was rewritten, i.e. an error that is consistent with the manifest. The manifest-fixed runs did a full rebuild and `verify` checks manifest, bhavcopy_lossless, overlap, calendar, table_sanity, identity, actions, adjusted_continuity. Baseline for comparison: close_outside_range 217, adjusted moves 403 flagged / 177 UNEXPLAINED / 232 securities with a break, gate KEPT 1,277 / REJECTED 15.

| Injected error | Manifest not fixed | Manifest fixed |
|---|---|---|
| RELIANCE close x1.015 on 2015-06-10 (one cell) | FAIL (raw_manifest) | **Not caught.** All PASS/WARN. Only trace: table_sanity `close_outside_range` 218 instead of 217 (still PASS) |
| RELIANCE close x10 on the same day | FAIL (raw_manifest) | **Not caught.** All PASS/WARN. Trace: UNEXPLAINED adjusted moves 179 instead of 177 (still WARN), `close_outside_range` 218 |
| WIPRO 2010-06-15 "Bonus 2:3" changed to "Bonus 3:2" in the held JSON | FAIL (raw_manifest) | **Not a FAIL, but neutralised.** The evidence gate REJECTED the flipped action (KEPT 1,277 to 1,276, REJECTED 15 to 16), so the wrong factor is not applied. Status stays WARN. |
| One raw bhavcopy zip deleted | FAIL (raw_manifest, missing=1) | not applicable (manifest row would still list it) |

Reading
- Raw inputs are protected only by the manifest. Anyone who can edit both a raw file and `manifest.csv` can change a price cell with no FAIL: `bhavcopy_lossless` compares the build with the same raw file, and no check compares prices with a second source. A one-day typo of x10 shows up only as two extra rows in a WARN count. This is a gap in the gate, expected for a single-source dataset, and the reason Stage 2.4 (third-party prices) matters.
- The gate's protection for corporate actions works as designed (a flipped ratio is rejected rather than applied), but the rejection is silent in the status: REJECTED was already non-zero, so the check stays WARN.
- Side effect of that rejection: a true bonus that the gate rejects leaves an unadjusted break in the series. WIPRO's real 2:3 bonus would be a 0.6 overnight move, inside the continuity check's [0.55, 1.8] band, so `adjusted_price_continuity` did not flag it (counts unchanged: 403 / 177 / 232).

| ID | Sev | Finding | Suggested fix |
|---|---|---|---|
| S2-7 | S2 | A single changed price cell, with the manifest updated, is not detected by any check. | Add a cross-source check (second price source for a sample, Stage 2.4) and/or make `check_table_sanity` FAIL when `close_outside_range` rises above a stored baseline for non-`T0` series. |
| S2-8 | S2 | `check_actions` stays WARN when one more action is REJECTED, so a newly rejected action is invisible in the status. Continuity bands [0.55, 1.8] cannot see a rejected 3:2 bonus (0.6). | Store a baseline for the gate counts and the rejected list; FAIL if a new rejection appears. Tighten continuity for liquid securities or check every rejected action against its adjusted series. |

Not run: Nifty 500 symbol-swap rerun (the earlier scratch layout is gone; needs `audit/mutate.py` adapted to the current root).

## Owner decisions of 2026-11-22 and their results

### S2-6 resolved in code: same symbol and same full equity ISIN across a gap joins (not yet built)

Rule 4 in `identity.link` (docstring updated): two adjacent segments of one symbol are joined when both traded in an equity series, they share a full ISIN whose security-type digits are `01` (equity share; debt is `07`/`08`, funds are `INF`), and that ISIN is seen under no other symbol inside the gap. A join that would overlap days is refused by `try_join` as before. Log source `symbol_isin`. Tests: `tests/test_identity.py` (5 new, 89 tests pass in total).

Pre-check (`audit/stage3_join_check.py`, `audit/stage3_join_effect.py`; build files only, nothing written to `data/build`):

| Check | Result |
|---|---|
| Adjacent same-symbol pairs sharing an equity-share ISIN | 56, none already one security |
| Exact symbol, full ISIN, no overlapping days, nothing in the gap (ISIN under another symbol, another issuer under the symbol, a different-issuer segment between) | 0 problems in all 56 |
| Joined by the rule (both segments in an equity series) | **46** (the same 46 as before), in 42 resulting securities (88 old ids absorbed); 8,182 securities become 8,136 |
| **Cases not joined (10)**: 3RDROCK (4 pairs), GIRRESORTS (2), MMNL (2), KAWIRES, MRO | Same symbol and same full ISIN, but a segment never traded in an equity series (`is_equity` false), so the existing equity-universe rule leaves them out. Same logic would join them; owner call. |
| Index membership intervals | **No change.** 14,851 interval rows all map; only 4 old ids are ever members (S00054, S00606, S02837, S02891, 31 interval rows), no index has two merged ids as members. Interval dates are untouched. |

Consequences to know before the rebuild
- **`sec_id` labels renumber.** Ids are assigned by order of first date, so removing 46 securities shifts 6,268 of the 8,182 existing labels (the first join shifts everything after it). The statement in the identity docstring that ids do not move holds only for appended days, not for a changed linking rule. Anything that stores a `sec_id` (A3) must be re-keyed; the ratchet baseline and coverage baseline are keyed by symbol and index, not `sec_id`, so they survive.
- The merged securities carry 306 action events (12 splits or bonuses). Their adjusted prices will now run across the gap and change; the corporate-action, continuity and ratchet checks must be re-read after the rebuild (a fall in the ratchet is WARN, a rise is FAIL).
- Not rebuilt: `data/build` still has the old identity.

### S2-7 and S2-8: ratchet check added (`check_ratchet_baseline`, 13th check)

`data/curated/ratchet_baseline.csv` stores the accepted ceiling: out-of-range closes 217, UNEXPLAINED adjusted moves 177 (by symbol and date), rejected share actions 15 (by symbol and ex-date). A new item or a higher count is **FAIL**, a fall is **WARN** (regenerate with `verify.write_ratchet_baseline()` and commit). A missing baseline or a missing `build/adjustment_gaps.csv` is FAIL. Tests: 3 new in `tests/test_verify.py`, including one-in-one-out swap.

**Plainly: a price edit that keeps the manifest consistent is caught only if it creates a new flag (the ratchet) or disagrees with an independent price source (below). A small edit of one cell that creates no flag, such as the +1.5% in the Stage 7 test, would raise `close_outside_range` only when it pushes the close beyond the day's range; otherwise nothing in the repo detects it. Only an independent price source finds that.**

### Stage 2.4: closing prices against a second public source

Source: Yahoo Finance public chart endpoint, NSE tickers (`SYMBOL.NS`), one request per symbol, 3 seconds apart, 40 requests, saved in the scratchpad (not `data/raw`). Script `audit/stage24_prices.py`, seed 20261122. Yahoo's close is split-adjusted, so for each stock only dates after its last split, bonus or consolidation in the project's events were compared with the raw NSE `EQ` close; 20 seeded dates per stock, 2015 onward, 40 large caps (the Nifty 50 names with a long history). Tolerance 0.5%.

| Result | Count |
|---|---|
| Comparisons | 800 |
| Within 0.5% | 735 (the differences are about 1e-6 percent, i.e. rounding) |
| No Yahoo row | 35: 33 after Yahoo's last day (2026-09-21), and two weekend special sessions (ONGC 2024-01-20, KOTAKBANK 2026-02-01) that Yahoo does not list |
| Outside 0.5% | 30, all in three stocks and **all explained**: each is one constant factor on every date before a single feed event, which Yahoo adjusts for and NSE's raw close does not |

The 30 misses: ITC -3.71% on 17 dates before the 2025-01-06 demerger (feed: SCHEME "Demerger"; the raw close drops 8.1% that day); GRASIM -22.85% on 2 dates before the 2017-07-19 scheme of arrangement (feed: SCHEME; raw close drops 19.7%); BHARTIARTL -9.87% on 5 dates before the 2019-04-23 rights issue and -1.84% on 6 dates between it and the 2021-09-27 rights issue (feed: RIGHTS 19:67 and 1:14). The attribution to demerger and rights adjustments is mine from the event dates and the price drops, not from Yahoo documentation. Raw NSE closes are the right values here.

Limits: one source, one provider's feed; 40 stocks of the Nifty 50; no dates before 2015 or on or before a stock's last share action (those need adjusted-price comparison, Stage 4).

### Nifty 500 symbol swap (Stage 7, rerun with a fresh scratch layout)

`audit/mutate.py` now takes the repo as baseline and a scratch folder. Baseline run: both checks PASS, no coverage change. Swap Nifty 500 inclusion `MAXHEALTH` (2021-03-31) to `ASIANPAINT`: **`check_membership` FAIL, 465 violations**, and verified coverage drops (Nifty 500 -2,615 days, Midsmallcap 400 -2,840, Smallcap 250 -1,643). Caught both ways.

### Stage 6.4b: archived NSE constituent lists vs the build, 2026-11-22

Source: 157 distinct Internet Archive captures of NSE's own constituent CSVs (`audit/stage64b_archive.py`; held in the scratchpad pending the owner's approval to save them in `data/raw/constituents_archive/`). Compared as symbol sets (ISIN match for renamed tickers; DUMMY rows ignored) with `index_members(index, capture date)`.

**Coverage of the test.** Captures start 2016-03 (Nifty 50), 2017-2019 (most indices) and 2010 (Midcap 50 only). **Membership before about 2016, and the workbook-only history 2007-2016, cannot be tested with this source.** 150 captures could be compared; 6 fell in unverified windows (refused by the API) and 1 had an unparseable header.

**Result.** 141 exact matches; 9 differences after the fix below (10 before):
- **S2-9 (fixed): Tata Motors DVR in derived indices.** The build carried TATAMTRDVR in Nifty MidSmallcap 400 and Smallcap 250 from 2020-06-26 to 2023-09-28 (DIFF of Nifty 500 and Nifty 100 / LargeMidcap 250 left it in because the DVR was only in the parent). NSE's lists on 2023-08-12 (MidSmallcap 400: 400 rows, no DVR) and 2023-08-08 (Midcap 150: 150 rows, no DVR) show it was in neither, hence not in Smallcap 250. Fix: `build_composites` removes the named dual-class security from DIFF composites and makes no size allowance for it; unit test added. Rebuild: coverage days unchanged for every index; MidSmallcap 400 now matches the archive.
- **Nifty Bank 2024-09-28** (CANBK in the archive, BANDHANBNK in the build): NSE published the list before the 2024-09-30 effective date. Publication lag, not an error.
- **Nifty 500, LargeMidcap 250, Midcap 150, Smallcap 250 on 2026-10-09..25** (REITs BAGMANE, BIRET, EMBASSY in the build, absent from the archived CSVs): the build follows `ind_prs10082026.pdf` (effective 2026-09-30); NSE's 2026-11-15 list contains the REITs. Read as NSE's CSV lagging the release; not provable from held data. Open note.

### Stage 6.4c: archived old-format NSE lists (2007-2015) vs the build, 2026-11-22

Source: 93 further Internet Archive captures of NSE's older constituent files (`ind_niftylist.csv`, `ind_jrniftylist.csv`, `ind_cnx100list.csv`, `ind_cnx200list.csv`, `ind_cnx500list.csv`, `ind_cnxbanklist.csv` and others; `audit/stage64c_archive_old.py`; held in the scratchpad pending the owner's approval to save them in `data/raw/`). Same method as 6.4b.

**Result: 66 comparable captures, 66 exact matches, 0 differences**, dated 2007-04-30 and 2010-01 to 2015-11 (Nifty 50: 10 captures, Next 50: 9, Nifty 100: 10, Nifty 200 and 500: 3 each, Bank 5, Pharma 6, FMCG 4, Realty 4, Metal 3, Midcap 50: 6, Midcap 100: 2, PSU Bank 1). 27 captures were refused by the API because the build does not claim them (before the 2007-01-01 floor, or before the index's verified window, e.g. Nifty IT before 2015-05, Media before 2020).

**Combined with 6.4b: 207 of 216 comparable captures match exactly across 2007-2026; the 9 differences are the explained ones above.** This is an independent confirmation of the workbook-based history (`IndexInclExcl.xls`) for the indices and dates listed. **Thin spots:** only one capture between 2007-05 and 2009-12 (Nifty 50, 2007-04-30), so 2007-2009 membership rests mostly on the workbook plus the size checks; no captures for Nifty 500 before 2014 or Nifty 200 before 2014.

## Stage 4 (2026-11-22, session 3): adjusted prices, factors and dividend entries

Scripts: `audit/stage4_factors.py`, `audit/stage4_missed.py`, `audit/stage4_dividends.py` (own parser, no project parsing code; seed 20261122).

**4.1 Factors, 60 securities (15 each with bonus, split, rights, scheme events in the feed).** 92 events compared by effective day and factor: 92 match. Adjusted-price factor series over the whole history: 60 of 60 identical (max deviation 0). First run showed 4 differences, all gaps in the auditor's parser (`Fv Split Rs.10/- To Re.1/`, bonus of NCRPS, bonus plus split); the project was right in each. Breaks in NSE's own prev_close/close (ratio outside 0.7-1.43) with no adjustment nearby: 18 in the sample; 2 on action days already flagged, the rest are real one-day moves, series switches (BE relist) or base-price resets (IGL 2012-04-10 is a real crash); none is a missed share action. Not covered: the third-party adjusted-price comparison (4.2 of the plan), review of the 15 rejected actions / 108 waivers / 177 unexplained moves (4.3), pre-2007 refusal (4.4).

**Dividend entries (used by `total_return`)**, own parse of all 43,816 feed records vs the project's events:

| ID | Sev | Finding | Fix |
|---|---|---|---|
| S1-4a | S1 | Rights premium or issue price was summed into the dividend in the same subject: TRENT 2007 Rs 500 (true 7.0), GULFOILCOR 2010 Rs 31.8 (1.8), KESORAMIND 2013 Rs 56 (1.0), HATSUN 2018 Rs 557 (3.0). Each multiplied all earlier `total_return` prices by 0.23-0.73. (HINDOILEXP 2006 same fault, before the coverage start.) | Rights clause removed before reading dividend rupees. |
| S2-4b | S2 | Rights written `Rhs` / `Rgts` not recognised (HINDALCO 2008 rights 3:7 never applied). | Abbreviations added; 2 rights added to the build. |
| S2-4c | S2 | Glued amounts (`Div-Re0.80`, `Rs7.5`, `Rs -3.60`) left UNPARSED: about 91 dividends from 2007 (77 in 2007-2009). | Parsed. `Rs .50` stays unparsed (ambiguous). |
| S2-4d | S2 | Trust/REIT distributions with no headline total (`Interest Payment Rs 2.25 / Return Of Capital Re 0.80`) used only the first figure (about 17 rows). | Headline total if stated, else the sum of parts. |
| S2-4e | S2 | `Of Rs. 10/- Each` face value added to the dividend (TULSYAN 2012). | Phrase removed. |
| S2-4f | S2 | A dividend was placed on the first day the security traded in an equity series, even years later: about 80 rows more than 7 days after the ex-date (InvIT/REIT units: IRBINVIT 2017-2019 on 2026-09-30, EMBASSY, INDIGRID, NXST...). | Not applied if the first trading day is more than 7 days after the ex-date; status `NO_TRADING_NEAR`. |

Remaining differences between the two parsers (about 269 amount differences; reviewed in Stage 4 remainder below) are 248 InvIT/REIT rows where the auditor's parser summed the components of a stated headline total (project correct) plus unreviewed rows. Ex-day check: of 2,168 dividends with yield above 3% and no share action that day, 92% moved within 5 points of the expected drop (median excess return +0.15%). Unresolved: GENESYS 2019 `Rs.0125` (kept out, dividend above price), SBT 2009 130% (dropped, above price), 13 yields above 25% reviewed by hand (AURUM Rs 974 explains the 985 to 12 price drop; the others are special dividends in the subject text).

Effect of the rebuild: 26,914 to 26,993 adjustment rows (+77 dividends, +2 rights), 16 multipliers changed. 6 new unit tests; 96 tests pass.

## Stage 4 remainder (2026-11-23, session 4): third-party prices, the exception lists, dividend differences

Scripts: the Yahoo downloads and comparisons were run from the scratchpad (not added to `audit/`); the review table is `audit/stage43_review.csv` (225 rows: the 15 rejected actions plus 2 wrongly applied ones, 31 waivers, all 177 unexplained moves). Source: Yahoo public chart endpoint (`query1.finance.yahoo.com/v8/finance/chart/<SYM>.NS`), plain GETs 3 s apart, 83 JSON files kept in the scratchpad, nothing written to `data/raw`.

**4.2 Adjusted prices against a second source (30 stocks, every common day 2007-01-02..2026-11-19, tolerance 0.5%).** `api.prices(adjust_mode="splits")` `adj_close` against Yahoo's split-adjusted close, 4,858 common days per stock (Nestle 4,120, Bajaj Auto 4,513: the demerged entity trades from 2008). Infosys (bonus 2014, 2015, 2018), HDFC Bank (split 2019, bonus 2025), Reliance bonus 2017, TCS, Wipro, HCL, Asian Paints, SBI, Titan, Bajaj Finance and others: **after the BHARTIARTL fix below, 26 of 30 stocks have 1 to 16 days outside 0.5% and no stretch longer than 7 days; the other four have one long stretch each, explained below.** Every miss is one of:

| Miss | Days | Cause |
|---|---|---|
| One-day differences on 2025-03-18 in 28 of 30 stocks (-0.5% to -3.1%) | 28 | Yahoo's bar for that day differs from NSE's close in every stock at once, then reverts. Not an adjustment break; cause not determined (NSE's own next-day `prev_close` equals the held close) |
| One-day differences on 2007-12-18, 2008-01-18/30, 2008-03-12, 2008-11-20 and a few more (0.5% to 7.7%) | 67 | Revert the next day, no corporate action: closing-price definition on volatile days. Not an adjustment break |
| DABUR 2007-01-25 (-50%) | 1 | Bonus ex-date: Yahoo steps one day away from NSE's ex-date. Single day |
| **BHARTIARTL 2007-01-02..2009-07-23, -50%** | 627 | **Project error, fixed.** The feed text `Agm/Div-Rs.2/Fv Rs10tors5` is a face-value split 10 to 5 with the word "to" glued to the figures; the parser read it as a dividend of Rs 12 |
| RELIANCE 2007-01-02..2023-07-19 (-7.7%), ITC 2007-01-02..2025-01-03 (-3.7%), SUNPHARMA 2007-01-02..2007-04-20 (-7.1%) | 4,076 / 4,435 / 74 | Demergers (Jio Financial 2023-07-20, ITC Hotels 2025-01-06, the 2007-04-23 scheme). Yahoo adjusts for them; the feed gives no ratio and the project does not estimate one: documented break (waiver), as designed |
| TATASTEEL 2007-01-02..2007-10-26 (-21.7%) | 205 | The 2007 rights issue `Right-Eq1:5 & 9ccps:10eq` has no issue price and a CCPS leg: UNPARSED, not applied. Documented gap |

Corporate-action factors against Yahoo's split events (50 dates in these 30 stocks since 2007): **47 match exactly**. The other three are same-day bonus-plus-split combinations (Bajaj Finance 2016 and 2025, Titan 2011: the project's 10, 10 and 20 equal bonus x split, Yahoo lists one leg; the close comparison agrees with the project on every day). BHARTIARTL 2009 was the fourth difference before the fix. Bajaj Auto 2008: the demerger created a new security (new ISIN), so there is no pre-demerger series to adjust, and both sources start on the same day.

**Parser defects found (all fixed; 19 new tests, 116 pass):**

| ID | Sev | Finding | Fix |
|---|---|---|---|
| S1-4g | S1 | Face-value splits with "to" glued to the figures (`Fv Rs10tors5`, `Spl-Rs10tors2`, `Fv Rs10tors2`, `Fv Sp Rs10to 4`, `Spl Rs10-Rs2`) were read as a dividend of the face value: BHARTIARTL 2009, ERAINFRA 2008, COREEDUTEC 2007 (SHREEKRPET 2000 and CASTEXTECH 2005 are before the data start). The 2x to 5x price step stayed in the adjusted series and a fake Rs 10 to 12 dividend lowered `total_return`. | Glued `to`, `fv sp` and the hyphen form recognised; 3 splits added (gate: kept); 3 false dividends gone |
| S2-4h | S2 | **A bonus of debentures, NCRPS or preference shares was typed as a share bonus** (`Bonus Deb1:1`, `Bonus Ncrps 1:10`, `Bonus Preference Shares 21:1`). 9 were rejected by the price gate (ASTRAZEN, BRITANNIA, DRREDDY, COROMANDEL, ZEEL, NTPC, TVSMOTOR, SIYSIL, TVSHLTD 2026). **2 were too small for the gate and were applied: RADIOCITY 2023-01-13 factor 1.10 and TVSHLTD 2023-03-24 factor 1.0086**, shifting every earlier adjusted price of those two stocks by 10% and 0.9%. | Recorded as SCHEME (not quantified, no share factor); rejected 15 to 6; 2 wrong factors removed |
| S3-4i | S3 | A dividend written next to a face-value split (`Fv Spl-Rs10to2/Div-Rs2.50`) was dropped (12 records: EMAMILTD, KCP, UNICHEMLAB, ALLCARGO, KRBL and others). A percentage dividend next to a split is still not read (of the old or the new face value?). | Rupee dividends read after cutting the split phrase out; +12 dividends |
| S3-4j | S3 | `Dividend Rs:- 5.50 Per Share` (AARTIDRUGS, DEEPAKFERT, SINTEX, BRIGADE, ALKYLAMINE 2014) and `Div.@1.20` (ELNET 2011) were UNPARSED. | Parsed; +6 dividends |
| S3-4k | S3 | `Rs.0125` (GENESYS 2019) was read as Rs 125 and then dropped as above the price. | A figure of 3 or more digits with a leading zero and no point is UNPARSED (0.125 or 1.25 cannot be known from the text) |

Effect of the rebuild: adjustment rows 26,993 to 27,010; gate 1,281 kept / 112 untestable / 6 rejected (was 1,277 / 114 / 15); ON_ACTION_DAY breaks 76 to 73; full `verify` 13/13 without FAIL, with `ratchet_baseline` WARN (rejected 15 to 6: a deliberate improvement) and PASS after the baseline was regenerated.

**4.3 Review of the exception lists (225 rows in `audit/stage43_review.csv`).**

*The 15 rejected share actions (all reviewed).* 9 are not share actions (debentures, NCRPS, preference shares): fixed above. 6 stay rejected:
- GULFPETRO 2013-07-09 (bonus 23:19) and AHLEAST 2022-10-06 (bonus 1:2) are **real actions**: Yahoo's split on the same day equals the feed (42:19 and 3:2). The gate looks at one day: GULFPETRO fell only 17.9% on the ex-date (price band) and the rest of the 2.2x over the following sessions; the AHLEAST day also carries a waived demerger (observed 1.89 = 1.5 x 1.26). Their adjusted series keep a flagged break. Not applied; decision A18.
- SUNTV 2007-07-23: the feed `Agm/Spl/Bon-1:1/Div-20%` is a bonus 1:1 plus a split whose figure is not stated; observed 3.82 is about 2 x 2 (Yahoo lists one 2:1). Documented gap.
- LAKSHVILAS 2006 (bonus plus rights, before 2007), DVL 2021 (observed 0.99, no price effect, no Yahoo split, instrument not named), KWALITY 2010 (-14.9% on 5x volume, factor 1.714 unconfirmed, no Yahoo data): documented gaps, cause not proven.
No rejected action is a WIPRO-style bonus hidden inside the continuity band: the gate accepts +-25% of the stated factor, and every action of factor 1.5 or more that fails it is in this list.

*The 108 waivers (31 reviewed against a second source).* All 108 are `UNQUANTIFIED_SCHEME` (101) or `UNQUANTIFIED_TEXT` (7), each with the feed text and the observed ratio. Of the 31 whose stocks Yahoo covers (after 2007-02): **15 are adjusted by Yahoo** (ADANIENT 2018, ARVIND 2018, DCM 2019, GFLLIMITED 2019 and 2021, KESORAMIND 2025, SIEMENS 2025, TATACHEM 2020, THOMASCOOK 2019, TATACOMM 2019, IIFL 2019, TRIVENI 2011, EDELWEISS 2023, NMDC 2022, AHLEAST 2022): an independent sign that a corporate event happened, with a size the project does not adopt. 16 show the same drop in Yahoo (SANOFI, MASTEK, RAYMOND twice, SCI, VEDL, SKFINDIA, STAR, STLTECH, TMPV, NIITLTD, TRIVENI 2026, ALLCARGO twice, ABFRL, QUESS): the event rests on the feed text and the drop is real in both sources. No waiver contradicts its evidence.

*The 177 unexplained overnight moves (all classified).*

| Class | Count | Evidence |
|---|---|---|
| SME platform (series SM/ST), ratios 0.21 to 0.53 | 97 | The held feed has **0 records for SM/ST securities**, so no SME split or bonus can appear. Yahoo confirms 11 of 11 checked (AILIMITED, KSOLVES x2, MCL x3, REMUS x2, PRITI, DUGLOBAL x2: splits 2:1 to 5:1 on the same day, matching the ratio) |
| ETF and index-fund unit splits, ratios 0.010 to 0.12 | 60 | No feed record; NSE's own open and prev_close give the unit ratio (NIFTYBEES 0.101, BANKBEES 0.100, GOLDBEES 0.010). Yahoo confirms NIFTYBEES 10:1, BANKBEES 10:1 and GOLDBEES 100:1 on 2019-12-19 |
| Real price moves, no corporate action | 12 | 63MOONS 2013, CCAVENUE 2018 (-71%), COREEDUTEC x3, GTL 2011, HUBTOWN 2009, JETAIRWAYS 2019 (+90%), PURVA and UNITECH 2008-10-24, SATYAMCOMP 2009-01-07, YESBANK 2020-03-06: volume 3x to 2,000x and no feed record; the cause is not in the held data |
| After the feed ends (2026-10-16) | 8 | CCAVENUE 2026-10-19 is a 10:1 consolidation (prev_close 138.30 against a close of 13.83 on 10-12; adjusted ratio 9.4), AZADIND 2026-10-23, KMEW 2026-11-06, PASHUPATI 2026-11-13, CONCORDBIO 2026-11-04 and three more: actions after the feed snapshot. A feed refresh (owner download) closes them |

The unexplained list held no missed parser case; the three glued splits were not in it because each sat on a day with a dividend (class ON_ACTION_DAY).

**4.3c Dividend differences between the auditor's parser and the project (reviewed).** Of 269 amount differences, 255 are the project being right (InvIT and REIT headline totals; `Int + Spl` sums such as NESTLEIND 2019 Rs 23 + Rs 180, GESHIP, VISAKAIND, SUDARSCHEM; `Of Rs 10/- Each` face values; TRENT and HINDOILEXP fixed in A15). The other 14 were the glued splits above (project wrong, fixed). 49 records exist only in the project: a dividend printed next to a bonus, which the auditor's script skipped (TCS 2009 and 2018, INFY 2015, ICICIBANK 2017 are right). 205 exist only in the auditor's: most have no amount in the text (`Interim Dividend`, STAN, NOT_EQUITY); the others were fixed above. Left unparsed on purpose: `Rs .50` (ELGIEQUIP, unit unclear), `R.5/-` (SHREECEM), `Fin 1.40+Spl 0.40` with no currency sign (RATNAMANI, RENUKA), `S 5/-` (DECCANCE), `R E 1` (TBZ), `Rs Per 0.50 Share` (AGIIL).
- **GENESYS 2019 `Rs.0125`: decided, left out** (now UNPARSED). The previous year reads `Rs.0.125`, so 0.125 is likely but 1.25 cannot be excluded and no source says which; the effect is under 1% of the price either way.
- **SBT 2009 `130%`: decided, correct to drop.** State Bank of Travancore's first trading day was 2009-04-24 (series BT), two days after the ex-date 2009-04-22: there is no earlier close to adjust. The 2007 and 2008 dividends precede the listing (NO_SECURITY).

**A5.** `membership.build_anchored` has three synthetic tests (healthy index: one VERIFIED row and no PARTIAL; an index that held one security too many for five days: PARTIAL with the right day count; a member that never traded within the window: PARTIAL by the trading rule). No refactor was needed: `root` and `paths.CURATED` are injectable.

## Stage 4 follow-up (2026-11-23, later): feed update, ETF unit splits, SME warning, backfill, methodology check

**Feed update (A19).** The owner's download `CF-CA-equities-01-01-2004-to-23-11-2026.csv` (5,399,901 bytes, NSE Corporate Actions page, saved 2026-11-23) is in `data/raw/corporate_actions/` with a manifest row. `actions.load_supplement` adds only the rows dated after the held feed's last ex-date (2026-10-16) that are not already in it: 221 records (JSWDULUX, AZADIND, KMEW, GNRL, BNAGROCHEM splits, CONCORDBIO and PASHUPATI bonuses and others). The held feed stays the base. The same `update` run added the bhavcopy and index files for 2026-11-20 (5,685 trading days, 8,137 securities).

**ETF unit splits (A18, owner decision).** `data/curated/actions_price_evidenced.csv` holds 55 rows: a factor and a cited NSE bhavcopy file for each ETF unit sub-division that the feed does not carry (NIFTYBEES 10, BANKBEES 10, GOLDBEES 100, and 52 more, 5 and 10 and 50 and 100 to 1). Rule: a factor is accepted only if NSE's own prev_close/open or prev_close/close is within 5% of a round factor (2, 4, 5, 10, 20, 25, 50, 100, 1000) and the feed has no share action within 10 days. Yahoo confirmed NIFTYBEES, BANKBEES and GOLDBEES (the rest are not on Yahoo). The price gate then tested all 55 against the price move: **55 of 55 KEPT** (gate 1,343 kept). Not added: SETFGOLD 2022-01-06 (ratio 1.0), UTINEXT50 (ratios 9.47 and 9.43), AXISNIFTY/NIFTYAXIS 2020-07-23 (8.58 and 8.33), UTISXN50/SNXT50BETA (8.73 and 8.33, exactly 0.1200 in the adjusted series), UTIBANKETF/BANKBETA (8.87 and 9.44): non-round ratios, left as flagged breaks. `check_curated_provenance` now reads this file (3,542 references, 0 missing).

**SME securities.** The feed has no SM/ST records, so 97 flagged breaks and an unknown number of silent ones remain in their adjusted prices. `api.prices(adjust_mode=...)` now adds `adj_reliable` (False for any security that ever traded in SM/ST) and raises a `DataQualityWarning`; `api.sme_securities()` lists them. Raw prices are unaffected.

**Index membership backfill (opt-in).** `api.index_members(index, date, backfill=True)` for dates from 2007-01-01 up to an index's first verified day returns the first verified list restricted to securities already trading on the date, with `membership_status='BACKFILLED_UNVERIFIED'` and `backfilled_from`, plus a warning. Dates inside or between verified windows, before 2007 and for indices with no verified window are refused. Bias: survivors only, outcomes known; stress tests, not clean out-of-sample.

**Result.** Full `verify` 13/13 without FAIL; unexplained adjusted moves 177 to 115, securities with documented breaks 230 to 169; ratchet and coverage baselines regenerated (deliberate: 62 fewer unexplained moves; 25 indices gained the 2026-11-20 day). The 115 remaining: 97 SME, 12 real price moves, CCAVENUE 2026-10-19 (a 10:1 consolidation that is in neither feed), 5 ETFs above.

**Index base dates and values against NSE's Nifty Indices methodology document (November 2026, 352 pages; the five Method_*.pdf files saved by the owner are the same document).** Compared with the first values in `index_values`: Nifty 50 base 1995-11-03 = 1000 (data: 1000.00 on 1995-11-03), Nifty Bank 2000-01-01 (data 1000.0), Nifty Auto 2004-01-01 (1000.0), Nifty 100 2003-01-01 (1000.0), Nifty Realty 2006-12-29 (1000.0). The broad indices' own sentences are not all in this document; their first data rows are Nifty Next 50 1996-11-04 (1000.0), Nifty 200 2004-01-01 (1000.0), Nifty 500 1995-01-01 (1000.0), Midcap 150 and Smallcap 250 2005-04-01 (1000.0): consistent with the published base value of 1000 on a base date, not independently confirmed for those five from this PDF. No mismatch found.

**`IndexInclExcl.xls` (C5), independent check.** (1) 5,971 of 6,413 workbook events (93%) dated 2007 to 2020 have the company named in a held NSE press release dated up to 150 days before the effective date (misses concentrate in 2007 to 2009, when about 20 releases a year are held); a weak test (a mention is not a direction). (2) Stronger: the build counts members on every trading day and requires the official index size (50, 100, 200, 500 ...) and the subset rules between indices; a wrong or missing workbook event breaks a count unless two errors cancel, and 40 windows verify with 0 contradictions; 207 of 216 archived NSE lists (2007 to 2026) and 66 of 66 old-format lists match the rebuilt membership exactly. Reading: content corroborated, origin still unknown.

**Methodology and point-in-time membership.** The methodology ranks by six-month average full (Nifty 500, 100, Midcap 150, Smallcap 250) or free-float market capitalisation with buffers, turnover, impact cost and F&O criteria. A rule-based reconstruction would need shares outstanding (and free float) per stock per date; the bhavcopy has none. It would also be a model, not NSE's membership.

## Market-activity data (2026-11-23)

`fetch.py` gained four sources fetched only on days with a bhavcopy (the session calendar): `delivery_mto` (5,685 files), `band_changes` (4,057), `sec_list` (1,707, from 2020-01), `fo_secban` (4,190), plus a daily save of the latest bulk and block deal files (2). 526 MB, all in the manifest (a manifest lock problem on the Drive-synced CSV crashed the first runs; rows are now queued and written in batches, 89 duplicate rows removed, 10 original rows untouched). `market.py` parses them (header variants handled, unknown layouts refused: 2 band-change files) and attaches each row to a security through the bhavcopy row of the same day, symbol and series. New check `market`: deliverable quantity above traded quantity 0, delivery percent differing from its own quantities 0, traded quantity differing from the bhavcopy volume on 6,598 of 9,211,334 rows (0.072%, source disagreements, e.g. EIDPARRY 2004-01-02: 218,026 in MTO against 23,276 in the bhavcopy). Unattached rows: delivery 230, band changes 1,222, security list 167,351 (securities that did not trade that day), F&O ban 0. Full verify 14/14 without FAIL.

Added later the same day: derivatives bhavcopy (`fo_bhav_legacy` 5,091 files to 2024-07-05, `fo_bhav_udiff` 591 files from 2024-07-05; 2.4 GB) and the table `fo_stocks` (stock futures or options present that day; 987,624 rows, 5,681 days, 50 to 267 stocks a day, 28 rows unattached). The manifest briefly held 19 repeated rows (a queued row and a reconcile both listed a file); `fetch.dedupe_manifest()` now removes them, byte-exact for every other line.

Added 2026-11-23: bulk deals (2004-01-04..2026-11-20, 23 annual windows, 245,962 rows), block deals (2005-11-17..2026-11-20, 22 annual windows, 13,375 rows), and short selling (2008-02-01..2026-11-20, 19 annual windows, 99,725 rows), downloaded via a real Chrome session from NSE's report page (1-year Custom windows, 5.5 s pauses, 0 blocks/challenges, 0 empty windows inside covered periods) and listed in `manifest.csv` (34,938 files total). Built into `data/build/market/deals.parquet` (359,062 deduplicated rows, 104 unattached, 0 skipped layouts). Extended `check_market`: `qty > 0` on 100.000% of rows (1 null `"-"` on `LIQUIDBEES` 2026-07-09), price within bhavcopy day low–high on 259,212/259,293 priced attached rows (99.969%). `api.deals()` enforces coverage; `caveats.py` updated (`DEALS_REVISED_BY_EXCHANGE` added). Full verify 14/14 without FAIL; 137 tests pass.

Added 2026-11-23: monthly NSE Clearing Security Category & Impact Cost (`C_CATG_<MMM><YYYY>.T01` on `nsearchives.nseindia.com/content/nsccl/`; NSE does not publish a daily per-security impact-cost file). 47 monthly files fetched (16.12 MB; continuous 2023-10..2026-11 plus 2019-03, 2021-01..06, 2023-05..06; 34,985 manifest files total) and built into `data/build/market/impact_cost.parquet` (532,386 rows, 172,282 with numeric 6-month rolling mean impact cost % for ₹1 lakh order, 250,587 unattached mostly non-trading debt/SG series, 0 negative, 0 >100%, range 0.00%–32.01%). Extended `check_market`, added `api.impact_cost()`, updated `caveats.py` (`IMPACT_COST` added, `DATA_NOT_IN_THE_BUILD` updated). Full verify 14/14 without FAIL; 140 tests pass.

## Gate overrides (2026-11-23)

`data/curated/gate_overrides.csv` (symbol, ex-date, share factor, reason, source) keeps a share action the one-day price test rejects, only when the feed states the ratio and a second source agrees; it applies to a feed event of the same symbol, ex-date and factor only. Two rows: GULFPETRO 2013-07-09 (23:19) and AHLEAST 2022-10-06 (1:2). Gate: 1,343 kept, 112 untestable, 4 rejected, 2 overridden. Both stay logged and counted in `verify` (`kept by a curated override=1`; AHLEAST's day is also covered by its demerger waiver). Yahoo check after the change: GULFPETRO median difference to Yahoo 0.0% on both sides of the event (was a factor 2.21 off before it); AHLEAST 0.0% after, and -26% before, which is the same-day demerger the feed gives no ratio for.

## Stage 5 (2026-11-22): index values

Script: `audit/stage5_index.py`, `audit/stage52_ew.py`.

- Overlap of the daily files and the history API: 279,365 (index, day) rows over 170 indices; |difference| above 0.01%: 971, above 0.1%: 361 in 14 indices (178 above 1%). Nifty 100 Low Vol 30: 141 days, 2016-10-06 to 2017-05-03, mean -3.9%. Others: bond and G-Sec indices (about 200 days), Nifty 50 Dividend Points 32, High Beta 50 14, Arbitrage 12. No duplicate keys in either source. A conflict is not a one-day shift (2 days equal the previous day's value, 6 the next).
- Which source is right, tested without NSE factsheets: on the conflict windows the history series follows its parent index better. Low Vol 30 vs Nifty 100 daily return correlation 0.95 (history) against 0.80 (daily file); High Beta 50 vs Nifty 50 0.72 against 0.32. This supports the existing advice (`source="history"` or `mask_conflicts=True`). It is evidence, not a proof; no factsheet is held.
- Equal-weight check (NSE prev_close to close of the members held that day, no adjustment): Nifty 50, 1,641 sampled days, correlation 0.967 (below the plan's 0.97 line; by year 0.85 in 2019 to 0.99 in 2008); Nifty 100, 704 days, 0.962. Every sampled day had a price for every member. The shortfall is the cap weighting of the index against equal weights (largest gaps on days when HDFC Bank, Reliance or Infosys moved alone, e.g. 2022-07-28 index +1.7%, equal-weight -0.4%); a wrong member would show as a missing price, which did not happen. Not tested: base date and base value against NSE methodology (no document held).

## Stage 8 (2026-11-22): point-in-time and API

Scripts: `audit/stage81_lookahead.py`, `audit/stage82_contract.py` (seed 20261122).

- **8.1 Look-ahead.** For 10 seeded dates D between 2009 and 2024, events, attachment, multipliers and the evidence gate were rebuilt from prices dated <= D and feed records with ex-date <= D only, and compared with the full build's adjustments with effective day <= D (3,969 to 23,468 rows per date): 0 missing, 0 extra, 0 different multipliers on all 10 dates. Limit: identity (`sec_id`, symbol segments) came from the full build, not truncated; the gate looks up to 5 sessions after an ex-date, which did not change any decision on these dates.
- **8.2 Refusals.** 74 indices, 40 seeded dates each (2,960 pairs): 664 served, 2,296 refused, 0 violations (nothing served outside a VERIFIED window, nothing refused inside one, every refusal names the reason). Adjusted prices before 2007-01-01 are refused; an unknown symbol raises.
- **S3-8a (fixed).** `prices('RELIANCE', Saturday, Sunday)` returned an empty frame silently. It now raises `CoverageError`; test added (`test_range_with_no_trading_day_is_an_error_not_an_empty_frame`).
- **S3-8b (documented).** `as_of=` limits which corporate actions are applied but does not remove price rows after `as_of`; README now says so.
- **8.3** The `build_anchored` unit test (A5) was not added: it needs injected paths (stays OPEN in A5).

## Stage 9 (2026-11-22): documentation honesty

Every count in README, CHECKPOINT and METHODOLOGY was compared with the build. Stale and corrected: securities 8,182 to 8,136 (equity 4,826 to 4,780, after the S2-6 joins); verified windows 45 to 40 (27 indices unchanged); securities with a documented break 231 to 232; indices verified over the whole span 5 to 6 (NIFTYPSUBANK added); CHECKPOINT tests 76 to 97, integrity checks 11 to 13, raw files 13,286 to 13,548, "NOT yet independently audited" changed to "audit in progress". Added to README: an audit-status section listing what was and was not checked, and every thin spot from HANDOFF (membership 2007-2009, Nifty 200/500 before 2014, `IndexInclExcl.xls`, dividends parsed from text, index conflicts, `as_of`, `sec_id` instability, missing weights and costs). Matches verified: 5,684 days, 9,968,593 rows, 238 indices, 43,816 feed records with no announcement dates, 1,061 index conflicts, 177/403 gap counts. Not checked by script: prose claims in SOURCES.md.

## Stage 1.1 (2026-11-22): re-download sample

Script: `audit/stage1_redownload.py` (seed 20261122; plain GETs, one at a time, 1.2 s apart, generic User-Agent; files to scratch, nothing written to `data/raw`). 329 files, 39.5 MB: 100 legacy bhavcopy days and 50 UDiFF days (first and last three of each era always included), 20 daily index files, all 59 constituent CSVs, 100 press PDFs, each compared with the SHA-256 in `manifest.csv`.

| Group | Files | Identical SHA-256 |
|---|---|---|
| Bhavcopy legacy | 100 | 99 (see below) |
| Bhavcopy UDiFF | 50 | 49 (one network error; retried, identical) |
| Daily index files | 20 | 20 |
| Constituent CSVs (current lists, fetched 2026-11-15) | 59 | 59 |
| Press PDFs | 100 | 100 |

The one real difference: `cm22DEC2023bhav.csv.zip` has the same size and the same CSV inside (byte-equal), but the zip member timestamp differs by 6 seconds (17:32:18 now, 17:32:24 held), so the zip hash differs. The data is unchanged; the held copy remains the evidence. Limits: a sample (329 of 13,548 files); constituent lists are live files and matched the held copies a week later by luck of no index change, which says nothing about earlier dates.

## Spot check of 30 membership dates (2026-11-24)

Script `audit/spot30.py`, result `audit/spot30_result.csv` (seed 20261124).

- **Draw.** 207 held NSE constituent captures (data/raw/constituents_archive) dated 2010-01-04 or later fall inside a verified window of their index; 30 were drawn at random, at most 4 per index. Indices covered: Nifty 50, Next 50, 100, 200, 500, Bank, FMCG, IT, Metal, Midcap 50, Midcap 150, MidSmallcap 400, Pharma, PSU Bank, Realty, Smallcap 100.
- **Result: 30 of 30 match exactly** (symbol sets equal, a renamed symbol counted as equal on the same ISIN), build member count equals the NSE file's count each time (e.g. 501 for Nifty 500 with the HEG dummy, 101 for Nifty 100 on 2017-11-02).
- **Limits.** The captures are 2013-2026 (none in the draw before 2013; the held captures before that are few and were used in the earlier 6.4b/6.4c comparison, so this is a fresh draw of the same evidence family, not a new source). Boundary days (the day of a change) were not targeted.
- **Second source (Nifty 50, 2010-2026).** Wikipedia's index-changes table (revision 1386392186, fetched by a subagent; the flattened rowspan text cannot tell OUT from IN, and its date blocks are shifted against each other) was compared by company: 76 companies, 100 mentions against 102 build change events. After allowing for the shifted blocks every company agrees except Jaiprakash Associates and Tata Communications, which Wikipedia lists in an 8 April 2010 block; the NSE capture of 2010-01-02 (`ind_niftylist_20100102023400.csv`) shows Jaiprakash already a member and Tata Communications not, as in the build. The September 2025 changes (Hero MotoCorp and IndusInd out, IndiGo and Max Healthcare in) were checked against the held NSE press release `ind_prs22082025.pdf`: effective 2025-09-30, as built. Wikipedia is a secondary compilation, so this confirms the dates and names only where it agrees with NSE's own files.
- **Not covered.** Nifty 100 and Nifty 500 before 2013 (no captures), the 2010-2012 boundaries of the sector indices, and index weights.
