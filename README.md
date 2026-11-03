# 🏛️ Canonical All-Instrument NSE Universe (2004 – Present)

An institutional-grade, mathematically verified canonical market data store covering **all 6,089 NSE instruments** across **5,657 trading sessions (2004 to present)**, strictly derived from official National Stock Exchange of India (NSE) Bhavcopies.

---

## 🌟 Key Capabilities & Architectural Guarantees

1. **Total Instrument Coverage (All Scrips):**
   - Tracks every instrument that ever traded on the NSE from 2004 to present:
     - **Equities (`EQUITY`):** 4,957 scrips (Active listings + historical delistings, bankruptcies, and drops).
     - **SME Platform (`SME`):** 616 scrips (Series `SM`, `ST`).
     - **ETFs (`ETF`):** 182 instruments (Equity, Gold, Liquid, Debt ETFs).
     - **Mutual Funds (`MUTUAL_FUND`):** 331 schemes.
     - **Debt & Hybrid (`DEBT_INVIT_REIT`):** InvITs, REITs, Sovereign Gold Bonds, and Debt instruments.

2. **Official NSE Sectoral & Broad-Market Selectors:**
   - Synchronized directly with official `niftyindices.com` definitions.
   - **Broad-Market Selectors:** `nifty50`, `niftynext50`, `nifty100`, `nifty200`, `largemid250`, `midcap150`, `smallcap250`, `midsmall400`, `nifty500`, `totalmarket` (NSE 750).
   - **Official Sectoral Selectors:** `niftybank`, `niftyit`, `niftyauto`, `niftypharma`, `niftyhealthcare`, `niftyfmcg`, `niftymetal`, `niftyenergy`, `niftyoilgas`, `niftyfinance`, `niftyrealty`, `niftymedia`, `niftyconsumerdurables`.
   - **Industry Filtering:** Slice universe by official sector/industry string (e.g. `sector='Information Technology'`).

3. **Full-Spectrum Extended Tensor Schema (12 Synchronous Matrices):**
   - `open.parquet`, `high.parquet`, `low.parquet`, `close.parquet`, `volume.parquet`, `turnover.parquet`, `trades.parquet`, `vwap.parquet`, `last.parquet`, `prevclose.parquet`, `series.parquet`, `isin.parquet`.
   - Dimension: **5,657 dates $\times$ 6,089 tickers**.

4. **Zero-Taint Invariant (Pure Base Data):**
   - Untraded or suspended sessions on disk are strictly `NaN`.
   - Optional in-memory forward filling (`forward_fill=True`) for backtesting execution engines without mutating disk parquets.

5. **Self-Sustaining Daily Automation & Pre-Commit Validation Gate:**
   - `update_universe_daily.py` checks for new listings, symbol changes, and corporate actions.
   - Newly staged sessions pass through an atomic mathematical validation gate before committing to disk; any anomaly triggers an immediate rollback to prevent data tainting.

---

## 📦 Lightweight Python Client (`pip install nseuniverse`)

The repository includes `nseuniverse` — an institutional Python client providing a `yfinance`-like developer experience, but with zero survivorship bias, exact exchange metrics, and on-demand cloud caching.

### Installation
```bash
pip install git+https://github.com/sweeza/NSE-PIT-Universe.git
```

### 1. `yfinance`-style Ticker Interface (`nse.Ticker`)
```python
import nseuniverse as nse

# Query any of the 6,089 NSE instruments (Active, SME, ETF, or Delisted)
stock = nse.Ticker("RELIANCE")

# Comprehensive metadata
print(stock.info)
# {'symbol': 'RELIANCE', 'asset_class': 'EQUITY', 'sector': 'Oil Gas & Consumable Fuels', 
#  'isin': 'INE002A01018', 'listing_date': '29-NOV-1995', 'current_indices': ['nifty50', ...]}

# Full Corporate Actions & Split/Bonus Histories
print(stock.actions)
print(stock.bonuses)
print(stock.splits)

# Historical OHLCV + VWAP, Turnover, and Trades
# Backwards-adjusted for splits & bonuses by default
df = stock.history(start="2020-01-01", adjusted=True)
print(df.tail())

# Delisted / Defunct stocks work natively with 0 survivorship bias
dead_stock = nse.Ticker("3IINFOTECH")
print(dead_stock.is_active)  # False
print(dead_stock.history().tail())
```

### 2. Official Synthetic Index Time Series (`nse.Index`)
Query official index levels, OHLCV, and valuation metrics (P/E, P/B, Dividend Yield):
```python
# Query Nifty 50, Nifty Bank, India VIX, or any of 206 official NSE indices
nifty = nse.Index("NIFTY 50")  # or nse.Index("^NSEI")
print(nifty.history(start="2020-01-01").tail())
#             Open     High      Low    Close       Volume     Pe    Pb  Div_yield
# 2026-10-30  22964.5  23118.1  22905.1  23053.1  328562872  19.30  2.83       1.42

# Sectoral & Volatility indices
bank = nse.Index("NIFTY BANK")
vix  = nse.Index("INDIA VIX")
print(vix.history().tail(3))
```

### 3. Point-in-Time Index Universe Loader (`nse.load`)
```python
# Load full cross-sectional matrix (Date x Ticker) for an index
n50_close = nse.load("close", universe="nifty50", adjusted=True)
it_volume  = nse.load("volume", universe="niftyit", adjusted=True)

# Load multiple aligned fields for backtesting
panel = nse.load_universe(
    fields=["open", "high", "low", "close", "volume", "vwap"],
    universe="nifty200",
    adjusted=True,
    forward_fill=True
)
```

---

## 💻 Python Loader API (`nseuniverse_io.py`)

```python
import nseuniverse_io as nio

# 1. Load Broad Market Index (Point-in-Time masked)
midcap_close = nio.load_tensor("close", universe="midcap150")
largemid_close = nio.load_tensor("close", universe="largemid250")

# 2. Load Official Sectoral Indices
bank_close = nio.load_tensor("close", universe="niftybank")
it_volume  = nio.load_tensor("volume", universe="niftyit")

# 3. Filter by Asset Class
etf_close = nio.load_tensor("close", asset_type="ETF")
sme_close = nio.load_tensor("close", asset_type="SME")

# 4. Filter by Sector / Industry
tech_stocks = nio.load_tensor("close", universe="nifty500", sector="Information Technology")

# 5. Extract multiple fields with in-memory forward filling and split/bonus adjustments
panel = nio.load_universe(
    fields=["open", "high", "low", "close", "volume", "vwap"],
    universe="nifty200",
    adjusted=True,       # Dynamic in-memory backward adjustment for splits & bonuses
    forward_fill=True    # Continuous non-stale price lines
)

# 6. Access Master Security Master & Corporate Actions
sec_master = nio.get_security_master()
ca_ledger  = nio.get_corporate_actions()
```

---

## 🔬 Validation & Audit

Run the 6-stage validation suite anytime:
```bash
python validate_universe.py
```
Outputs validation metrics to `data/validation_report.json`.
