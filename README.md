# NSE Point-in-Time Universe

A deterministic, source-traceable Python package for NSE equity history: every bhavcopy row since
2004, corporate-action-adjusted prices, official index values, and index membership. Each claim is
backed by a check in `nseuniverse verify`; anything that cannot be verified is refused by the API
instead of estimated.

## What is in it (as of 2026-11-15)

| Requirement | State | Evidence |
|---|---|---|
| **All bhavcopy data, 2004 → today** | **Complete.** 5,680 trading days, 9,953,639 rows, both NSE formats, every column NSE published for that era (older eras simply did not publish ISIN, trade counts, etc.; those stay null). | Every row is re-read by an independent parser and compared exactly: 0 differences. The 24 days NSE published in both formats are identical. |
| **All NSE equity securities, adjusted** | **Raw: complete.** 8,148 securities (4,825 equity/SME-equity), stable `sec_id`, ticker/ISIN history. **Adjusted: verified from 2007-01-01.** | Each split/bonus is tested against the price move NSE printed; 1,277 pass, 114 are too small to test, 15 are rejected (the feed claims an action the prices do not show). |
| **Official index values** | **238 indices** from two independent NSE publications (daily files from 2012, history API from each index's base date), including price, total return, PE/PB/yield. | The sources agree on 99.6% of overlapping days; the 1,061 disagreements are flagged `conflict=True` with the other source's value, never hidden. |
| **Index membership from 2007-01-01** | **Nifty 50, Nifty Next 50 and Nifty 100 are each verified 2007-01-02 → today, one window each** (decision 2026-11-16: every index is verified from 2007-01-01 only, the date from which adjusted prices are verified; `membership.FLOORS`). Days before 2007-01-01 are out of scope and refused. Nifty 50 held 51 securities of 50 companies 2016-04-01 → 2017-09-28 (Tata Motors DVR, `index_dual_class.csv`); Nifty 100 held 101 securities of 100 companies while the DVR was in it (2016-04-01 → 2020-06-25, 2023-09-29 → 2024-08-29). On some days NSE also held demerged entities at zero price under dummy symbols (Siemens Energy, ITC Hotels, Jio Financial, Tata Motors CV, Kwality Wall's, the four Vedanta spin-offs): there the real members are verified exactly and the extras are taken from the cited releases in `data/curated/index_size_exceptions.csv`. Some company-name links are inferred from NSE ticker history, each marked in `data/curated/name_aliases.csv`. The other in-scope indices (NSE's Broad Market and Sectoral categories, `data/curated/index_universe.csv`), including Nifty 500 and Midsmallcap 400: **not verified** (see below). | Exactly the official number of real members on every trading day, every member traded, and the set equals NSE's official list today. |

## Read this before relying on it

1. **Adjusted prices before 2007-01-01 are not verified.** The corporate-action feed on hand has
   almost no splits or bonuses before then (2004: none; 2005: two). `api.prices(adjust_mode=...)`
   refuses earlier dates unless you pass `allow_unverified=True`.
2. **Membership is verified for three indices (Nifty 50, Nifty Next 50, Nifty 100).** NSE's inclusion/exclusion workbook lists changes after
   launch but not the launch lists, and it names companies, not symbols. Mapping ~370 old company
   names needs reviewed aliases. See `data/build/membership/unresolved.csv` for the worklist and
   `api.coverage()` for exactly which dates are trustworthy.
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
