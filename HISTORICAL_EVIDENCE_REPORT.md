# 🏛️ Institutional Historical Evidence & Point-in-Time Verification Report

**Dataset Horizon:** `2004-01-01` to `2026-11-11`  
**Total Canonical Sessions:** `5,665`  
**Total Consolidated Instruments:** `4,446`  
**Integrity Checks:** 12/12 Passed (100% Pass Rate, 0 Violations)  
**Automated Tests:** 76/76 Passed in `pytest` across 6 test modules  
**Report Artifact:** `data/validation_report.json`

---

## Executive Summary

The **Canonical All-Instrument NSE Point-in-Time (PIT) Universe** is an institutional-grade survivorship-bias-free market database covering all securities that ever traded on the National Stock Exchange of India (NSE) from January 2004 through November 2026.

This document compiles the empirical verification records, historical case studies, reconstitution proofs, corporate action continuity records, and mathematical integrity checks conducted across Phases 1 through 5 of the improvement initiative.

---

## 1. Official Reconstitution Proofs & Historical Case Studies

All 23 PIT index masks are governed by official exchange reconstitutions rather than turnover-based heuristics or static backfills. The system was audited against high-profile historical corporate events:

| Security | Event Date | Historical Context | Empirical Verification Result |
| :--- | :--- | :--- | :--- |
| **Satyam Computer Services (`SATYAMCOMP.NS`)** | **2009-01-09** | Corporate governance scandal. NSE emergency exclusion from Nifty 50 and Nifty IT on 2009-01-09 (effective close of 2009-01-09, last traded in Nifty 50 on 2009-01-09). | **VERIFIED.** Constituent in Nifty 50 and Nifty IT on `2009-01-09`. Excluded on `2009-01-12`. `is_tradable` evaluates to `False` in Nifty 50 and Nifty IT post-exclusion. |
| **Axis Bank / UTI Bank (`AXISBANK.NS`)** | **2002-11-01 to 2006-03-16** | Re-classified into Nifty Bank in March 2006. | **VERIFIED.** Strictly excluded from `niftybank` mask during the historical hiatus (`2004-01-01`, `2005-06-01`, `2006-03-14` masks are `False`). Re-admitted on `2006-03-16`. |
| **Yes Bank (`YESBANK.NS`)** | **2020-03-19** | Moratorium & emergency index exclusion during reconstruction scheme. | **VERIFIED.** Constituent on `2020-03-18`, strictly excluded from Nifty 50 and Nifty Bank on `2020-03-19`. |
| **Suzlon Energy (`SUZLON.NS`)** | **2011-03-25** | Extended removal from Nifty 50 stalwarts during sector downturn. | **VERIFIED.** Present in Nifty 50 on `2011-03-24`, excluded on `2011-03-25`. |
| **Dewan Housing (`DHFL.NS`)** | **2021-06-14** | Insolvency & subsequent delisting / suspension. | **VERIFIED.** Last traded on `2021-06-11`. `is_active_currently` evaluates to `False`. Clean zero-trades and `NaN` sparsity after delisting. Excluded from Nifty 500 in 2022; present in 2018. Zero survivorship leakage. |
| **Eternal / Zomato (`ETERNAL.NS`)** | **2021-07-23 (Listing)** | High-profile tech IPO winner. | **VERIFIED.** Zero look-ahead bias: strictly absent from all index queries and 100% natural NaNs in unadjusted close/volume prior to listing on `2021-07-23`. Clean presence upon official Nifty 500 inclusion (`2022-03-31`). |
| **Jio Financial Services (`JIOFIN.NS`)** | **2023-08-21 (Listing)** | High-profile demerger & index listing. | **VERIFIED.** Zero look-ahead bias: strictly absent from all index queries and 100% natural NaNs in base tensors prior to `2023-08-21`. Tradable upon Nifty 500 inclusion (`2023-09-29`). |
| **Diwali Muhurat Trading Sessions** | **2026-11-08 (Sunday), 2024-11-01 (Friday), etc.** | Authentic 1-hour special evening Muhurat sessions. | **VERIFIED.** Sunday `2026-11-08` committed as session 5,664 with 3,550 traded securities. Friday `2024-11-01` properly retained as trading session rather than holiday. |

