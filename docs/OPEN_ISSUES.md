# Open issues tracker

Last updated: 2026-11-16. Status values: **OPEN** (work possible), **DECISION** (needs the project owner),
**BLOCKED** (cannot be done under the project rules with the evidence held), **DONE** (kept for the record).
Add a row when something is found; change its status, do not delete it.

## A. Pending now

| ID | Status | Item | Next step |
|----|--------|------|-----------|
| A1 | DECISION | Nothing from the Nifty Next 50 work is committed or pushed. Changed: `index_events_press.csv`, `name_aliases.csv`, `manifest.csv`, `membership.py`, `identity.py`, both test files, README, METHODOLOGY. New: `index_size_exceptions.csv`, `identity_links.csv`, `constituents/2026-11-15/ind_niftynext50list.csv`, this file. | Owner says when to commit / push. |
| A2 | OPEN | Review the **inferred name links** (2004-2011), each marked "INFERRED" in `data/curated/name_aliases.csv`: Aventis, Mundra Port, United Phosphorus, Motor Industries (x2), ICI India, E.Merck, Piramal Healthcare (via `symbolchange.csv`); Escorts, India Cement, Polaris (NSE equity list / renamed ticker); spelling variants "Jindal Vijaynagar", "Himachal Futuristic Communication". `verify` passes, but a wrong link would not show up there. | Owner spot-checks the ones relied on; any rejected alias is deleted and the build re-run. |
| A3 | OPEN | The curated identity join `GESHIPPING -> GESHIP` (`data/curated/identity_links.csv`) renumbers `sec_id` for later securities (8,148 -> 8,147 securities). | Check any code, notes or saved queries that hard-code a `sec_id`. |
| A4 | OPEN | `data/raw/manifest.csv` `fetched_utc` for `ind_niftynext50list.csv`, `ind_prs17022023_1.pdf`, `ind_prs25062025_2.pdf` (and the earlier `ind_prs24022022_1.pdf`) are estimates from the time the owner saved the file, not recorded download times. Hashes and sizes are real. | Optionally replace with real times, or note it in SOURCES.md. |
| A5 | OPEN | The change that emits a `PARTIAL` coverage row only when a day fails (`membership.build_anchored`) has no unit test (needs real data); it is covered by the full `verify` run. | Add a synthetic-data test if `build_anchored` is ever refactored to take injected paths. |
| A6 | OPEN | `999 dump/` still holds the originals of files copied into `data/raw/` (`ind_niftynext50list.csv`, `ind_prs17022023_1.pdf`, `ind_prs25062025_2.pdf`, plus earlier files). Untracked, the owner's. | Owner deletes when ready. |
| A7 | OPEN | Untracked and not ours, left alone: `999 dump/`, `Project Requirement.docx`, `requirements-lock.txt`. | Owner decides whether to commit or ignore. |

## B. Membership coverage

| ID | Status | Item | Notes |
|----|--------|------|-------|
| B1 | DONE | Nifty 50: VERIFIED 2004-05-24 -> 2016-03-31 and 2017-09-29 -> today. | |
| B2 | BLOCKED | Nifty 50 2004-01-01 -> 2004-05-23: L&T (member until 2004-05-24) has no NSE bhavcopy before 2004-06-23. | Needs a bhavcopy source for L&T; none held. |
| B3 | DECISION | Nifty 50 2016-04-01 -> 2017-09-28: 51 securities (Tata Motors DVR), 50 companies. The exactly-50 rule was deliberately not relaxed. The same "documented extras" rule used for Next 50 dummy days (`index_size_exceptions.csv`) could cover it; the 22 Feb 2016 NSE release documents the DVR. | Owner decides whether to treat the DVR as a documented extra. Nothing changed. |
| B4 | DONE | Nifty Next 50: VERIFIED 2004-01-01 -> 2026-11-13 (one window). 92 days (Siemens Energy 2025-04-07..2025-06-26; Vedanta spin-offs 2026-04-30..2026-06-23) are verified as 50 real members plus documented zero-price dummies; those extras and dates rest only on the cited press releases. | |
| B5 | OPEN | Nifty 100, Nifty 500, Nifty Midsmallcap 400: not started (owner instruction). Each needs a current constituent list in `data/raw/constituents/<date>/`, a fixed size in `ANCHORED`, and the same name/event work. | Start only when the owner says so. |
| B6 | OPEN | The other 55 in-scope indices (NSE Broad Market and Sectoral categories): UNVERIFIED. 329 distinct unresolved workbook names remain in `data/build/membership/unresolved.csv`. | Resolve only with cited evidence. |
| B7 | OPEN | About 300 suffixed press releases (`ind_prsDDMMYYYY_1.pdf`, `_2`, `_3`) listed on niftyindices.com were never downloaded. For Nifty 50 and Next 50 the contradiction check reports none missing; other indices may need some ("Replacements in indices" titles are the relevant ones). Known missing and relevant to other indices: e.g. `ind_prs09022023_1.pdf`, `ind_prs19042023_1.pdf`, `ind_prs05042022_1.pdf`, `ind_prs20102022_1.pdf`. | Ask the owner to save one at a time (file name, source, size) when an index needs it. |
| B8 | OPEN | Image-only PDFs have no extractable text: `ind_prs23082021.pdf` was read from page renders (pymupdf). Other releases before 2020-09 were not scanned for this. | Scan and render when extending to other indices. |
| B9 | OPEN | Zero-price dummy-symbol demergers in other indices (Nifty 50, 100, 500...) have not been catalogued. Only the Next 50 ones are in `index_size_exceptions.csv`. | Needed before verifying another fixed-size index over 2025-2026. |

## C. Other limitations carried over (see METHODOLOGY section 7)

| ID | Status | Item |
|----|--------|------|
| C1 | BLOCKED | Adjusted prices before 2007-01-01 are unverified (the held corporate-action feed has almost no splits/bonuses for 2004-2006; a fresh NSE download for those years was identical). |
| C2 | OPEN | 15 share actions contradicted by prices are not applied (`build/actions_rejected_or_shifted.csv`); 108 documented adjustment breaks (`waivers.csv`); 176 unexplained overnight moves; 3 rights days differ >25% from the theoretical adjustment. |
| C3 | OPEN | Index values: 1,061 index-days where the two NSE sources disagree (338 by >=0.1%), flagged `conflict=True`; 925 index-days missing inside index lives. |
| C4 | BLOCKED | 2004 prices for some large companies are absent from NSE's own files (e.g. L&T before 2004-06-23). |
| C5 | OPEN | `IndexInclExcl.xls`, `raw_corporate_actions_1995_2026.json`, `symbolchange.csv`, `EQUITY_L.csv` are held inputs of unverified origin (only 2004-2006 of the corporate-action feed was re-checked against NSE). |

## D. Working rules (from the owner)

- Nothing is estimated; missing stays missing and the API refuses it.
- Every curated alias or event cites a file that exists in `data/raw/`; inferred links are marked as such.
- `verify` must show no FAIL; add a unit test for every new code path and run `pytest -q`.
- Ask before pushing, deleting, committing, or saving any downloaded file (state file name, source, size).
- Browser pane cannot save files; the owner saves downloads, we copy them into `data/raw/` and add a manifest row.
- Full `verify` takes about 11 minutes and `build` several; run them in the background, once, at the end.
