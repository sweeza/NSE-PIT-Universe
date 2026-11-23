# Source Register (Phase 0)

Probed 2026-11-15 with plain HTTP clients and a browser-like User-Agent, no login. Samples were downloaded to a scratch folder, not into `data/`. "Verified" below means a sample was fetched and its content inspected today.

## 1. Equity bhavcopy — VERIFIED, fully reachable

| Era | URL pattern | Columns | Notes |
|---|---|---|---|
| Legacy, 1998 → 2024-07-05 | `nsearchives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MMM}/cm{DD}{MMM}{YYYY}bhav.csv.zip` | 2004: `SYMBOL SERIES OPEN HIGH LOW CLOSE LAST PREVCLOSE TOTTRDQTY TOTTRDVAL TIMESTAMP`; by 2018 also `TOTALTRADES ISIN` | Trailing comma on every line. Dates written `2-JAN-2004`. |
| UDiFF, 2024-07-05 → today | `nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip` | 34 columns, ISIN, instrument id, name, session id, lot size | ISO dates. Includes bonds and gold bonds (series `GB`, `NX`, …). |

- 2024-07-05 exists in both formats; 2024-07-08 and later exist only as UDiFF. Format must be chosen by header, not by date, and the overlap day is a free cross-check between the two parsers.
- Missing days return HTTP 404 with a small HTML body (e.g. 2004-01-03, a Saturday). Some other failures return **HTTP 200 with an HTML page**, so fetch must check content type or zip magic bytes, never status alone.
- **2004-era files have no ISIN and no trade count.** Identity before the ISIN era (somewhere between 2010 and 2018, to be pinned down in Phase 1) must come from symbol history and `symbolchange.csv` alone. This is the weakest part of requirement 1 for early years.
- Row counts: 749 (2004) → 2,806 (2024) → 3,727 (2026-11-12). The 2026 count includes non-equity series, so "all constituents" needs an explicit series filter that is a documented choice, not a silent one.
- Files for 1998 and 2003 also exist, so extending prices before 2004 is feasible later.

## 2. Index values

### 2a. Daily file — VERIFIED
`nsearchives.nseindia.com/content/indices/ind_close_all_{DDMMYYYY}.csv`

- Same 13 columns throughout: name, date, OHLC, points change, % change, volume, turnover, PE, PB, dividend yield.
- First available day: **2012-02-21** (earlier tested dates return 404). 30 indices that day, 167 on 2026-11-12 (about 13 look like fixed-income).
- Index names change over time (`S&P CNX Nifty` in 2012, `Nifty 50` in 2026), so a dated rename table is required.

### 2b. History API — VERIFIED, with a changed path
`POST https://www.niftyindices.com/BackPage/{endpoint}`, JSON body `{"cinfo":"{'name':..,'startDate':'DD-Mon-YYYY','endDate':..,'indexName':..}"}`, session cookie from the history page, `Referer` header set.

| Endpoint | Returns | Probed |
|---|---|---|
| `getHistoricaldatatabletoString` | Date, OPEN, HIGH, LOW, CLOSE | Nifty 50 from 2004; Nifty Bank from 2000 |
| `getTotalReturnIndexString` | Total-return index and net-total-return | Nifty 50 2004 |
| `getpepbHistoricaldataDBtoString` | PE, PB, dividend yield | Nifty 50 2004 |

- The old `Backpage.aspx/...` path now redirects to a login page. The new path is read from the site's own script and could change again, so `fetch.py` must fail loudly on a redirect or non-JSON reply.
- The page UI limits a request to one year; the API accepted a two-year range in testing. Fetch in one-year chunks anyway.
- Pre-2012 OHLC can be blank (`-`), with only CLOSE present (seen for Nifty Bank in 2000). Blank stays null.
- Index-name spelling in the request has an internal mapping in the site script; names must be taken from the site's own list, not guessed.
- Not yet checked: coverage for every index (only Nifty 50 and Nifty Bank were queried), and agreement between 2a and 2b where they overlap.

## 3. Corporate actions — NOT VERIFIED LIVE

- The NSE corporate-actions API (`nseindia.com/api/corporates-corporateActions`) sits behind `nseindia.com`, which returns **HTTP 403 to scripted requests**, and the holiday API redirects.
- A probe through the in-app browser session was declined by the permission layer and was not retried or worked around.
- A previously fetched copy exists (`data/raw/raw_corporate_actions_1995_2026.json`, 43,816 records, `caBroadcastDate` empty on every row). Its origin and completeness were not re-checked today.
- **Update 2026-11-16:** the page itself (nseindia.com → Companies Listing → Corporate Filings → Corporate Actions, Equity tab, custom dates) works in a normal browser. Its Download button opens a new tab, which the in-app browser blocks for automated clicks, so the file was downloaded by the user. `data/raw/corporate_actions/CF-CA-equities-01-01-2004-to-31-12-2006.csv` (230,817 bytes, 2,062 rows, no ISIN column) matches the held feed's 2004-2006 records exactly. It adds no records; it is kept as provenance for that slice. The page offers nothing earlier or fuller for 2004-2006.