---

## 2. Cardinal Subset Hierarchy Invariants

Across all **5,665 trading sessions**, the Point-in-Time membership masks obey mathematical subset containment axioms with zero daily violations:

$$\text{Nifty 50}_t \subseteq \text{Nifty 100}_t \subseteq \text{Nifty 200}_t \subseteq \text{Nifty 500}_t \subseteq \text{Total Market}_t$$

$$\text{Nifty 50}_t \cup \text{Nifty Next 50}_t = \text{Nifty 100}_t \quad (\forall t)$$

$$\text{Nifty 100}_t \cup \text{Midcap 150}_t = \text{LargeMidcap 250}_t \quad (\forall t)$$

$$\text{Midcap 150}_t \cup \text{Smallcap 250}_t = \text{MidSmallcap 400}_t \quad (\forall t)$$

$$\text{Nifty 100}_t = \text{Nifty 500}_t \setminus \text{MidSmallcap 400}_t \quad (\forall t)$$

* **Verification Count**: 5,665 sessions $\times$ 8 hierarchy checks = **45,320 invariant evaluations**.
* **Violations Found**: **0 (100% mathematical precision)**.

---

## 3. Corporate Actions & Dual Adjustment Verification

The platform maintains unadjusted raw exchange prices on disk while providing dynamic backwards-adjustment for splits and bonus issues, paired with a complete cash dividend ledger:

### A. Dynamic Backward Split & Bonus Continuity
* **Cipla (`CIPLA.NS`)**: 1:5 stock split on `2004-05-12` (face value ₹10 to ₹2). Unadjusted price dropped from ₹1,274.55 to ₹260.95 (~80% drop). Backward-adjusted price series exhibits a smooth ratio of $1.0000 \pm 0.0001$ across the ex-date boundary with an adjusted 1-day return between -5% and +5%.
* **360 ONE WAM (`360ONE.NS`)**: Simultaneous 1:2 split (face value ₹2 to ₹1) and 1:1 bonus issue on `2023-03-02` (net adjustment factor 4.0×). Unadjusted close moved from ₹1,773.30 to ₹441.05. Adjusted close demonstrates seamless price continuity (~-0.51% return).
* **Eicher Motors (`EICHERMOT.NS`)**: 1:10 stock split on `2020-08-24` (face value ₹10 to ₹1). Unadjusted close moved from ₹21,720 to ₹2,175. Seamless price continuity verified.

### B. Dividend Ledger & Total Return Index (TRI)
* Parsed from 43,816 raw exchange filings: **25,894 verified cash dividend events** across **2,638 instruments**.
* Categorized into regular interim/final dividends and special dividends.
* Synthetic Total Return Index (TRI) compounds cash dividends strictly above Price Return, preserving zero pre-history lookahead bias.

---

## 4. Point-in-Time API (`get_universe`) Behavioral Verification

The `nse.get_universe()` API allows quantitative researchers to slice the investable universe for any historical date using strictly past data:

```python
import nseuniverse as nse

# Query point-in-time universe as of Saturday 2024-01-06 (automatically resolves to 2024-01-05)
df = nse.get_universe(
    as_of_date="2024-01-06",
    universe="nifty500",
    min_adtv=50_000_000,    # 50M INR trailing 20-day ADTV
    min_price=50.0,         # Minimum nominal price filter
    include_metrics=True
)
print(f"Tradable Nifty 500 constituents passing corridors: {len(df)}")
```

