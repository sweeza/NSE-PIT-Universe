# Open issues tracker

Last updated: 2026-11-22. Status values: **OPEN** (work possible), **DECISION** (needs the project owner),
**BLOCKED** (cannot be done under the project rules with the evidence held), **DONE** (kept for the record).
Add a row when something is found; change its status, do not delete it.

## A. Pending now

| ID | Status | Item | Next step |
|----|--------|------|-----------|
| A9 | OPEN | Audit findings fixed 2026-11-22: five held files added to the manifest and now scanned (S2-1); `check_coverage_baseline` added with `data/curated/coverage_baseline.csv` (S3-1); `press.extract_text` added (S3-2). To accept a deliberate coverage change run `verify.write_coverage_baseline()` and commit it. | None. |
| A10 | DONE | **S2-4**: Nifty LargeMidcap 250 was VERIFIED 2008-03-14..2015-09-24 although the index launched 2016-04-01 (Nifty 100 was not a subset of it on those days). Owner decision 2026-11-22: mark UNVERIFIED. `FLOORS["NIFTYLARGEMIDCAP250"]` is now 2016-04-01; coverage baseline regenerated as a deliberate reduction. | None. |
| A11 | DONE | **S2-2/S2-5**: `symbolchange.csv`, `EQUITY_L.csv` and `raw_corporate_actions_1995_2026.json` were compared with fresh NSE copies on 2026-11-22: no altered or missing historical rows (differences are renames and post-snapshot events; see `docs/AUDIT_REPORT.md`). `IndexInclExcl.xls` has no live NSE source and stays unchecked (C5). | None. |
| A12 | DONE | **S3-4**: the two dead aliases (AGC Networks -> BLACKBOX, Pudumjee -> PUDUMJEE) were deleted 2026-11-22. Their four Nifty 500 events (1998, 2007, 2011) now show NAME_UNKNOWN as before in effect: no security exists for them; membership and coverage baseline unchanged. | None. |
| A13 | OPEN | Audit Stage 2/3/7-raw (2026-11-22, AUDIT_REPORT): **S2-6** DONE in code, NOT YET BUILT: same symbol and same full equity ISIN across a gap now joins (46 pairs; 8,182 to 8,136 securities; **sec_id labels renumber**, 6,268 of 8,182; no index membership change); needs a full rebuild, then `verify`, then re-read ratchet and re-key anything that stores a sec_id (A3). **S2-7/S2-8** DONE: `check_ratchet_baseline` (baseline 217 / 177 / 15). Open: 10 same-symbol, same-ISIN pairs in non-equity series are not joined (owner call); S3-6..S3-9 doc items; a price edit that keeps the manifest and creates no flag is caught only by an independent price source. | After the rebuild: run `verify`, check the ratchet, regenerate `coverage_baseline` only if intended. |
| A1 | OPEN | Phase 1-4 work (2026-11-15..22) is committed locally in chunks on 2026-11-22; nothing pushed. | Owner decides when to push. |
| A8 | OPEN | Independent audit of the curated data (press events, aliases, size exceptions) and of the verification logic itself has not been done. | Execute `docs/AUDIT_PLAN.md`. |
| A2 | DONE | Inferred name links reviewed 2026-11-22 after the owner fixed the data start at 2007-01-01. Of 18 INFERRED aliases, 9 have events on or after 2007 and were checked: Aventis -> Sanofi, Mundra Port -> Adani Ports, United Phosphorus -> UPL, Piramal Healthcare (via Nicolas Piramal) -> PEL, Escorts, Polaris, ABB, Merck (E.Merck chain), and JSW Steel (the JINDVIJSTL alias is only used for pre-2005 events; later ones resolve to JSWSTEEL). Each resolves to one continuous security chain that matches the real company. The other 9 (Motor Industries x2, ICI India, Jindal Vijaynagar, India Cement, Himachal Futuristic, L&T-Sus, NIIT-Sus, E.Merck) only have events before 2007 and are out of scope. None rejected. | None. |
| A3 | OPEN | The curated identity join `GESHIPPING -> GESHIP` and `CASTROL -> CASTROLIND` (`data/curated/identity_links.csv`) map 8,182 securities from 8,570 symbols. | Check any code, notes or saved queries that hard-code a `sec_id`. |
| A4 | OPEN | `data/raw/manifest.csv` `fetched_utc` for `ind_niftynext50list.csv`, `ind_prs17022023_1.pdf`, `ind_prs25062025_2.pdf` (and the earlier `ind_prs24022022_1.pdf`) are estimates from the time the owner saved the file, not recorded download times. Hashes and sizes are real. | Optionally replace with real times, or note it in SOURCES.md. |
| A5 | OPEN | The change that emits a `PARTIAL` coverage row only when a day fails (`membership.build_anchored`) has no unit test (needs real data); it is covered by the full `verify` run. | Add a synthetic-data test if `build_anchored` is ever refactored to take injected paths. |
| A6 | OPEN | `999 dump/` still holds the originals of files copied into `data/raw/` (`ind_niftynext50list.csv`, `ind_prs17022023_1.pdf`, `ind_prs25062025_2.pdf`, plus earlier files). Untracked, the owner's. | Owner deletes when ready. |
| A7 | OPEN | Untracked and not ours, left alone: `999 dump/`, `Project Requirement.docx`, `requirements-lock.txt`. | Owner decides whether to commit or ignore. |