## 4. Listing and symbol files — VERIFIED

| File | URL | Notes |
|---|---|---|
| Current equity list | `nsearchives.nseindia.com/content/equities/EQUITY_L.csv` | Symbol, name, series, listing date, face value, ISIN. Current listings only. |
| Symbol changes | `.../content/equities/symbolchange.csv` | 1,080 rows: name, old symbol, new symbol, effective date. Includes mutual-fund products; has `OLD == NEW` self-loops (from earlier work). |
| Delisted securities | `.../content/equities/delisted.csv` | Exists (lowercase name; the uppercase name 404s). Contents not yet inspected. |

## 5. Index membership

### Press releases — VERIFIED
- `niftyindices.com/press-release` lists **1,514 press releases** (`ind_prsDDMMYYYY.pdf` and suffixed `ind_prsDDMMYYYY_N.pdf`), dated 1998 → 2026, held in `data/raw/pressreleases/pdf/` and tracked in `manifest.csv`.
- Real PDFs with extractable text (and audited OCR text where scanned, e.g. `ind_prs23082021.pdf`).
- Content mixes equity and fixed-income index changes, futures-eligibility notices, demerger replacements, and new-index launches. Equity changes name the index, the included and excluded companies, and an effective date.
- **Format drift:** 2004 releases name companies only, with no symbol; a Symbol column appears around 2016. Earlier events map through reviewed alias tables (`data/curated/name_aliases.csv`, `press_name_symbol.csv`).
- Parsing is semi-manual: extract text, classify, then enter events into `data/curated/index_events_press.csv` with a direct raw citation.

### Current constituents — VERIFIED
`niftyindices.com/IndexConstituent/ind_{name}list.csv` (59 constituent CSVs held for current index anchors as of November 2026). Columns: company, industry, symbol, series, ISIN. This is the end anchor for replay.

### Not found
- **No live link to `IndexInclExcl.xls`**; every guessed URL returned the site's HTML error page. The held copy ends 2020-07-31 and its origin is not documented here.
- No constituent archive or historical-data pages exist at the guessed paths. Month-end constituent/weightage snapshots, which would serve as replay checkpoints, were not located.
- Methodology PDF is available (`/Methodology/Method_NIFTY_Equity_Indices.pdf`, 352 pages) and gives the size and rules per index, needed for the count check.

## 6. Coverage assessment and what Phase 0 changes

| Requirement | Status after Phase 0 |
|---|---|
| 3. All bhavcopy data | **Achievable in full**, 2004 → today, from the official source. Only limit is the columns each era published. |
| 1. Constituents, adjusted | Prices are fine. **Identity before the ISIN era and corporate actions are the open items.** |
| 2a. Index values | Daily file gives 2012 →; history API gives price, total return and PE/PB back to each index's base. Coverage per index still to be enumerated. |
| 2b. Membership from launch | **Feasible for broad-market and sectoral indices; unproven for most thematic and strategy indices.** Replay needs launch list + press-release changes + end anchor; the launch list for older indices and the 2020 → today inclusions in the held workbook are the gap. Unknown how many of ~167 daily-file indices have a fetchable launch list. |

