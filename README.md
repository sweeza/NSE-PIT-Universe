# NSE Point-in-Time Universe

A deterministic, source-traceable Python package for NSE equity history: every bhavcopy row since
2004, corporate-action-adjusted prices, official index values, and index membership. Each claim is
backed by a check in `nseuniverse verify`; anything that cannot be verified is refused by the API
instead of estimated.

## What is in it (as of 2026-11-22)

| Requirement | State | Evidence |
|---|---|---|
| **All bhavcopy data, 2004 → today** | **Complete.** 5,684 trading days, 9,968,593 rows (2004-01-01 through 2026-11-19), both NSE formats, every column NSE published for that era (older eras simply did not publish ISIN, trade counts, etc.; those stay null). | Every row is re-read by an independent parser and compared exactly: 0 differences. The 24 days NSE published in both formats are identical. |
| **All NSE equity securities, adjusted** | **Raw: complete.** 8,136 securities (4,780 equity/SME-equity), stable `sec_id`, ticker/ISIN history. **Adjusted: verified from 2007-01-01.** | Each split/bonus is tested against the price move NSE printed; 1,343 pass, 112 are too small to test, 6 are rejected (the feed claims an action the prices do not show). |
| **Official index values** | **238 indices** from two independent NSE publications (daily files from 2012, history API from each index's base date), including price, total return, PE/PB/yield (869,785 index-days). | The sources agree on 99.6% of overlapping days; the 1,061 disagreements are flagged `conflict=True` with the other source's value, never hidden. |
| **Index membership from 2007-01-01** | **27 indices verified (20 anchored + 7 composite), 40 VERIFIED coverage windows.** `NIFTY50`, `NIFTYNEXT50`, `NIFTY100`, `NIFTYBANK`, `NIFTYPSUBANK` and `NIFTYPHARMA` are each verified `2007-01-02` → `2026-11-19` (4,929 trading days); broad market and sectoral indices (`NIFTY200`, `NIFTY500`, `NIFTYMIDCAP150`, `NIFTYSMALLCAP250`, `NIFTYMIDCAP50`, `NIFTYSMALLCAP100`, `NIFTYSMALLCAP50`, `NIFTYFMCG`, `NIFTYIT`, `NIFTYAUTO`, `NIFTYFINANCIALSERVICES`, `NIFTYMEDIA`, `NIFTYMETAL`, `NIFTYREALTY`, and 7 composite benchmarks) are verified from their respective restructuring / launch dates with **0 contradictions** across the entire dataset. Dual-class shares (`TATAMTRDVR`) are verified through `index_dual_class.csv`; the audit confirmed every one of those rows is load-bearing. Zero-price demerger dummies (Siemens Energy, ITC Hotels, Jio Financial, etc.) are listed in `index_size_exceptions.csv` as documentation only: the build counts real members, and the audit showed dropping any of those rows changes nothing. The remaining 30 indices in `data/curated/index_universe.csv` lack historical workbook sheets and legitimately remain `UNVERIFIED` per strict PIT rules. | Exactly the official number of real members on every trading day, every member traded within ±3 sessions, and the set equals NSE's official list today with 0 subset violations across all 4,929 trading days. |

## Know the limits: `api.caveats()` and `api.explain()`

`api.caveats()` lists every known limit of the data (19 flags in six categories) with its severity, what it does to a
backtest, how to handle it, which column or function shows it, and how much of this build it touches.
`api.caveats("PRICES")` filters by category. `api.explain(symbols, start, end, index=None)` returns only the flags that
apply to your selection, with the securities and dates concerned (SME and curated unreliable adjusted prices,
documented breaks, unquantified corporate actions, unverified or backfilled membership windows, index-value
conflicts, a stale corporate-action feed). Run it before trusting a backtest. The catalogue is `nseuniverse/caveats.py`.

## Market-activity data (added 2026-11-23)

Daily NSE files fetched into `data/raw/market/` (2.9 GB, 34,938 files in the manifest, not committed to git) and built into `data/build/market/`:

| Table / API | Source | Coverage | Check |
|---|---|---|---|
| `api.delivery(symbols, start, end)`: traded and deliverable quantity, delivery % | NSE `MTO` security-wise delivery file | every bhavcopy day, 2004-01-01 to 2026-11-20 (9.2 M rows) | traded quantity equals the bhavcopy volume on 99.93% of rows; deliverable never above traded; percent matches its own quantities |
| `api.price_band(symbol, date)`: circuit limit | NSE security list (daily, 2020-01 on) and the daily band-change files (2010 on) | exact from 2020; before that the band after the last recorded change, refused if none was recorded | 2 change files with another layout (2017-11-14, 2021-03-30) are skipped and listed |
| `api.asm_gsm(date)`: ASM/GSM and other surveillance remarks | remarks column of the security list | 2020 on | none beyond parsing |
| `api.fo_ban(date)`: securities in the F&O ban period | NSE `fo_secban` files | 2010 on; an empty frame means NIL | files without a list are refused |
| `api.fo_eligible(date)`: stocks with futures and/or options contracts that day | NSE derivatives bhavcopy (legacy and UDiFF) | 5,681 days, 2004 to 2026-11-20 (50 to 267 stocks a day) | derived from contracts present, not NSE's official eligible list |
| `api.deals(symbols, start, end, kind=None)`: bulk deals, block deals, and short selling | NSE report archive (64 annual windows, real browser session) and daily snapshots | bulk 2004-01-04.., block 2005-11-17.., short 2008-02-01.. to 2026-11-20 (359,062 rows) | qty > 0 on 100.000% of rows (1 null `"-"`), price inside bhavcopy low–high on 99.969% (259,212/259,293), 104 unattached |
| `api.impact_cost(symbols, start, end)`: liquidity category (1/2/3) and 6-month rolling mean impact cost (%) for ₹1 lakh order | NSE Clearing monthly `C_CATG_<MMM><YYYY>.T01` (not daily) | 47 months: continuous 2023-10..2026-11 + 9 earlier months (2019-03, 2021-01..06, 2023-05..06); 532,386 rows (172,282 with numeric impact cost) | 0 negative values, 0 above 100% (range 0.00%–32.01%), 52.9% attached overall (250,587 unattached, mostly non-trading debt/SG series); blank values never filled |

Not included: market cap, free float. Fetch with `python -m nseuniverse.cli fetch market` (also part of `update`).

## Read this before relying on it

1. **Adjusted prices before 2007-01-01 are not verified.** The corporate-action feed on hand has
   almost no splits or bonuses before then (2004: none; 2005: two). `api.prices(adjust_mode=...)`
   refuses earlier dates unless you pass `allow_unverified=True`.
2. **Membership is verified across 27 indices (40 verified windows).** NSE's inclusion/exclusion workbook lists changes after
   launch but not the launch lists, and it names companies, not symbols. The historical changes have been curated and verified against official press releases. See `api.coverage()` for exactly which dates and indices are trustworthy.
3. **169 securities carry documented breaks** after 2007-01-01 (demergers, schemes and SME/ETF unit events
   the feed does not quantify): `api.adjustment_gaps()`.
3b. **SME-platform securities (series SM/ST) have unreliable adjusted prices.** The NSE corporate-action feed holds no
   records for them, so none of their splits or bonuses is applied (97 flagged overnight breaks, and an unknown number
   of unflagged ones). `api.prices(..., adjust_mode=...)` marks them `adj_reliable=False` and warns; `api.sme_securities()`
   lists them; `api.unreliable_adjusted()` lists them plus 9 curated names with known wrong adjusted history
   (`data/curated/adjustment_unreliable.csv`: 5 ETFs with non-round unit ratios, GULFPETRO, AHLEAST, SUNTV, CCAVENUE), all
   marked `adj_reliable=False` with a warning. Use raw prices or leave them out. ETF unit splits (55 added from NSE's own prices, `data/curated/actions_price_evidenced.csv`)
   are applied; 5 UTI/Axis/Nippon ETFs with non-round ratios and SETFGOLD are not.
3c. **Backfill is opt-in and not membership.** `api.index_members(idx, date, backfill=True)` returns, for dates from 2007-01-01
   to an index's first verified day, the first verified list restricted to securities already trading, marked
   `BACKFILLED_UNVERIFIED` (survivorship and look-ahead bias; stress tests only).
4. **No announcement dates exist** in NSE's feed (`caBroadcastDate` is empty on all 43,816
   records). Adjustments use ex-dates, which is point-in-time safe: an action cannot affect prices
   before its ex-date. `as_of=` applies only actions with ex-date ≤ that date.

## Audit status (2026-11-22) and thin spots

An independent audit (`docs/AUDIT_REPORT.md`, scripts in `audit/`) has covered reproducibility, raw-source authenticity for three of the four unverified inputs, bhavcopy and calendar, identity, membership (including 207 of 216 archived NSE constituent lists), the verify gate (mutation tests), adjustment factors for a 60-security sample (92 of 92 events match an independent rebuild), the dividend entries used by `total_return` (six defects found and fixed), index values, and look-ahead. Not yet done: a third-party comparison of adjusted prices, a review of the rejected actions and unexplained moves, a re-download sample of raw files. What to keep in mind:

- Membership 2007-05 to 2009-12 has a single archived capture (Nifty 50, 2007-04-30); it rests on the workbook, press releases and daily size checks. Back-test from 2010 if you need fully confirmed membership.
- Nifty 200 and Nifty 500 membership has no archived list before 2014.
- `IndexInclExcl.xls` has no live NSE source, so its origin is unverified. REIT inclusions of 2026-09-30 are absent from the NSE CSVs captured in October 2026; the build follows the press release.
- `total_return` uses cash dividends parsed from free text. Unparseable ones are left out (never estimated), and a dividend that cannot be placed on its ex-date (no trading within 7 days) is not applied.
- 361 index-days differ by more than 0.1% between the daily files and the history API (141 of them Nifty 100 Low Vol 30). Where they differ the history series tracks the parent index better; use `source="history"` or `mask_conflicts=True`.
- `as_of=` limits which corporate actions are applied; it does not hide price rows dated after `as_of`. Restrict the date range yourself.
- A date range with no trading day raises `CoverageError` (it used to return an empty frame).
- `sec_id` labels are not stable across rebuilds: key anything durable by symbol plus ISIN.
- No index weights, liquidity or circuit limits, bid-ask or costs are in the data.

## Use

```python
import nseuniverse.api as nse

nse.bhavcopy_day("2015-03-02")                      # every row NSE published that day
nse.securities(as_of="2010-06-30")                  # equity securities trading then
nse.prices("INFY", "2012-01-02", "2020-12-31",
           adjust_mode="total_return")              # None | "splits" | "total_return"
nse.index_values("Nifty 50", "2010-01-01", "2020-12-31")
nse.index_members("Nifty 50", "2024-01-15")         # raises CoverageError outside verified dates
nse.coverage()                                      # what is verified, per index
nse.adjustment_gaps("TATAMOTORS")                   # known breaks in the adjusted series
nse.prices("INFY", "2012-01-02", "2020-12-31", "splits",
           mask_gaps=True)                          # adj_return is NaN on days with a break (adj_gap=True)
```

Symbols resolve as of the query end date and follow renames back (`INFY` ← `INFOSYSTCH`).

**Flagged days.** `prices()` and `index_values()` emit a `DataQualityWarning` whenever the result contains days the data cannot support, and list them in `frame.attrs['flagged']` with a class: `ON_ACTION_DAY` (documented demerger or similar event whose adjustment is not quantifiable), `UNEXPLAINED` (an overnight move nothing in the feed explains; **this can be a real crash**, such as Yes Bank 2020, so masking it removes a real loss) or `SOURCE_CONFLICT` (NSE's two index sources disagree; `index_values` adds `ret` and `ret_unreliable`, and `mask_conflicts=True` blanks `ret` on those days). A NaN return is not zero: count the masked days (`len(frame.attrs['flagged'])`) and report them with the backtest rather than letting a portfolio treat them as 0.

## Workflow

```bash
pip install -e .[dev]
nseuniverse fetch all        # only command that uses the network; resumable; raw files never overwritten
nseuniverse build            # offline: data/raw + data/curated -> data/build
nseuniverse verify           # integrity gate; exit code 1 on any FAIL
nseuniverse determinism      # two builds into temp dirs must have identical checksums
pytest                       # code tests on small synthetic fixtures (fast, offline)
```

`data/raw/` holds exactly what NSE served, with a SHA-256 manifest (`manifest.csv`). `data/curated/`
holds hand-entered facts, each citing its source. `data/build/` is derived and can be deleted.
Raw bhavcopies and press releases are git-ignored (hundreds of MB); the manifest records their hashes.

See `docs/METHODOLOGY_AND_LIMITATIONS.md` for the method and `docs/SOURCES.md` for where each input comes from.