## B. Membership coverage

| ID | Status | Item | Notes |
|----|--------|------|-------|
| B1 | DONE | Nifty 50: VERIFIED 2007-01-02 -> 2026-11-19 (4,929 trading days; the 2016-04-01 -> 2017-09-28 DVR span is covered, see B3). Earlier results are before the 2007-01-01 floor. | Complete. |
| B2 | MOOT | Nifty 50 2004-01-01 -> 2004-05-23 (L&T ticker) is before the 2007-01-01 floor. | None. |
| B3 | DONE | Nifty 50 2016-04-01 -> 2017-09-28 (Tata Motors DVR, 51 securities / 50 companies) is now VERIFIED via `data/curated/index_dual_class.csv` (`membership.dual_class_securities`): +1 real, traded security allowed only while the DVR and its parent are both members. Inclusion date rests on the NSE workbook (no held release names it). Full build/verify run 2026-11-16, no FAIL. | Complete. |
| B4 | DONE | Nifty Next 50: VERIFIED 2007-01-02 -> 2026-11-19 (4,929 trading days; one window; 2004-2006 was verified too but is now before the 2007-01-01 floor). 92 days (Siemens Energy 2025-04-07..2025-06-26; Vedanta spin-offs 2026-04-30..2026-06-23) are verified as 50 real members plus documented zero-price dummies; those extras and dates rest only on the cited press releases. | Complete. |
| B5 | DONE | Nifty 500 (floor 2007-01-01, `FLOORS`/`ANCHORED` set): VERIFIED continuously `2013-08-26..2026-11-19` (+ `2013-06-11..08-01`, `2013-08-06..08-19`; 0 contradictions `>= 2007-01-01`). Dual-class and demerger dummy exceptions cited. | Complete. |
| B15 | RESOLVED | Suffixed press-release regex bug fixed in `nseuniverse/fetch.py`; 1,514 press PDFs/texts now held (including `ind_prs15092025_1.pdf`, `ind_prs04042025_2.pdf`, `ind_prs22082025_1.pdf`, and 277 newly fetched suffixed releases). | Closed in Phase 2. |
| B16 | OPEN | (Audit: the dummy rows in `index_size_exceptions.csv` are documentation only; see METHODOLOGY.) |
| B16a | OPEN | The Nifty 500 constituent list holds 501 symbols: 500 real plus DUMMYHEG (HEG Graphite demerger, 2026-09-07; no exclusion release held). `ANCHORED` test now counts non-DUMMY symbols. DUMMYSKFIN (2025-10-15) is not in `index_size_exceptions.csv` yet: its exit release (ind_prs11122025_1) is not held. | Extras do not change the real-member count check, they are documentation. |
| B10 | DONE | Nifty 100: VERIFIED 2007-01-02 -> 2026-11-19 (4,929 trading days; full build/verify 2026-11-22, no FAIL; dual-class DVR rows and dummy extras cited). | Complete. |
| B11 | DONE | Nifty 100 2004-01-01 -> 2005-02-20 now verified: the blockers were tickers (JINDVIJSTL for JSW Steel, EMERCK for Merck, L&T and NIIT before their later tickers), all in held files. | None. |
| B14 | MOOT | Possible Nifty 50 improvement via an L&T alias for 2004: before the floor, not pursued. | None. |
| B13 | MOOT | Vijaya Bank dates differ by 4 days (2004-05-24 vs 05-28) between the Nifty 100 and Next 50 workbook sheets: before the floor, so no claim is made. | None. |
| B12 | OPEN | Suffixed mid-cycle releases not held (ind_prs20012026_2, 20052026_1, 17062026_2, 13072026_1, 04042025_2, 21062024_1, 24042024_1 ...): unread, could hold Nifty 100 changes invisible to the size check. | Ask owner to save them if a check is wanted. |
| B6 | DONE | Scaling broad market and sectoral indices: 27 indices verified (20 anchored + 7 composite) across 45 active verified windows with 0 contradictions (the last contradiction on `NIFTYMIDCAP100 2009-03-27 GVT&D` was resolved via `ind_prs12122011.pdf`). Remaining 30 indices in `index_universe.csv` lack historical workbook sheets and legitimately remain `UNVERIFIED`. | Complete. |
| B17 | DONE | Resolved last remaining contradiction on `NIFTYMIDCAP100 2009-03-27 GVT&D` via official NSE press release `ind_prs12122011.pdf` documenting Areva T&D India demerger exclusion and JISLJALEQS inclusion effective 2011-12-14. Zero contradictions across all indices. | Complete. |
| B7 | OPEN | About 300 suffixed press releases (`ind_prsDDMMYYYY_1.pdf`, `_2`, `_3`) listed on niftyindices.com were never downloaded. For Nifty 50 and Next 50 the contradiction check reports none missing; other indices may need some ("Replacements in indices" titles are the relevant ones). Known missing and relevant to other indices: e.g. `ind_prs09022023_1.pdf`, `ind_prs19042023_1.pdf`, `ind_prs05042022_1.pdf`, `ind_prs20102022_1.pdf`. | Ask the owner to save one at a time (file name, source, size) when an index needs it. |
| B8 | OPEN | Four releases have no text layer even with PyMuPDF (`ind_prs13032024`, `ind_prs16062018`, `ind_prs18092018`, `ind_prs25092018`; none is cited by a curated row). `ind_prs23082021.pdf` is NOT image-only: PyMuPDF reads it, and `press.extract_text` now regenerates its text (nine such empty text files were fixed in `data/build/press_text`). Other releases before 2020-09 were not scanned for this. Nifty 100 work read ind_prs23082021.pdf as text (it has a text layer). | Scan and render when extending to other indices. |
| B9 | OPEN | Zero-price dummy-symbol demergers in other indices (Nifty 50, 100, 500...) have not been catalogued. Only the Next 50 ones are in `index_size_exceptions.csv`. | Needed before verifying another fixed-size index over 2025-2026. |