### Institutional Invariant Guarantees Verified:
1. **Zero Look-Ahead Date Resolution**: Weekend and exchange holiday queries automatically roll back to the latest preceding trading session. Intraday timestamps (e.g. `'2026-11-09 15:30:00'`) and timezone-aware timestamps (`Asia/Kolkata`) resolve deterministically.
2. **Strict Preceding ADTV Windows**: Liquidity corridor calculations use only sessions on or before `as_of_date`.
3. **Zero Listing/IPO Lookahead**: Stocks are strictly excluded from the universe prior to their exchange listing date (e.g., Jio Financial on `2023-08-20` is absent; tradable on `2023-08-21`).
4. **Immediate Entrant Tradability**: Stocks entering indices become immediately tradable on the exact effective session with zero latency.
5. **Universal Aliasing**: Universe keys accept arbitrary casing and formatting (`"Nifty 50"`, `"nifty-50"`, `"NIFTY_BANK"`, `"Total Market"`, `"nifty it"`).

### 4.1 Empirical Query Latency & Performance Benchmarks

The `get_universe()` API was empirically benchmarked across different query modes, universe sizes, and filtering configurations on canonical datasets ($5,665 \text{ sessions} \times 4,446 \text{ instruments}$):

| Query Configuration | Target Universe | Metrics / Filter Mode | Execution Time (Warm Cache) | Throughput / Latency Assessment |
| :--- | :--- | :--- | :---: | :--- |
| **Mask-Only Ticker List** (`as_list=True`) | Nifty 50 | In-Memory Mask Cache Lookup | **1.46 ms** | Ultra-low latency, optimal for loop-driven backtest rebalances. |
| **Mask-Only Ticker List** (`as_list=True`) | Nifty 500 | In-Memory Mask Cache Lookup | **1.52 ms** | 50× speedup over un-cached full load. |
| **Full Snapshot DataFrame** | Nifty 50 | Close, Open, High, Low, Volume, 1D Return | **2,260 ms** | Includes disk I/O and dynamic multi-column projection. |
| **Filtered Quant Corridor** | Nifty 500 | `min_adtv=50M`, `min_price=50.0` | **4,396 ms** | Vectorized rolling 20-day ADTV calculation across 5,665 sessions. |
| **Broad Market Complete** | Total Market | Full Universe Metric Assembly (~750 scrips) | **5,001 ms** | Comprehensive institutional universe assembly. |

* **In-Memory Caching Acceleration**: Caching PIT masks in `_INDEX_MASK_CACHE` enables daily constituent extraction in **< 1.5 ms** per rebalancing date, allowing an 18-year daily strategy backtest (4,500 trading days) to query point-in-time constituent membership in under 7 seconds.
* **Cache Invalidation Integration**: Invalidation hooks in `update_universe_daily.py` (`invalidate_universe_cache()`) guarantee that any newly appended sessions instantly clear cached masks and dates without manual daemon restart.

---

## 5. Daily Automation & Pre-Commit Invariant Gate

The daily updater (`update_universe_daily.py`) protects the database against data contamination using an atomic two-phase staging and commit pipeline:

```
[Official NSE Bhavcopy Stream]
               │
               ▼
[In-Memory Staging Grid (12 Extended Tensors)]
               │
               ▼
[Multi-Tensor Pre-Commit Mathematical Gate]
   ├── Check High >= Max(Open, Close)
   ├── Check Low <= Min(Open, Close)
   ├── Check Volume >= 0 and Turnover >= 0
   ├── Check Active Close has Non-Null Open/High/Low
   └── Check Zero Taint on Non-Trading Securities
               │
               ├── (FAIL) ──► Instant Clean Rollback (Zero disk taint)
               │
               └── (PASS) ──► Atomic Flush to Parquet Storage
                                 │
                                 ├── Invalidate In-Memory Tensor Caches
                                 ├── Invalidate Index Mask Caches
                                 └── Re-generate 23 PIT Index Masks
```

* **Tested Live Ingestion**: Successfully staged and committed sessions `2026-11-04`, `2026-11-05`, `2026-11-06`, `2026-11-08` (Diwali Muhurat), `2026-11-09`, and `2026-11-11`.
* **Zero Contamination**: 0 mathematical or dimensional violations across all commits.

---

## 6. Official Institutional Validation Checklist

