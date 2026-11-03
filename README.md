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
