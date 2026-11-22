# NSE Point-in-Time Universe

A deterministic, source-traceable Python package for NSE equity history: every bhavcopy row since
2004, corporate-action-adjusted prices, official index values, and index membership. Each claim is
backed by a check in `nseuniverse verify`; anything that cannot be verified is refused by the API
instead of estimated.

## What is in it (as of 2026-11-22)

| Requirement | State | Evidence |
|---|---|---|
| **All bhavcopy data, 2004 → today** | **Complete.** 5,684 trading days, 9,968,593 rows (2004-01-01 through 2026-11-19), both NSE formats, every column NSE published for that era (older eras simply did not publish ISIN, trade counts, etc.; those stay null). | Every row is re-read by an independent parser and compared exactly: 0 differences. The 24 days NSE published in both formats are identical. |
| **All NSE equity securities, adjusted** | **Raw: complete.** 8,182 securities (4,826 equity/SME-equity), stable `sec_id`, ticker/ISIN history. **Adjusted: verified from 2007-01-01.** | Each split/bonus is tested against the price move NSE printed; 1,277 pass, 114 are too small to test, 15 are rejected (the feed claims an action the prices do not show). |
| **Official index values** | **238 indices** from two independent NSE publications (daily files from 2012, history API from each index's base date), including price, total return, PE/PB/yield (869,785 index-days). | The sources agree on 99.6% of overlapping days; the 1,061 disagreements are flagged `conflict=True` with the other source's value, never hidden. |
| **Index membership from 2007-01-01** | **27 indices verified (20 anchored + 7 composite), 45 active VERIFIED coverage windows.** `NIFTY50`, `NIFTYNEXT50`, `NIFTY100`, `NIFTYBANK`, and `NIFTYPHARMA` are each verified `2007-01-02` → `2026-11-19` (4,929 trading days); broad market and sectoral indices (`NIFTY200`, `NIFTY500`, `NIFTYMIDCAP150`, `NIFTYSMALLCAP250`, `NIFTYMIDCAP50`, `NIFTYSMALLCAP100`, `NIFTYSMALLCAP50`, `NIFTYFMCG`, `NIFTYIT`, `NIFTYAUTO`, `NIFTYFINANCIALSERVICES`, `NIFTYMEDIA`, `NIFTYMETAL`, `NIFTYREALTY`, `NIFTYPSUBANK`, and 7 composite benchmarks) are verified from their respective restructuring / launch dates with **0 contradictions** across the entire dataset. Dual-class shares (`TATAMTRDVR`) are verified through `index_dual_class.csv`; the audit confirmed every one of those rows is load-bearing. Zero-price demerger dummies (Siemens Energy, ITC Hotels, Jio Financial, etc.) are listed in `index_size_exceptions.csv` as documentation only: the build counts real members, and the audit showed dropping any of those rows changes nothing. The remaining 30 indices in `data/curated/index_universe.csv` lack historical workbook sheets and legitimately remain `UNVERIFIED` per strict PIT rules. | Exactly the official number of real members on every trading day, every member traded within ±3 sessions, and the set equals NSE's official list today with 0 subset violations across all 4,929 trading days. |

## Read this before relying on it

1. **Adjusted prices before 2007-01-01 are not verified.** The corporate-action feed on hand has
   almost no splits or bonuses before then (2004: none; 2005: two). `api.prices(adjust_mode=...)`
   refuses earlier dates unless you pass `allow_unverified=True`.
2. **Membership is verified across 27 indices (45 verified windows).** NSE's inclusion/exclusion workbook lists changes after
   launch but not the launch lists, and it names companies, not symbols. The historical changes have been curated and verified against official press releases. See `api.coverage()` for exactly which dates and indices are trustworthy.
3. **231 securities carry documented breaks** after 2007-01-01 (demergers, schemes and SME/ETF unit events
   the feed does not quantify): `api.adjustment_gaps()`.
4. **No announcement dates exist** in NSE's feed (`caBroadcastDate` is empty on all 43,816
   records). Adjustments use ex-dates, which is point-in-time safe: an action cannot affect prices
   before its ex-date. `as_of=` applies only actions with ex-date ≤ that date.

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