| Check # | Institutional Verification Invariant | Scope / Data Points | Status |
| :---: | :--- | :--- | :---: |
| **Check 1** | Matrix Dimensional Parity (12 Synchronous Tensors) | 5,665 sessions $\times$ 4,446 instruments | **PASS** |
| **Check 2** | Mathematical OHLCV Bounds | 25+ million data points | **PASS** |
| **Check 3** | Zero Phantom Columns (No Non-Traded Entities) | All 4,446 instruments | **PASS** |
| **Check 4** | Zero Disk Taint & Natural Sparsity Invariant | 15.99M natural NaNs (63.5% untraded sparsity) | **PASS** |
| **Check 5** | Listing Gatekeeper & Lookahead Invariant | All 4,446 instruments | **PASS** |
| **Check 6** | Entity Resolution & Alias Map Integrity | 811 canonical alias rules | **PASS** |
| **Check 7** | Applied Corporate Actions Ledger | 1,971 split/bonus records | **PASS** |
| **Check 8** | Dynamic In-Memory Corporate Action Adjustment | Continuous price line across ex-dates | **PASS** |
| **Check 9** | 23 PIT Index Masks & 8 Subset Hierarchy Invariants | 5,665 sessions $\times$ 23 masks | **PASS** |
| **Check 10** | Historical Raw Exchange Bhavcopy Spot Parity | Spot audits on Bhavcopies | **PASS** |
| **Check 11** | PIT Dividend Ledger & Dual Adjustment Architecture | 25,894 dividend events | **PASS** |
| **Check 12** | Point-in-Time Universe Query API (`get_universe`) | Historical reconstitutions & corridors | **PASS** |

---

## 7. Comprehensive Automated Regression Test Suite (76/76 Passing)

The repository maintains 76 automated unit and regression tests executed via `pytest`, achieving a 100% pass rate with zero failures and zero skipped tests:

| Test Module | Test Count | Scope & Coverage | Status |
| :--- | :---: | :--- | :---: |
| `tests/test_adjustments.py` | 4 | Dynamic in-memory split and bonus adjustments, cumulative multiplier vectors, price line continuity, multi-ticker panel adjustment, zero disk taint invariant. | **PASS** |
| `tests/test_client.py` | 12 | Lightweight client `nseuniverse`, `nse.Ticker` API, `nse.Index` synthetic time series, metadata dictionary, actions/bonuses/splits, caching, survivorship bias retention. | **PASS** |
| `tests/test_daily_updater.py` | 20 | Exchange calendar loading, candidate session generation, Diwali Muhurat inclusion, holiday filtering, safe float parsing, atomic multi-tensor staging, mathematical pre-commit gate, mid-commit emergency rollback, cache invalidation, network connection dropout resilience. | **PASS** |
| `tests/test_dividends.py` | 10 | Dividend ledger parsing, regular vs special classification, multi-component additivity, trailing dividend yield computation, Total Return Index (TRI) compounding, zero prehistory leak. | **PASS** |
| `tests/test_historical_accuracy.py` | 19 | Satyam collapse/exit, Axis Bank hiatus/re-inclusion, Yes Bank exit, Suzlon exit, Eternal IPO zero lookahead, Jio Financial IPO zero lookahead, DHFL delisting handling, Cipla split, 360ONE combined action, Eicher Motors split, multi-regime snapshots (GFC 2008, Election 2014, COVID 2020, Election 2024), weekend/holiday resolution, liquidity/price corridors, timestamp/timezone normalization, horizon holiday resolution, name normalization, fields projection, require_traded filtering. | **PASS** |
| `tests/test_pit_universe.py` | 11 | PIT index mask dimensions, 8 strict subset hierarchy containment axioms across 5,665 sessions, listing gatekeeper, sectoral constituent authenticity, dynamic tradable mask generation, zero entrant latency, official sheet events accuracy. | **PASS** |
| **Total** | **76** | **Full System Institutional Regression Suite** | **100% PASS** |

---

## 8. Conclusion

The NSE Point-in-Time Universe is fully verified, mathematically sound, free of survivorship and look-ahead biases, and ready for institutional backtesting, risk management, and quantitative factor research.
