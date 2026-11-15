# NSE Point-in-Time Universe — Plan From Scratch

Written 2026-11-15. Supersedes `REBUILD_PLAN.md`.

## 1. What we are building

A Python package that answers, for any date from 2004 to today, using only what NSE officially published:

| # | Requirement | Deliverable |
|---|---|---|
| 1 | All NSE-listed equities, 2004 → today, adjusted for corporate actions | Every security that ever traded, with raw and adjusted prices |
| 2a | All official NSE indices — values | Daily index levels (OHLC, total-return, PE/PB/yield where published) |
| 2b | All official NSE indices — membership from launch | Who was in each index on each date |
| 3 | All data from the bhavcopies | Every row and every column NSE published, unaltered |
| — | Deterministic workflow | Same raw files + same code = byte-identical output |
| — | Tests that the data is not tainted | A `verify` command that fails the build on any unexplained discrepancy |

## 2. Why start over, and what changes

The last rebuild produced clean code but did not meet the requirement, because it was built on inherited caches rather than official sources:

- **Membership:** 20 of 23 indices are `UNVERIFIED` on every date; only Nifty 500, Nifty 200 and LargeMidcap 250 have verified windows, and those cover roughly half the history.
- **Bhavcopies:** 2016–2026 came from a stripped cache with 7 of 13 columns. Requirement 3 is not met for those ten years.
- **Indices:** 23 hand-picked indices, values only from 2012.

So the new plan is **source-first**. Three rules:

1. **Only official sources are data.** Everything is re-downloaded from NSE / NSE Indices. Nothing from `../03 Moshi 15` or the old `data/` is an input (it stays untouched as a cross-check only).
2. **Present or absent, never estimated.** No turnover-ranked proxies, no back-projection of today's constituents, no filling missing fields. If a fact has no official source, the API raises "no coverage" for it. This replaces the four-regime labelling scheme.
3. **Prove the source before writing the pipeline.** Phase 0 is a go/no-go gate on source availability.

Two simplifications fall out of this:

- **Store long-format tables, not wide matrices.** One row per (date, symbol, series). Wide date × security frames are produced on query.
- **Drop the `knowledge_date` machinery.** Back-adjusting as of date D using only actions with ex-date ≤ D is already point-in-time, because an adjustment has no effect on prices before its ex-date. Announcement dates are not needed for requirement 1.

## 3. Sources

URLs and era boundaries below are from memory and are confirmed in Phase 0.

| Data | Official source | Expected coverage |
|---|---|---|
| Equity bhavcopy (legacy) | `nsearchives.nseindia.com/content/historical/EQUITIES/YYYY/MMM/cmDDMMMYYYYbhav.csv.zip` | 2004 → July 2024 |
| Equity bhavcopy (UDiFF) | `nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip` | July 2024 → today |
| Daily index file | `nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv` | ~2012 → today, all indices |
| Index history before 2012 | niftyindices.com historical-data endpoints (price, total-return, PE/PB/yield) | Each index from its base date |
| Corporate actions | NSE corporate-actions API (already archived as `raw_corporate_actions_1995_2026.json`, 43,816 records; re-fetched to confirm) | 1995 → today |
| Symbol changes, listings | `symbolchange.csv`, `EQUITY_L.csv`, delisted-securities list | Full history |
| Holidays | NSE holiday circulars | Cross-check only; see Phase 1 |
| Index membership | In priority order: (a) NSE Indices inclusion/exclusion workbook `IndexInclExcl.xls` — held copy ends July 2020, check for a newer edition; (b) NSE Indices reconstitution press releases, 2020 → today; (c) monthly constituent / weightage archives as checkpoints; (d) today's constituent CSVs as the end anchor | Varies by index — the main risk, see §7 |

## 4. Design

```
data/
  raw/        Exactly as downloaded (zip, csv, xls, pdf). Never edited.
              manifest.csv: path, url, sha256, bytes.
  curated/    Facts typed in by hand (e.g. from press-release PDFs).
              Every row cites a file in raw/.
  build/      Everything derived. Deleted and regenerated at will.
              checksums.txt is committed to git.
nseuniverse/
  fetch.py       The only module that touches the network
  bhavcopy.py    Per-era parsers → one canonical table
  calendar.py    Trading days
  identity.py    Security ids, symbol and ISIN history
  actions.py     Corporate actions → adjustment factors, dividends
  indices.py     Index values
  membership.py  Event replay → membership intervals
  verify.py      All data-integrity checks
  api.py         Read-only queries
  cli.py         fetch | build | verify | update
tests/           Code tests on small fixtures (fast, offline)
```

