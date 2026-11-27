# Restructure plan (agreed 2026-11-26)

## What the bank is for
1. Daily OHLCV and delivery for stocks, raw and split/bonus-adjusted.
2. Point-in-time membership of the 27 verified equity indices.
3. The bhavcopy archive.
Index levels are kept for benchmarks. The code is kept so the data can be updated and rechecked.

## Three layers
| Layer | Holds | Rule |
|---|---|---|
| `data/raw/` | what NSE published | never edited |
| `data/curated/` | hand-entered facts | each cites a file in `data/raw/` |
| `data/final/` | the tables you use | rebuilt from the two above; `_work/` inside it holds intermediates |

Final tables: `prices/prices_YYYY.parquet` (OHLCV, delivery, adjustment factor), `membership.csv`
(index, symbol, ISIN, from, to), `indices.parquet`.

## Prune
- Cut market data in `archive/raw/market/`: F&O bhavcopy, security master, security lists, deals, impact cost,
  band changes, F&O bans. The 2004-2006 bhavcopy and delivery files stay, as part of the bhavcopy archive.
- The rule-based membership rebuild (code, test, API option).
- `audit/`, `999 dump/`, `PLAN.md`, `CHECKPOINT.md` and the old documents in `docs/`; limitations move into `README.md`.
- `Project Requirement.docx` is left alone.

Files outside git cannot be restored from the repository, so their deletion is confirmed separately.

## How we know nothing essential changed
1. Full `nseuniverse verify` before any change.
2. The same after the restructure: no FAIL, same bhavcopy row count, no index loses verified days except the
   deliberate corrections below.

## Tests
One short test per behaviour that matters (parsing, adjustment, identity, membership replay, API refusals).
No tests for removed features, no duplicates of what `verify` already checks on real data.

## Status 2026-11-26
Done: restructure, pruning (including the files outside git), tests, and the coverage corrections below.

## Coverage corrections (all applied)
- Bank, Pharma: expanded-size allowance made open-ended.
- Metal and PSU Bank: documented periods with more or fewer stocks than usual added to `index_size_exceptions.csv`.
- Launch dates: nothing is verified before launch (`membership.py`: `LAUNCHED`, `FLOORS`).
- Nifty 500 from 2010-01-04: four company names mapped to the ticker of the time, one wrong mapping corrected
  (Jay Shree Tea pointed at Sterlite), Asian Hotels mapped to its pre-demerger ticker, and two stocks with no trades in
  August 2013 recorded in `index_no_trade.csv`.

## Open
- Nubra cross-check (needs the SDK and the owner's login).
- Hand check of the machine-extracted rows in `press_name_symbol.csv`.
