# NSE Point-in-Time Equity Data

Daily prices and delivery, point-in-time membership of 29 NSE equity indices, index levels and the bhavcopy archive,
built from files NSE published. Audited in-house only; no independent review has been recorded.

## Layout

| Folder | Holds | Rule |
|---|---|---|
| `data/raw/` | what NSE published: `bhavcopy/`, `delivery/`, corporate actions, press releases, index files | never edited; SHA-256 in `manifest.csv` |
| `data/curated/` | hand-entered facts | each cites a file in `data/raw/` |
| `data/final/` | the tables you use | rebuilt by `nseuniverse build`; `_work/` holds intermediates |
| `archive/` | 2004-2006 bhavcopy and delivery files (not built or served) and other material cut from the bank | |
| `nseuniverse/`, `tests/`, `tools/` | the code | |

## The tables in `data/final/`

| File | One row per | Columns |
|---|---|---|
| `prices/prices_YYYY.parquet` | date, symbol, series (2007-01-02 onward) | OHLC, `prev_close`, `volume`, `turnover`, `trades`, `deliv_qty`, `deliv_pct`, `price_factor`, `volume_factor`, `adj_gap` |
| `membership.csv` | index and security, per verified span | `index_key`, `sec_id`, `symbol`, `isin`, `from_date`, `to_date` (inclusive) |
| `indices.parquet` | index and day | official index levels |

`isin` is blank where NSE's early files give none for that symbol (18 rows).

- **Raw prices** are the columns as stored. **Adjusted** price = price x `price_factor`; adjusted volume = `volume` x
  `volume_factor`. Splits, bonuses, consolidations and rights only; no dividends.
- **`price_factor` is NaN** for securities where adjusted prices are not offered (SME platform and the list in
  `data/curated/adjustment_unreliable.csv`).
- **`adj_gap` is not empty** on a day where the adjusted series has a break. For `ON_ACTION_DAY` and
  `DEMERGER_ESTIMATED` do not treat that day's change as a return. `UNEXPLAINED` moves can be real crashes.
- **`sec_id` is renumbered on every rebuild.** Join the tables on it within one build; save symbol plus ISIN.
- `series` includes non-equity instruments; filter to the series you want (usually `EQ`, `BE`).

From Python, `import nseuniverse.api as nse`: `nse.prices(...)`, `nse.delivery(...)`, `nse.index_members(index, date)`,
`nse.index_values(index)`, `nse.coverage()`, `nse.caveats()`.

## Limitations

- Membership exists only where verified (`nse.coverage()`), from 2010 or later. `index_members(..., backfill=True)` is an
  opt-in proxy with survivorship bias; it is not in `membership.csv`.
- No index is verified before its public launch (`membership.LAUNCHED` and `FLOORS` cite the notices). Several indices
  start later than their launch because the held sources do not reach back further.
- Some name-to-ticker rows in `data/curated/press_name_symbol.csv` were machine-extracted. 20 wrong ones were removed on
  2026-11-26 by a screen that only catches names with no word in common; the rest have not been checked by hand.
- Some demergers and rights issues cannot be quantified and stay unadjusted. Five demergers use estimated factors.
- NSE's corporate-action feed has ex-dates only (no announcement dates) and has to be downloaded by hand after each
  month-end into `data/raw/corporate_actions/`.
- Index levels before an index's launch are NSE's back-calculation.
- Two weekend sessions (2010-05-16, 2012-11-11) are partial.
- Indices without verified history (Private Bank, Healthcare, Oil & Gas and others) are not included.
- Microcap 250 is replayed back from Total Market minus Nifty 500 (no Microcap list of the build date is held). Four
  archived NSE lists in `data/raw/constituents_archive/` (2021, 2024, 2025, 2026) matched exactly when it was added.

## Commands

```bash
pip install -e .[dev]
nseuniverse fetch all    # the only command that uses the network
nseuniverse build        # data/raw + data/curated -> data/final
nseuniverse verify       # 14 integrity checks; exit 1 on any FAIL
nseuniverse update       # fetch recent days, build, verify
pytest -q                # short code tests, offline
python tools/nubra_check.py fetch      # optional cross-check against Nubra; you log in at its prompt
python tools/nubra_check.py compare
```

Large raw files are not in git; they live in Google Drive.