## C. Other limitations carried over (see METHODOLOGY section 7)

| ID | Status | Item |
|----|--------|------|
| C1 | OUT OF SCOPE | Adjusted prices before 2007-01-01 are unverified (the held corporate-action feed has almost no splits/bonuses for 2004-2006; a fresh NSE download for those years was identical). The data bank starts at 2007-01-01 (owner decision 2026-11-22); earlier days are not claimed. |
| C2 | OPEN | 15 share actions contradicted by prices are not applied (`build/actions_rejected_or_shifted.csv`); 108 documented adjustment breaks (`waivers.csv`); 177 unexplained overnight moves; 3 rights days differ >25% from the theoretical adjustment. |
| C3 | OPEN | Index values: 1,061 index-days where the two NSE sources disagree (338 by >=0.1%), flagged `conflict=True`; 929 index-days missing inside index lives across 208 indices (869,785 index-days total). |
| C4 | OUT OF SCOPE | 2004 prices for some large companies are absent from NSE's own files (e.g. L&T before 2004-06-23). Before the 2007-01-01 start, so not claimed. |
| C5 | OPEN | `IndexInclExcl.xls` is a held input of unverified origin with no live NSE source; it feeds early index membership history. The corporate-action feed, `symbolchange.csv` and `EQUITY_L.csv` were verified against fresh NSE copies on 2026-11-22. |

## D. Working rules (from the owner)

- Nothing is estimated; missing stays missing and the API refuses it.
- Every curated alias or event cites a file that exists in `data/raw/`; inferred links are marked as such.
- `verify` must show no FAIL; add a unit test for every new code path and run `pytest -q`.
- Ask before pushing, deleting, committing, or saving any downloaded file (state file name, source, size).
- Browser pane cannot save files; the owner saves downloads, we copy them into `data/raw/` and add a manifest row.
- Full `verify` takes about 11 minutes and `build` several; run them in the background, once, at the end.
