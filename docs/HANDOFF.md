# Handoff for a new session (2026-11-22)

Project: Nifty Universe (`nseuniverse`), a deterministic, source-traceable NSE point-in-time dataset. Read first: `CHECKPOINT.md`, `docs/AUDIT_PLAN.md`, `docs/AUDIT_REPORT.md`, `docs/OPEN_ISSUES.md`.

## State
- All work is committed locally (latest `eab8977`); **nothing is pushed**. Untracked and the owner's: `999 dump/`, `Project Requirement.docx`, `requirements-lock.txt`, `nseuniverse.egg-info/`.
- 78 tests pass. Run the CLI as `python -m nseuniverse.cli build|verify [--only NAME]` (no `__main__`). Full `verify` (13 checks) takes about 11 min; `build` several.
- 2026-11-22 later: S2-6 identity join rule and `check_ratchet_baseline` are in code and committed but **data/build is NOT rebuilt** (needs a rebuild; sec_ids will renumber). Stage 2.4 (Yahoo, 800 comparisons, 30 explained misses) and the Nifty 500 swap rerun are done.
- Audit done (also, 2026-11-22): Stage 2 (except 2.4 third-party prices), Stage 3, raw-layer mutation tests (cell, ratio flip, deletion). Scripts `audit/stage2_*.py`, `audit/stage3_identity.py`, `audit/mutate_raw.py`; findings S2-6..S2-8 in AUDIT_REPORT and A13 in OPEN_ISSUES.
- Audit done: Stage 0 (reproducibility), 7 (mutation test of the gate), 6.1-6.3/6.7/6.8 (membership), Stage 1 for `symbolchange.csv` and `EQUITY_L.csv`.
- Audit fixes done: manifest covers held files; `check_coverage_baseline` added (`data/curated/coverage_baseline.csv`; regenerate with `verify.write_coverage_baseline()` only for a deliberate change); `press.extract_text`; docs honesty fixes; LargeMidcap 250 floor set to 2016-04-01 (Midcap 150 lost the same window).

## Working rules (owner)
Nothing is estimated. Every curated row cites a file in `data/raw/`. Ask before pushing, deleting, or saving downloads into `data/raw/` (state name, source, size). Downloads for audit comparison go to the scratchpad, not `data/raw/`. Do not bypass NSE bot protection (scripted calls to the corporate-actions API were refused; stop there). Add a unit test for every new code path.

## Pending
1. **Owner decisions:** A12 dead aliases (BLACKBOX, PUDUMJEE: delete + rebuild or keep); A1 push; A6/A7 untracked files; A2 spot-check of inferred aliases.
2. **Owner action:** download a fresh NSE corporate-actions file by hand (the held JSON is unchecked, A11); optionally save missing press releases (B7, B12).
3. **Audit not started:** Stage 1 re-download sample (150 bhavcopy, 20 index, 59 constituent, 100 press), Stages 2 (bhavcopy/calendar), 3 (identity), 4 (adjusted prices), 5 (index values), 6.4 (blind sample vs factsheets, needs owner files), 6.5 (press completeness), 8 (PIT/API), 9 (docs honesty pass).
4. Mutation tests: all in the original list are done.
5. Open data issues: B9 (demerger dummies in other indices), B16a, C1-C5.
6. Scratch tools: `audit/` scripts in the repo; scratchpad outputs are temporary.

## Update 2026-11-22 (later)
- Owner decisions: data start is **2007-01-01** (API must refuse unverified index/date); dead aliases deleted (A12 done, commit 16538f7); inferred aliases reviewed for 2007+ (A2 done, none rejected); LargeMidcap 250 floor 2016-04-01 (A10 done); `999 dump/` and the other untracked files stay until the end; do not touch them.
- Full `verify` after these changes: 12/12 no FAIL (run before the alias deletion; membership, curated_provenance and coverage_baseline re-run after it, PASS).
- 12+ commits ahead of origin; push only on the owner's explicit yes.
- Waiting on the owner: fresh corporate-actions download (to scratch, never `data/raw/` without asking) and optional factsheets for the blind sample (6.4).
