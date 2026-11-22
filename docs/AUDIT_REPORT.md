# Audit report (interim): Stage 0 and Stage 7

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

Not yet tested in Stage 7: bhavcopy cell corruption, corporate-action ratio flip, raw-file deletion, the Nifty 500 symbol swap. Stages 1 to 6, 8 and 9 are not started.