**Determinism contract**

- `fetch` is the only network step. It writes raw bytes and appends to the manifest; an existing raw file is never overwritten. If NSE re-publishes a different file, it is saved as a new revision and flagged.
- `build` reads only `raw/` and `curated/`, runs offline, and writes no timestamps, host paths or unordered output. Rows are sorted, the Parquet writer settings are pinned, dependency versions are locked.
- `build/checksums.txt` lists the hash of every output. A change in it shows up in `git diff`, so any change in the data is visible and attributable to a commit.

**API sketch**

```python
import nseuniverse as nse

nse.bhavcopy("2015-03-02")                          # every row, as published
nse.securities(as_of="2010-06-30")                  # everything listed that day
nse.prices(["RELIANCE"], start, end,
           adjust="splits" | "total_return" | None,
           as_of=None)                              # as_of = no later actions applied
nse.index_values("NIFTY 50", start, end)
nse.index_members("NIFTY 50", as_of="2010-06-30")
nse.coverage()                                      # what is verified, for which dates
```

Symbols are resolved as of the query date, so `RELIANCE` in 2006 and a renamed ticker in 2024 both find the right security. A query outside verified coverage raises an error naming the gap; it never returns an empty or partial answer silently.

## 5. Phases

Each phase ends with checks that must pass before the next starts.

### Phase 0 — Decisions and source proof (gate)

- For every source in §3, fetch samples from each era (e.g. one day per year for bhavcopies; three indices of different ages for history; two press releases). Record the working URL pattern, required headers, rate limits and file schema in `docs/SOURCES.md`.
- For membership, list every official index and mark which source can cover it from launch.
- **Exit:** a written source register, and an honest table of which indices can reach full membership coverage. If a source is unreachable, the plan is revised here, before any pipeline code exists.

### Phase 1 — Raw archive and calendar

- Archive the old work on a branch, then start a clean tree. Keep `data/raw/` contents only where they are original NSE files.
- Build `fetch.py` and the manifest. Download every equity bhavcopy from 2004-01-01 to today from NSE, throttled and resumable (about 5,700 files).
- Trading calendar: a day is a trading day if NSE published a bhavcopy for it. Every weekday without one must match an entry in the holiday list; every weekend day with one must be a known special session.
- **Exit:** manifest hashes verify; zero unexplained missing or extra days.

### Phase 2 — Bhavcopy table (requirement 3)

- One parser per file format, selected by the file's header rather than by date. Output: one table, partitioned by year, with every published column and every series (EQ, BE, SM, and the rest). Columns that did not exist in an era are null.
- **Exit:** the lossless check — for every day, the canonical rows re-serialised match the raw file row-for-row and value-for-value.

### Phase 3 — Identity, corporate actions, adjusted prices (requirement 1)

- Identity: a stable security id built from ISIN history plus dated symbol changes. Symbol reuse by an unrelated company creates a new id. Mergers and demergers end or start ids; they are never spliced.
- Actions: parse splits, bonuses, consolidations and rights from the NSE feed into exact ratios. Demergers and other restructurings that the feed does not quantify go in a curated, cited table. Dividends are kept as cash amounts for the total-return series.
- **Exit:**
  - Every action in the feed is parsed, curated, or listed in an explicit waiver file with a reason. Unparsed count is zero.
  - On each ex-date, the adjustment ratio agrees with the observed price gap within tolerance.
  - Every overnight move beyond a threshold with no matching action appears in an exceptions report, which must be empty or waived line by line.
  - Adjusted price × adjusted volume equals raw price × raw volume.
  - About 30 hand-checked real events pass (e.g. Reliance 1:1 bonus 2017, HDFC Bank split 2019, HDFC–HDFC Bank merger 2023, ITC Hotels demerger 2025).

