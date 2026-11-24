# NSE Point-in-Time Equity Data Bank

A deterministic, source-traceable Python package that serves as the universe for equity strategies: NSE bhavcopy
since 2007-01-02, split/bonus-adjusted prices, delivery quantity, official values and point-in-time membership of 27
verified equity indices. Each claim is backed by a check in `nseuniverse verify`; anything that cannot be verified is
refused by the API instead of estimated.

> Audited in-house only; the independent review (OPEN_ISSUES A8) is outstanding. Known limits: [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).
> On 2026-11-24 the data bank was cut to this core. Price bands, ASM/GSM, F&O, deals, impact cost, shares outstanding,
> dividends/total return, 30 unverified indices and non-equity index values were removed from the build; git tag
> `full-2026-11-24` and the `archive/` folder hold them.

## What is in it (as of 2026-11-24)

| Item | State |
|---|---|
| **Bhavcopy, 2007-01-02 to 2026-11-20** | 4,930 trading days, 9,331,281 rows, both NSE formats. Every row is re-read by an independent parser and compared exactly: 0 differences. 2004-2006 is archived (not served). |
| **Securities and identity** | 8,024 securities (symbol and ISIN history, renames followed). `sec_id` is not stable across rebuilds: key anything durable by symbol plus ISIN. |
| **Adjusted prices (`adjust_mode="splits"`)** | Splits, bonuses, consolidations and rights, from 2007-01-01. Every share action is tested against the price move NSE printed. No dividends, no total return. SME securities and the securities in `api.unreliable_adjusted()` are refused an adjusted series (raw prices are exact). |
| **Delivery** | `api.delivery()`: traded and deliverable quantity and delivery % for every bhavcopy day (8.6 M rows). Traded quantity equals the bhavcopy volume on 99.93% of rows. |
| **Index values** | 27 equity indices, 163,135 index-days from two NSE sources that agree on every overlapping day (0 conflicts). |
| **Index membership** | 27 verified equity indices, **from 2010-01-01** (or the index's launch if later), 40 verified windows, 0 contradictions, 0 subset violations. Nifty 50, Next 50, 100, Bank, PSU Bank, Pharma, FMCG, Realty and Metal are verified from 2010. `api.coverage()` lists every window. |

## Use

```python
import nseuniverse.api as nse

nse.bhavcopy_day("2015-03-02")                      # every row NSE published that day
nse.securities(as_of="2012-06-29")                  # equity securities trading then
nse.prices("INFY", "2012-01-02", "2020-12-31")      # adjust_mode="splits"; adj_return is NaN on documented-event days
nse.prices("INFY", "2012-01-02", "2020-12-31", None)  # as published
nse.delivery("INFY", "2020-01-01", "2020-03-31")
nse.index_values("Nifty 50", "2010-01-01", "2020-12-31")
nse.index_members("Nifty 50", "2024-01-15")         # raises CoverageError outside verified dates
nse.index_members("Nifty 50", "2008-06-02", backfill=True)   # opt-in proxy list (see below)
nse.index_members("Nifty Midcap150", "2011-06-01", reconstruct=True)   # UNVERIFIED rule-based rebuild, see below
nse.index_start_dates(); nse.reconstruction_accuracy("Nifty 50")      # start dates; how close the rebuild is to the verified lists
nse.coverage()                                      # what is verified, per index
nse.adjustment_gaps("TATAMOTORS")                   # known breaks in the adjusted series
nse.caveats(); nse.explain(["INFY"], "2012-01-02", "2020-12-31", index="Nifty 50")
```

Symbols resolve as of the query end date and follow renames back (`INFY` <- `INFOSYSTCH`).

## The rules that matter for a backtest

1. **Documented event days are masked by default.** On a demerger/scheme day the feed cannot quantify
   (`ON_ACTION_DAY`), `prices()` sets `adj_return` to NaN (`mask_gaps="events"`). Overnight moves nothing explains
   (`UNEXPLAINED`) are flagged but **not** masked, because they can be real crashes (Yes Bank 2020, Satyam 2009) and
   masking them would hide real losses. `mask_gaps="all"` masks both, `"none"` neither. All flagged days are in
   `frame.attrs['flagged']`. A NaN return is not zero: count the masked days and report them. Do not compound
   `adj_close` across a flagged day.
2. **Backfill is opt-in and is not membership.** `index_members(idx, date, backfill=True)` returns, for dates from
   2007-01-01 up to the index's first verified day, the first verified list restricted to securities already trading
   (`BACKFILLED_UNVERIFIED`, with a warning). It carries survivorship and look-ahead bias.
   **Reconstruction is a second, separate opt-in** (`reconstruct=True`, `nseuniverse reconstruct`; needs
   `archive/raw/market/mii`). For the 16 size-rank indices it ranks stocks by 6-month average market capitalisation each
   April/October from 2007-04 with the current methodology bands, and returns `RECONSTRUCTED_UNVERIFIED` lists with the
   rank and an imputed-size flag. Shares are the 2024-26 issued capital carried back through splits and bonuses (traded-value
   imputation for delisted stocks), free float is ignored, and the 11 sectoral indices are refused (no sector data). It
   only fills dates that are not verified. Measured overlap with NSE's verified lists is in
   `api.reconstruction_accuracy()`: good for wide indices (Nifty 500 about 0.7-0.86 Jaccard, LargeMidcap 250 about 0.85-0.91), poor
   for narrow ones (Nifty 50 about 0.5-0.65, Next 50 and Midcap 50 about 0.2-0.5). 2007-2009 cannot be scored and is expected to be weaker.
3. **Adjusted prices before 2007-01-01 do not exist** in this bank. `as_of=` limits which corporate actions are applied,
   not which price rows are returned.
4. **No announcement dates**: NSE's feed has ex-dates only.
5. **Corporate-action feed age**: refresh it after each month-end (download in a browser, save into
   `data/raw/corporate_actions`, rebuild). Splits after the feed end show up as one-day crashes.
6. **Unquantified events** (about 90 rights/unparsed events and about 100 demergers since 2007) stay unadjusted and are
   masked on their day; the stock stays in the universe. Five demergers carry a curated **estimated** factor
   (`DEMERGER_EST`, value at the new company's first listing, accurate to a few percent; `demerger_estimates.csv`):
   Bajaj Holdings 2008, Alembic 2011, Triveni 2011, ABFRL 2025, SKF India 2025. Their event day is flagged
   `DEMERGER_ESTIMATED` and masked by default.

## Workflow

```bash
pip install -e .[dev]
nseuniverse fetch all        # only command that uses the network; resumable; raw files never overwritten
nseuniverse build            # offline: data/raw + data/curated -> data/build
nseuniverse verify           # integrity gate (14 checks); exit code 1 on any FAIL
nseuniverse determinism      # two builds into temp dirs must have identical checksums
pytest                       # code tests on small synthetic fixtures (fast, offline)
```

`data/raw/` holds exactly what NSE served, with a SHA-256 manifest (`manifest.csv`). `data/curated/` holds hand-entered
facts, each citing its source. `data/build/` is derived and can be deleted. Raw bhavcopies, press releases and the
delivery files are git-ignored or untracked (hundreds of MB) and live in Google Drive; a fresh clone fails the manifest
check until they are restored. `archive/` holds what was cut from the bank (see `archive/README.md`).

See `docs/METHODOLOGY_AND_LIMITATIONS.md` for the method, `docs/SOURCES.md` for where each input comes from, and
`docs/AUDIT_REPORT.md` for the in-house audit. METHODOLOGY, SOURCES, AUDIT_REPORT, HANDOFF and OPEN_ISSUES still describe the
removed items in places; each carries a note at the top. The full version is git tag `full-2026-11-24`.