### Decisions needed to continue
1. **Corporate actions source.** Options: (a) accept the held JSON as the raw input, re-checking it against bhavcopy price gaps in Phase 3; (b) fetch it yourself in a normal browser session (NSE's site allows it) and drop the file in `data/raw/`; (c) allow a browser-driven fetch of that single API. Not attempted further without your say.
2. **Membership launch lists.** Whether to treat the held `IndexInclExcl.xls` as an acceptable raw input (its origin is undocumented) or to rebuild early history from press releases only, which leaves older indices with gaps.

### Proposed next step
Phase 1 can start now for the bhavcopy archive, which depends on neither decision.

## 7. Bulk deals, block deals, and short selling — VERIFIED (2026-11-23)

Source page: `https://www.nseindia.com/report-detail/display-bulk-and-block-deals` (1-year Custom windows downloaded in a real Chrome session) and `nsearchives.nseindia.com/content/equities/{bulk,block}.csv` (daily latest-day snapshots via `fetch.fetch_deals_today()`).

| Report | Era / Source | Coverage | Columns | Notes |
|---|---|---|---|---|
| Bulk Deals | Archive CSV (`bulk_{YYYYMMDD}_{YYYYMMDD}.csv`) | 2004-01-04 → 2026-11-20 (23 windows) | `Date `, `Symbol `, `Security Name `, `Client Name `, `Buy / Sell `, `Quantity Traded `, `Trade Price / Wght. Avg. Price `, `Remarks ` | UTF-8 BOM, quoted fields, trailing spaces in header, Indian comma-formatted numbers, `DD-MMM-YYYY` dates. |
| Bulk Deals | Daily snapshot (`bulk_{YYYYMMDD}.csv`) | Latest day | `Date`, `Symbol`, `Security Name`, `Client Name`, `Buy/Sell`, `Quantity Traded`, `Trade Price / Wght. Avg. Price`, `Remarks` | Plain CSV, no BOM, no trailing spaces, `Buy/Sell` without spaces. |
| Block Deals | Archive CSV (`block_{YYYYMMDD}_{YYYYMMDD}.csv`) | 2005-11-17 → 2026-11-20 (22 windows) | `Date `, `Symbol `, `Security Name `, `Client Name `, `Buy / Sell `, `Quantity Traded `, `Trade Price / Wght. Avg. Price `, `Remarks ` | Same archive layout as Bulk Deals. |
| Block Deals | Daily snapshot (`block_{YYYYMMDD}.csv`) | Latest day | `Date`, `Symbol`, `Security Name`, `Client Name`, `Buy/Sell`, `Quantity Traded`, `Trade Price / Wght. Avg. Price` | Same as Bulk daily snapshot except `Remarks` column is omitted. |
| Short Selling | Archive CSV (`short_{YYYYMMDD}_{YYYYMMDD}.csv`) | 2008-02-01 → 2026-11-20 (19 windows) | `Date `, `Symbol `, `Security Name `, `Quantity ` | UTF-8 BOM, trailing spaces in header, Indian comma-formatted numbers; `"-"` in Quantity (1 row) stays null. |

## 8. Security Category & Impact Cost — VERIFIED (2026-11-23)

Source page: `https://www.nseindia.com/all-reports` (Capital Market → Equities & SME → Monthly Reports: `Security Category Impact Cost`, and Archives: `CM - Security Catergory Impact Cost (.T01)`, both tagged `data-type="monthly-reports"`). NSE does **not** publish a daily per-security impact-cost file.

- **URL pattern:** `https://nsearchives.nseindia.com/content/nsccl/C_CATG_{MMM}{YYYY}.T01` (monthly NSE Clearing file).
- **Coverage on `nsearchives.nseindia.com`:** 47 monthly files (16,905,605 bytes / 16.12 MB; 532,386 data rows, 172,282 with numeric impact cost). Continuous from **2023-10 through 2026-11** (38 consecutive months), plus 9 earlier months (**2019-03**, **2021-01..2021-06**, **2023-05..2023-06**). All other months from 2004 through 2026 return HTTP 404 (alternate suffixes `.T02`/`.T03` and `/archives/nsccl/` also 404).
- **Layout (identical across all 47 files, 2019–2026):** Plain CSV (`.T01`, `latin-1`, no column header row):
  - Header record: `10,{MMM},{YYYY},{count}`
  - Data record (6 fields): `20,{symbol},{series},{isin},{category},{impact_cost_pct}`
  - `category`: `1` (Group I: traded ≥80% of days in prior 6 months, mean impact cost ≤1%), `2` (Group II: ≥80% of days, >1%), `3` (Group III / other; impact cost blank).
  - `impact_cost_pct`: 6-month rolling mean impact cost (%) for a standard **₹1,00,000 (₹1 lakh)** order size per NSE Clearing methodology (no order-size column in the file). Range across all 47 files: 0.00% to 32.01%.
  - Series covered: all CM series (`EQ`, `BE`, `SM`, `ST`, `BZ`, `SG`, `N0`–`N9`, `GS`, `GB`, `MF`, etc.); impact cost is blank for Group 3, debt, and illiquid series (never filled).
  - Quirk: 1 row in `C_CATG_APR2026.T01` (`KRISHPP`, `E1`) is wrapped in outer double quotes with a trailing tab; stripped cleanly by `market.parse_impact_cost`.

## 9. Manifest download times that are estimates

Four rows in `data/raw/manifest.csv` carry a `fetched_utc` that is an estimate (the time the owner saved the file, not a recorded download time): `data/raw/constituents/2026-11-15/ind_niftynext50list.csv`, `data/raw/pressreleases/pdf/ind_prs17022023_1.pdf`, `ind_prs25062025_2.pdf` and `ind_prs24022022_1.pdf`. Their hashes and sizes are real (computed from the held files). (Added 2026-11-23, issue A4.)

## 10. NSE MII security master (shares outstanding) — HELD (2026-11-23)

`https://nsearchives.nseindia.com/content/cm/NSE_CM_security_{DDMMYYYY}.csv.gz`, one gzip CSV per trading day, 2024-02-05 to 2026-11-20 (694 files, 691 MB) in `data/raw/market/mii/`. Key columns: `TckrSymb`, `SctySrs`, `ISIN`, `ParVal`, `IssdCptl` (issued share count), `ListgDt`, `RmvlDt`. `FreeFltCptl` is empty for every EQ row (no free float). Parsed by `market.parse_mii` into `data/build/market/shares.parquet` (rows of the symbol and series that traded that day) and served by `api.shares_outstanding()`.