### Phase 4 — Index values (requirement 2a)

- Parse all daily index files; backfill each index to its base date from NSE Indices history. Map historical names (CNX → NIFTY) with a dated rename table.
- **Exit:** where the two sources overlap they agree exactly; no gaps on trading days after an index's launch; each index's first value matches its stated base value and date.

### Phase 5 — Index membership (requirement 2b)

- Store membership as events (index, symbol, date, in/out, source citation). Daily membership is derived by replaying events forward from the launch list.
- Work in tiers: broad-market indices first, then sectoral, then thematic and strategy.
- **Exit, per index:**
  - Replaying from launch reproduces today's official constituent list exactly.
  - Replay matches every intermediate checkpoint file.
  - Member count equals the index's stated size on every date, apart from documented transition days.
  - Every member was listed and trading on every day of its membership.
  - An index that fails any of these is published as "no coverage" for the failing window, not approximated.

### Phase 6 — API and packaging

- `api.py`, the CLI, a `pyproject.toml` with locked dependencies, README, and a methodology page generated partly from the coverage table.
- **Exit:** API contract tests; a fresh clone can run `build` and `verify` offline from the raw archive and reproduce `checksums.txt`.

### Phase 7 — Daily update

- `update` = fetch new days + the same `build` code. There is no separate incremental code path.
- **Exit:** building through day N in one run equals building through N−1 and then updating. Scheduled job runs `update` then `verify`, and commits only if `verify` passes.

## 6. How the data is shown to be untainted

`nse verify` runs against the full dataset and is the release gate. It checks, in summary:

| Check | What it catches |
|---|---|
| Raw hashes match the manifest | A raw file altered after download |
| Lossless bhavcopy round-trip | Any dropped, filled, clipped or reordered value |
| Calendar reconciliation | Missing or phantom trading days |
| Previous-close continuity (today's prev-close vs yesterday's close, except on ex-dates) | Mis-joined securities, missed actions |
| Ex-date ratio vs observed gap; unexplained-gap report | Wrong or missing corporate actions |
| Two-source agreement for index values | Bad backfill, wrong name mapping |
| Membership replay to anchors; count; member-was-trading | Wrong, missing or leaked constituents |
| Truncation invariance: build with raw data cut at date D equals the full build cut at D | Any look-ahead in raw facts or membership |
| Double build produces identical checksums | Non-determinism |
| No value in `build/` without a path back to a `raw/` or `curated/` row | Invented data |

Separately, `tests/` holds fast unit tests on small fixtures for the parsers and the adjustment maths. Unit tests check the code; `verify` checks the data.

## 7. Risks

1. **Membership from launch for every index may not be obtainable from free official sources.** NSE publishes roughly 350 indices. Launch lists and full change histories are reliably public for the broad and sectoral ones; for many thematic and strategy indices they may exist only in scattered press releases, or only in NSE Indices' paid data service. Phase 0 quantifies this. The fallback is published coverage gaps, not estimates.
2. **Post-2020 membership needs transcription from press-release PDFs.** This is manual, cited work in `curated/`, guarded by the replay-to-anchor check.
3. **NSE sites throttle and block automated clients.** The fetcher must be slow, resumable and session-aware; the first full download may take days.
4. **Demergers and mergers have no clean ratio in the feed.** They need a curated table; until an event is curated, the affected security's adjusted series is flagged from that date.
5. **Raw archive size (several hundred MB) is too large for plain git** and this folder syncs through Google Drive. Raw files stay out of git; the manifest goes in.

## 8. Decisions (confirmed 2026-11-15)

| Decision | Confirmed choice |
|---|---|
| What "API" means | A Python package. A thin HTTP layer can be added on top later without changing the data. |
| Index scope for membership | All indices for values. For membership: broad-market and sectoral to full coverage first, thematic and strategy as far as official sources allow, with gaps published. Consider NSE Indices' paid historical-constituent data if 100% is a hard requirement. |
| Pre-2004 | Prices start 2004-01-01 as specified. Membership before 2004 is stored by published symbol but is not linked to price data. |
| Existing code and data | Archive on a branch, start a clean tree. Reuse only original NSE raw files and, where they survive review, the bhavcopy header mapping and dividend-text parser. |
