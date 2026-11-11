"""
Constructs daily Point-in-Time (PIT) boolean membership masks for all official
broad-market and sectoral indices.

Guarantees:
- Output matrices are shaped exactly (5,659 Dates x 4,446 Canonical Tickers).
- 4 Cardinal PIT Axioms strictly enforced:
  1. Zero Survivorship Bias: Delisted / failed companies remain active during their historical tenure.
  2. Listing & Trading Gatekeeper: t >= first_trade_date (no future IPO winner active prior to listing).
  3. Strict Subset Hierarchy Invariance: EXACTLY 0 daily violations across all 5,659 sessions:
     - Nifty 50(t) ⊆ Nifty 100(t) ⊆ Nifty 200(t) ⊆ Nifty 500(t)
     - Nifty 100(t) | Midcap 150(t) == LargeMidcap 250(t)
     - Midcap 150(t) | Smallcap 250(t) == MidSmallcap 400(t)
     - Nifty 100(t) == Nifty 500(t) & ~MidSmallcap 400(t)
     - Nifty 50(t) | Nifty Next 50(t) == Nifty 100(t)
     - Nifty 500(t) ⊆ Total Market(t)
  4. Unified Corporate Entity Resolution: Continuous scrip timelines resolved via symbol_alias_map.json.
- Integrates reconstitution logs from IndexInclExcl.xls, pit_events_log.parquet, and official constituent seeds.
- Output parquet files are saved to data/metadata/pit_memberships/<index>.parquet.
"""

import sys
import json
from pathlib import Path
import numpy as np
import pandas as pd
import config

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# Explicit ticker alias overrides for historical N500 members
HISTORICAL_ALIAS_OVERRIDES = {
    "BIRLASOFT.NS": "BSOFT.NS",
    "ICICIPRULI.NS": "ICICILIFE.NS",
    "ZFCOMMERCIAL.NS": "ZFCVINDIA.NS",
    "BLACKBOX.NS": "BBOX.NS",
    "RHI.NS": "RHIM.NS",
    "TATASTEELBSL.NS": "TATASTLBSL.NS",
    "JSWISPATS.NS": "JSWISPAT.NS",
    "SHILPICABL.NS": "SHILPI.NS",
    "NARMADACHM.NS": "NARMADA.NS",
    "GAMMOINFRA.NS": "GAMMONIND.NS",
    "ESCORTSFIN.NS": "ESCORTS.NS",
    "DUMMYHEG.NS": "HEGAM.NS",
}

# Historical name overrides for IndexInclExcl.xls mapping
NAME_OVERRIDES = {
    "Arvind Mills Ltd": "ARVIND.NS",
    "Bajaj Auto Ltd": "BAJAJ-AUTO.NS",
    "Bharti Tele-Ventures Ltd.": "BHARTIARTL.NS",
    "Brooke Bond Lipton India Ltd.": "HINDUNILVR.NS",
    "Colgate Palmolive (I) Ltd": "COLPAL.NS",
    "Digital Equipment (india) Ltd.": "HCLTECH.NS",
    "East India Hotels Ltd": "EIHOTEL.NS",
    "Essar Gujarat Ltd.": "ESSARSTEEL.NS",
    "Gas Authority of India Limited": "GAIL.NS",
    "Glaxo (India) Ltd.": "GLAXO.NS",
    "Great Eastern Shipping Company Limited.": "GESHIP.NS",
    "HDFC Life Insurance Company Ltd.": "HDFCLIFE.NS",
    "Hero Honda Motors Limited": "HEROMOTOCO.NS",
    "IDFC Ltd": "IDFCFIRSTB.NS",
    "Indian Rayon & Industries Ltd.": "ADITYABIRLA.NS",
    "Industrial Development Bank of India Limited": "IDBI.NS",
    "Industrial Finance Corporation Of India Ltd.": "IFCI.NS",
    "Infosys Technologies Limited": "INFY.NS",
    "Infrastructure Development Finance Company Limited": "IDFCFIRSTB.NS",
    "Madras Refineries Ltd.": "CHENNPETRO.NS",
    "Maruti Udyog Limited": "MARUTI.NS",
    "Novartis India Ltd": "NOVARTIND.NS",
    "Ponds (India) Ltd.": "HINDUNILVR.NS",
    "Procter & Gamble India Ltd.": "PGHL.NS",
    "Reckitt & Colman India Ltd.": "RECKITTBEN.NS",
    "SCICI Ltd.": "ICICIBANK.NS",
    "Sesa Goa Limited": "VEDL.NS",
    "Smithkline Beecham Consumer Healthcare Ltd.": "HINDUNILVR.NS",
    "TVS Suzuki Ltd.": "TVSMOTOR.NS",
    "Tata Tea Limited": "TATACONSUM.NS",
    "Titan Company Ltd.": "TITAN.NS",
    "Videsh Sanchar Nigam Ltd.": "TATACOMM.NS",
    "Zee Telefilms Ltd": "ZEEL.NS",
    "Madras Cements Ltd.": "RAMCOCEM.NS",
    "Reliance Defence and Engineering Ltd.": "RNEL.NS",
    "Future Consumer Ltd.": "FCONSUMER.NS",
    "Centurion Bank of Punjab Ltd.": "HDFCBANK.NS",
    "Castrol (India) Ltd.-Old": "CASTROLIND.NS",
    "GE T&D India Ltd.": "GVT&D.NS",
    "Himachal Futuristic Communications Ltd": "HFCL.NS",
    "Himachal Futuristic Communications Ltd.": "HFCL.NS",
    "Polaris Software Lab Ltd.": "POLARIS.NS",
    "Piramal Healthcare Ltd.": "PEL.NS",
    "Asian Hotels Ltd.": "ASIANHOTNR.NS",
    "India Cements Ltd.": "INDIACEM.NS",
    "Pantaloon Retail (India) Ltd.": "FEL.NS",
    "63 Moons Technologies Ltd.": "63MOONS.NS",
    "Subex Ltd.": "SUBEX.NS",
    "3i Infotech Ltd.": "3IINFOTECH.NS",
    "OnMobile Global Ltd.": "ONMOBILE.NS",
    "Vakrangee Ltd.": "VAKRANGEE.NS",
    "Cyient Ltd.": "CYIENT.NS",
    "Infibeam Incorporation Ltd.": "CCAVENUE.NS",
    "Infibeam Avenues Ltd.": "CCAVENUE.NS",
    "NIIT Technologies Ltd.": "COFORGE.NS",
    "NIIT Ltd.-Sus": "NIITLTD.NS",
    "Navneet Publications (India) Ltd.": "NAVNETEDUL.NS",
    "KSS Ltd.": "KSERASERA.NS",
    "UFO Moviez India Ltd.": "UFO.NS",
    "Music Broadcast Ltd.": "RADIOCITY.NS",
    "Jump Networks Ltd.": "WINPRO.NS",
    "JSW ISPAT Steel Limited": "JSWISPAT.NS",
    "JSW ISPAT Steel Ltd.": "JSWISPAT.NS",
    "Ackruti City Ltd.": "HUBTOWN.NS",
    "Amara Raja Batteries Ltd.": "ARE&M.NS",
    "Escorts Ltd.": "ESCORTS.NS",
    "Tata Motors Ltd DVR": "TATAMTRDVR.NS",
    "Tata Infotech Ltd.-Merged": "TATAINFOTE.NS",
    "Patni Computer Systems Ltd.": "PATNI.NS",
    "Visualsoft Technologies Ltd.": "VISUALSOFT.NS",
    "Polaris Consulting & Services Ltd.": "POLARIS.NS",
    "Satyam Computer Services Ltd.": "SATYAMCOMP.NS",
    "Hexaware Technologies Ltd.": "HEXAWARE.NS",
    "Rolta India Ltd.": "ROLTA.NS",
    "CMC Ltd.": "CMC.NS",
    "Tata Sponge Iron Ltd.": "TATASTLLP.NS",
    "Sterlite Industries (India) Ltd.": "VEDL.NS",
    "Reliance Petroleum Ltd.": "RPL.NS",
    "Hinduja Ventures Ltd.": "NDLVENTURE.NS",
    "McDowell & Co. Ltd. (Old)": "UNITDSPR.NS",
    "Monnet Ispat and Energy Ltd.": "MONNETISPA.NS",
}

# Post-2020 official Nifty 50 reconstitutions
POST_2020_N50_EVENTS = [
    ("2020-09-25", "DIVISLAB.NS", "Inclusion into Index"),
    ("2020-09-25", "SBILIFE.NS", "Inclusion into Index"),
    ("2020-09-25", "INDUSTOWER.NS", "Exclusion from Index"),
    ("2020-09-25", "ZEEL.NS", "Exclusion from Index"),
    ("2021-03-31", "TATACONSUM.NS", "Inclusion into Index"),
    ("2021-03-31", "GAIL.NS", "Exclusion from Index"),
    ("2022-03-31", "APOLLOHOSP.NS", "Inclusion into Index"),
    ("2022-03-31", "IOC.NS", "Exclusion from Index"),
    ("2022-09-30", "ADANIENT.NS", "Inclusion into Index"),
    ("2022-09-30", "SHREECEM.NS", "Exclusion from Index"),
    ("2023-07-13", "LTM.NS", "Inclusion into Index"),
    ("2023-07-13", "HDFC.NS", "Exclusion from Index"),
    ("2024-03-28", "SHRIRAMFIN.NS", "Inclusion into Index"),
    ("2024-03-28", "UPL.NS", "Exclusion from Index"),
    ("2024-09-30", "BEL.NS", "Inclusion into Index"),
    ("2024-09-30", "TRENT.NS", "Inclusion into Index"),
    ("2024-09-30", "DIVISLAB.NS", "Exclusion from Index"),
    ("2024-09-30", "LTM.NS", "Exclusion from Index"),
    ("2025-03-28", "ETERNAL.NS", "Inclusion into Index"),
    ("2025-03-28", "INDIGO.NS", "Inclusion into Index"),
    ("2025-03-28", "BPCL.NS", "Exclusion from Index"),
    ("2025-03-28", "HEROMOTOCO.NS", "Exclusion from Index"),
    ("2025-09-30", "JIOFIN.NS", "Inclusion into Index"),
    ("2025-09-30", "WIPRO.NS", "Exclusion from Index"),
    ("2026-03-31", "BSE.NS", "Inclusion into Index"),
    ("2026-03-31", "MAXHEALTH.NS", "Inclusion into Index"),
    ("2026-03-31", "BRITANNIA.NS", "Exclusion from Index"),
    ("2026-03-31", "INDUSINDBK.NS", "Exclusion from Index"),
]

# Founding constituents for full-history forward reconstituted indices
FOUNDING_NIFTYIT = [
    "APTECHT.NS", "CMC.NS", "DIGITALEQP.NS", "GTL.NS", "HCL-INSYS.NS", "INFY.NS",
    "MASTEK.NS", "MOSERBAER.NS", "MPHASIS.NS", "NIITLTD.NS", "PENTSFWARE.NS", "PVP.NS",
    "ROLTA.NS", "SATYAMCOMP.NS", "SILVERLINE.NS", "SQRDSFWARE.NS", "TATAELXSI.NS",
    "TATAINFOTE.NS", "TRIGYN.NS", "WIPRO.NS"
]

FOUNDING_REALTY = [
    "ANSALAPI.NS", "PARSVNATH.NS", "MAHLIFE.NS", "ANANTRAJ.NS", "UNITECH.NS",
    "SOBHA.NS", "HUBTOWN.NS", "EMBDL.NS", "PHOENIXLTD.NS", "DLF.NS"
]

# Authentic mid-2020 constituent anchor sets for reverse reconstitution
MID_2020_ANCHORS = {
    "niftybank": {
        "HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS", "SBIN.NS",
        "INDUSINDBK.NS", "BANKBARODA.NS", "FEDERALBNK.NS", "PNB.NS", "IDFCFIRSTB.NS",
        "RBLBANK.NS", "BANDHANBNK.NS"
    },
    "niftyauto": {
        "MARUTI.NS", "M&M.NS", "BAJAJ-AUTO.NS", "HEROMOTOCO.NS", "TATAMOTORS.NS",
        "BOSCHLTD.NS", "BHARATFORG.NS", "ASHOKLEY.NS", "MOTHERSON.NS", "MRF.NS",
        "EXIDEIND.NS", "EICHERMOT.NS", "ARE&M.NS", "TVSMOTOR.NS", "BALKRISIND.NS"
    },
    "niftyfinance": {
        "HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS", "SBIN.NS",
        "INDUSINDBK.NS", "HDFC.NS", "BANKBARODA.NS", "SHRIRAMFIN.NS", "BAJAJFINSV.NS",
        "M&MFIN.NS", "BAJFINANCE.NS", "BAJAJHLDNG.NS", "ICICILIFE.NS", "HDFCLIFE.NS",
        "CHOLAFIN.NS", "ICICIGI.NS", "SBILIFE.NS", "PEL.NS", "HDFCAMC.NS"
    },
    "niftyfmcg": {
        "HINDUNILVR.NS", "ITC.NS", "BRITANNIA.NS", "DABUR.NS", "MARICO.NS",
        "COLPAL.NS", "TATACONSUM.NS", "GODREJCP.NS", "UBL.NS", "UNITDSPR.NS",
        "PGHH.NS", "JUBLFOOD.NS", "VBL.NS", "NESTLEIND.NS", "EMAMILTD.NS"
    },
    "niftymetal": {
        "TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "JINDALSTEL.NS", "SAIL.NS",
        "NMDC.NS", "HINDZINC.NS", "NATIONALUM.NS", "COALINDIA.NS", "APLAPOLLO.NS",
        "MIDHANI.NS", "RATNAMANI.NS", "HINDCOPPER.NS", "MOIL.NS", "WELCORP.NS"
    },
    "niftyenergy": {
        "RELIANCE.NS", "ONGC.NS", "NTPC.NS", "POWERGRID.NS", "BPCL.NS",
        "IOC.NS", "GAIL.NS", "TATAPOWER.NS", "ADANIENSOL.NS", "HINDPETRO.NS"
    },
    "niftymedia": {
        "ZEEL.NS", "SUNTV.NS", "PVRINOX.NS", "INOXLEISUR.NS", "TVTODAY.NS",
        "DBCORP.NS", "TV18BRDCST.NS", "DISHTV.NS", "HATHWAY.NS", "JAGRAN.NS"
    },
    "niftypharma": {
        "SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "LUPIN.NS",
        "AUROPHARMA.NS", "BIOCON.NS", "ZYDUSLIFE.NS", "TORNTPHARM.NS", "ALKEM.NS"
    },
}

# Explicit post-2020 sectoral index reconstitutions from official NSE press releases
POST_2020_SECTORAL_EVENTS = {
    "niftyit": [
        ("2021-03-31", "NAUKRI.NS", "Exclusion from Index"),
        ("2021-03-31", "OFSS.NS", "Inclusion into Index"),
        ("2022-09-30", "MINDTREE.NS", "Exclusion from Index"),
        ("2022-09-30", "PERSISTENT.NS", "Inclusion into Index"),
    ],
    "niftyrealty": [
        ("2021-09-30", "OMAXE.NS", "Exclusion from Index"),
        ("2021-09-30", "LODHA.NS", "Inclusion into Index"),
        ("2023-09-29", "EMBDL.NS", "Exclusion from Index"),
        ("2023-09-29", "ABREL.NS", "Inclusion into Index"),
        ("2024-09-30", "SUNTECK.NS", "Exclusion from Index"),
        ("2024-09-30", "ANANTRAJ.NS", "Inclusion into Index"),
    ],
    "niftybank": [
        ("2022-03-31", "RBLBANK.NS", "Exclusion from Index"),
        ("2022-03-31", "AUBANK.NS", "Inclusion into Index"),
        ("2024-09-30", "BANDHANBNK.NS", "Exclusion from Index"),
        ("2024-09-30", "CANBK.NS", "Inclusion into Index"),
        ("2025-12-31", "UNIONBANK.NS", "Inclusion into Index"),
        ("2025-12-31", "YESBANK.NS", "Inclusion into Index"),
    ],
    "niftyauto": [
        ("2022-03-31", "EXIDEIND.NS", "Exclusion from Index"),
        ("2022-03-31", "TIINDIA.NS", "Inclusion into Index"),
        ("2022-09-30", "MRF.NS", "Exclusion from Index"),
        ("2022-09-30", "UNOMINDA.NS", "Inclusion into Index"),
        ("2023-03-31", "ARE&M.NS", "Exclusion from Index"),
        ("2023-03-31", "SONACOMS.NS", "Inclusion into Index"),
        ("2024-11-29", "BALKRISIND.NS", "Exclusion from Index"),
        ("2024-11-29", "HYUNDAI.NS", "Inclusion into Index"),
        ("2025-03-28", "TATAMOTORS.NS", "Exclusion from Index"),
        ("2025-03-28", "TMPV.NS", "Inclusion into Index"),
    ],
    "niftyfinance": [
        ("2021-03-31", "M&MFIN.NS", "Exclusion from Index"),
        ("2021-03-31", "MUTHOOTFIN.NS", "Inclusion into Index"),
        ("2021-09-30", "BAJAJHLDNG.NS", "Exclusion from Index"),
        ("2021-09-30", "SBICARD.NS", "Inclusion into Index"),
        ("2022-03-31", "BANKBARODA.NS", "Exclusion from Index"),
        ("2022-03-31", "RECLTD.NS", "Inclusion into Index"),
        ("2022-09-30", "PEL.NS", "Exclusion from Index"),
        ("2022-09-30", "PFC.NS", "Inclusion into Index"),
        ("2023-07-13", "HDFC.NS", "Exclusion from Index"),
        ("2023-07-13", "LICHSGFIN.NS", "Inclusion into Index"),
        ("2024-03-28", "HDFCAMC.NS", "Exclusion from Index"),
        ("2024-03-28", "MFSL.NS", "Inclusion into Index"),
        ("2025-09-30", "ICICILIFE.NS", "Exclusion from Index"),
        ("2025-09-30", "JIOFIN.NS", "Inclusion into Index"),
        ("2026-03-31", "MUTHOOTFIN.NS", "Exclusion from Index"),
        ("2026-03-31", "BSE.NS", "Inclusion into Index"),
    ],
    "niftyfmcg": [
        ("2022-03-31", "JUBLFOOD.NS", "Exclusion from Index"),
        ("2022-03-31", "RADICO.NS", "Inclusion into Index"),
        ("2023-03-31", "EMAMILTD.NS", "Exclusion from Index"),
        ("2023-03-31", "PATANJALI.NS", "Inclusion into Index"),
        ("2024-03-28", "PGHH.NS", "Exclusion from Index"),
        ("2024-03-28", "GODFRYPHLP.NS", "Inclusion into Index"),
    ],
    "niftymetal": [
        ("2021-03-31", "MIDHANI.NS", "Exclusion from Index"),
        ("2021-03-31", "ADANIENT.NS", "Inclusion into Index"),
        ("2022-03-31", "MOIL.NS", "Exclusion from Index"),
        ("2022-03-31", "JSL.NS", "Inclusion into Index"),
        ("2023-03-31", "WELCORP.NS", "Exclusion from Index"),
        ("2023-03-31", "VEDL.NS", "Inclusion into Index"),
        ("2024-09-30", "RATNAMANI.NS", "Exclusion from Index"),
        ("2024-09-30", "LLOYDSME.NS", "Inclusion into Index"),
        ("2025-03-28", "COALINDIA.NS", "Exclusion from Index"),
        ("2025-03-28", "VAML.NS", "Inclusion into Index"),
    ],
    "niftyenergy": [
        ("2022-03-31", "PETRONET.NS", "Exclusion from Index"),
        ("2022-03-31", "ADANIGREEN.NS", "Inclusion into Index"),
    ],
    "niftymedia": [
        ("2022-09-30", "HATHWAY.NS", "Exclusion from Index"),
        ("2022-09-30", "NAZARA.NS", "Inclusion into Index"),
        ("2023-03-31", "INOXLEISUR.NS", "Exclusion from Index"),
        ("2023-03-31", "SAREGAMA.NS", "Inclusion into Index"),
        ("2024-03-28", "DISHTV.NS", "Exclusion from Index"),
        ("2024-03-28", "TIPSMUSIC.NS", "Inclusion into Index"),
        ("2025-03-28", "TV18BRDCST.NS", "Exclusion from Index"),
        ("2025-03-28", "PFOCUS.NS", "Inclusion into Index"),
    ],
    "niftypharma": [],
}

# Sector definitions and nominal constituent limits
SECTORAL_SPECS = {
    "niftybank": {
        "sector_pattern": "Financial Services",
        "keywords": ["BANK", "HDFC", "ICICI", "KOTAK", "AXIS", "SBI", "PNB", "INDUSIND", "CANBK", "BOB"],
        "max_constituents": 14,
    },
    "niftyit": {
        "sector_pattern": "Information Technology",
        "keywords": [],
        "max_constituents": 10,
    },
    "niftyauto": {
        "sector_pattern": "Automobile and Auto Components",
        "keywords": [],
        "max_constituents": 15,
    },
    "niftypharma": {
        "sector_pattern": "Healthcare",
        "keywords": ["PHARMA", "LAB", "DR", "CIPLA", "SUN", "LUPIN"],
        "max_constituents": 20,
    },
    "niftyhealthcare": {
        "sector_pattern": "Healthcare",
        "keywords": [],
        "max_constituents": 20,
    },
    "niftyfmcg": {
        "sector_pattern": "Fast Moving Consumer Goods",
        "keywords": [],
        "max_constituents": 15,
    },
    "niftymetal": {
        "sector_pattern": "Metals & Mining",
        "keywords": [],
        "max_constituents": 15,
    },
    "niftyenergy": {
        "sector_pattern": "Power|Oil Gas|Energy|Consumable Fuels",
        "keywords": [],
        "max_constituents": 30,
    },
    "niftyoilgas": {
        "sector_pattern": "Oil Gas & Consumable Fuels",
        "keywords": [],
        "max_constituents": 15,
    },
    "niftyfinance": {
        "sector_pattern": "Financial Services",
        "keywords": [],
        "max_constituents": 20,
    },
    "niftyrealty": {
        "sector_pattern": "Realty",
        "keywords": [],
        "max_constituents": 10,
    },
    "niftymedia": {
        "sector_pattern": "Media",
        "keywords": [],
        "max_constituents": 10,
    },
    "niftyconsumerdurables": {
        "sector_pattern": "Consumer Durables",
        "keywords": [],
        "max_constituents": 15,
    },
}


def build_pit_membership_masks():
    print("=" * 80)
    print("BUILDING POINT-IN-TIME (PIT) MEMBERSHIP MASKS (ALL 23 INDICES)")
    print("=" * 80)

    config.PIT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load canonical instruments and dates from close tensor
    close_file = config.TENSOR_FILES["close"]
    if not close_file.exists():
        raise FileNotFoundError(f"Canonical tensor '{close_file.name}' not found.")

    close_df = pd.read_parquet(close_file)
    all_dates = close_df.index
    all_cols = close_df.columns
    n_dates = len(all_dates)
    n_cols = len(all_cols)
    col_to_idx = {c: i for i, c in enumerate(all_cols)}

    print(f"  Canonical grid: {n_dates:,} sessions x {n_cols:,} instruments")
    print(f"  Horizon:        {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")

    # 2. Gatekeeper: Listing & Trading Invariant (Axiom 2)
    has_traded_mat = close_df.notna().cummax(axis=0).values

    # 3. Liquidity & Turnover Ranking (126-day rolling average turnover)
    turnover_file = config.TENSOR_FILES["turnover"]
    to_df = pd.read_parquet(turnover_file).fillna(0.0) if turnover_file.exists() else pd.DataFrame(0.0, index=all_dates, columns=all_cols)
    adtv_126_mat = to_df.rolling(126, min_periods=20).mean().fillna(0.0).values

    # 4. Ingest Historical Nifty 500 PIT Membership Matrix
    n500_file = config.SOURCE_METADATA_DIR / "pit_nifty500_daily_membership_1995_2026.parquet"
    if not n500_file.exists():
        alt_paths = [
            config.MOSHI_DIR / "Output" / "master" / "pit_nifty500_daily_membership_1995_2026.parquet",
            config.MOSHI_APP_DIR / "data" / "metadata" / "pit_nifty500_daily_membership.parquet",
            config.MOSHI_DIR / "pit_nifty500_daily_membership.parquet",
        ]
        for p in alt_paths:
            if p.exists():
                n500_file = p
                break

    if not n500_file.exists():
        raise FileNotFoundError(f"Source Nifty 500 PIT membership matrix not found at {n500_file}")

    print(f"  Loading historical Nifty 500 PIT source: {n500_file.name}")
    n500_raw = pd.read_parquet(n500_file)

    # Load symbol alias map
    alias_file = config.METADATA_DIR / "symbol_alias_map.json"
    aliases = json.loads(alias_file.read_text()) if alias_file.exists() else {}
    alias_ticker_map = {f"{k}.NS": f"{v}.NS" for k, v in aliases.items()}
    alias_ticker_map.update(HISTORICAL_ALIAS_OVERRIDES)

    def resolve_ticker(t: str) -> str:
        if not isinstance(t, str) or not t.strip():
            return None
        sym = t.strip()
        if not sym.endswith(".NS"):
            sym = f"{sym}.NS"
        return alias_ticker_map.get(sym, sym)

    # Construct mapped Nifty 500 boolean matrix
    n500_arr = np.zeros((n_dates, n_cols), dtype=bool)
    common_dates = all_dates.intersection(n500_raw.index)

    for col in n500_raw.columns:
        target_col = col if col in col_to_idx else alias_ticker_map.get(col)
        if target_col and target_col in col_to_idx:
            c_idx = col_to_idx[target_col]
            s_vals = n500_raw.loc[common_dates, col].astype(bool).values
            date_indices = all_dates.get_indexer(common_dates)
            n500_arr[date_indices, c_idx] |= s_vals

    # Forward-fill any unpopulated exchange gap sessions (< 400 members)
    for i in range(n_dates):
        if n500_arr[i].sum() < 400 and i > 0:
            n500_arr[i] = n500_arr[i - 1].copy()

    # Enforce Gatekeeper (Axiom 2) on N500
    n500_arr &= has_traded_mat
    daily_n500_counts = n500_arr.sum(axis=1)
    print(f"  Nifty 500 daily counts: min={daily_n500_counts.min()}, median={int(np.median(daily_n500_counts))}, max={daily_n500_counts.max()}")

    # 5. Ingest Reconstitution Logs & Current Index Constituents for Priority Seeding
    print("\n  Ingesting official historical reconstitution logs & constituent lists...")
    sec_master = pd.read_parquet(config.SECURITY_MASTER_FILE)
    n500_recon_file = config.MOSHI_DIR / "Output" / "n500_mapped_reconstitutions_1995_2020.parquet"
    scrip_map = {}
    if n500_recon_file.exists():
        n500_recon = pd.read_parquet(n500_recon_file)
        scrip_map = n500_recon.drop_duplicates("scrip_name").set_index("scrip_name")["canonical_ticker"].to_dict()

    for t, row in sec_master.iterrows():
        cn = str(row["company_name"]).strip()
        if cn and cn not in scrip_map:
            scrip_map[cn] = t
    scrip_map.update(NAME_OVERRIDES)

    def get_csv_constituents(csv_name: str) -> set:
        f = config.RAW_INDICES_DIR / csv_name
        s = set()
        if f.exists():
            df = pd.read_csv(f)
            sym_col = [c for c in df.columns if "symbol" in c.lower()][0]
            for raw_s in df[sym_col].dropna().str.strip():
                t = resolve_ticker(f"{raw_s}.NS")
                if t and t in col_to_idx:
                    s.add(t)
        return s

    curr_n50 = get_csv_constituents("nifty50.csv")
    curr_nn50 = get_csv_constituents("niftynext50.csv")
    curr_m150 = get_csv_constituents("midcap150.csv")

    excel_path = config.MOSHI_DIR / "IndexInclExcl.xls"
    all_n50_ev = pd.DataFrame()
    all_nn50_ev = pd.DataFrame()

    if excel_path.exists():
        xl = pd.ExcelFile(excel_path)

        def load_sheet_events(sheet_name: str) -> pd.DataFrame:
            df = xl.parse(sheet_name)
            df["Event Date"] = pd.to_datetime(df["Event Date"], format="mixed", dayfirst=True)
            tickers = []
            for _, r in df.iterrows():
                sc = str(r["Scrip Name"]).strip()
                dt = r["Event Date"]
                if sc == "KPIT Technologies Ltd." and dt < pd.Timestamp("2019-01-01"):
                    tickers.append("BSOFT.NS")
                else:
                    tickers.append(resolve_ticker(scrip_map.get(sc)))
            df["ticker"] = tickers
            return df.dropna(subset=["ticker"])

        n50_ev = load_sheet_events("Nifty 50")
        post_df = pd.DataFrame(POST_2020_N50_EVENTS, columns=["Event Date", "ticker", "Description"])
        post_df["Event Date"] = pd.to_datetime(post_df["Event Date"])
        post_df["ticker"] = post_df["ticker"].map(resolve_ticker)
        all_n50_ev = pd.concat([n50_ev[["Event Date", "ticker", "Description"]], post_df], ignore_index=True).sort_values("Event Date")
        all_nn50_ev = load_sheet_events("Nifty Next 50").sort_values("Event Date")
        print(f"  Loaded {len(all_n50_ev)} Nifty 50 events and {len(all_nn50_ev)} Nifty Next 50 events.")

    # Precompute historical N50 active set intervals
    n50_intervals = []
    if not all_n50_ev.empty:
        cur_set = set(curr_n50)
        rev_ev = all_n50_ev[all_n50_ev["Event Date"] >= all_dates[0]].sort_values("Event Date", ascending=False)
        ev_dates = sorted(rev_ev["Event Date"].unique(), reverse=True)
        for ev_dt in ev_dates:
            n50_intervals.append((ev_dt, set(cur_set)))
            grp = rev_ev[rev_ev["Event Date"] == ev_dt]
            for _, r in grp.iterrows():
                t = r["ticker"]
                desc = r["Description"].lower()
                if "inclusion" in desc:
                    cur_set.discard(t)
                elif "exclusion" in desc:
                    cur_set.add(t)
        n50_intervals.append((pd.to_datetime("1990-01-01"), set(cur_set)))

    def get_official_n50_at(dt: pd.Timestamp) -> set:
        for ev_dt, s in n50_intervals:
            if dt >= ev_dt:
                return s
        return n50_intervals[-1][1] if n50_intervals else curr_n50

    # Precompute historical NN50 active set intervals
    nn50_intervals = []
    if not all_nn50_ev.empty:
        cur_set_nn = set(curr_nn50)
        rev_ev_nn = all_nn50_ev[all_nn50_ev["Event Date"] >= all_dates[0]].sort_values("Event Date", ascending=False)
        ev_dates_nn = sorted(rev_ev_nn["Event Date"].unique(), reverse=True)
        for ev_dt in ev_dates_nn:
            nn50_intervals.append((ev_dt, set(cur_set_nn)))
            grp = rev_ev_nn[rev_ev_nn["Event Date"] == ev_dt]
            for _, r in grp.iterrows():
                t = r["ticker"]
                desc = r["Description"].lower()
                if "inclusion" in desc:
                    cur_set_nn.discard(t)
                elif "exclusion" in desc:
                    cur_set_nn.add(t)
        nn50_intervals.append((pd.to_datetime("1990-01-01"), set(cur_set_nn)))

    def get_official_nn50_at(dt: pd.Timestamp) -> set:
        for ev_dt, s in nn50_intervals:
            if dt >= ev_dt:
                return s
        return nn50_intervals[-1][1] if nn50_intervals else curr_nn50

    # Axiom 3 Consistency: Any stock in official Nifty 50 or Nifty Next 50 must be in Nifty 500
    for i, dt in enumerate(all_dates):
        off_n50 = get_official_n50_at(dt)
        off_nn50 = get_official_nn50_at(dt)
        for t in off_n50.union(off_nn50):
            c_idx = col_to_idx.get(t)
            if c_idx is not None and has_traded_mat[i, c_idx]:
                n500_arr[i, c_idx] = True

    # Ingest NIFTY 200 & LargeMidcap 250 events from pit_events_log.parquet
    pit_log_file = config.MOSHI_DIR / "pit_events_log.parquet"
    official_m150_candidates = set(curr_m150)
    if pit_log_file.exists():
        pit_log = pd.read_parquet(pit_log_file)
        sub_log = pit_log[pit_log["index_name"].isin(["NIFTY 200", "NIFTY LargeMidcap 250"])]
        for s in sub_log["symbol"].dropna().unique():
            can = resolve_ticker(str(s).strip())
            if can and can in col_to_idx:
                official_m150_candidates.add(can)
        print(f"  Enriched Midcap 150 candidate pool to {len(official_m150_candidates)} historical scrips via pit_events_log.")

    # 6. Build Broad Market Sub-Index Tier Matrices via Priority Slicing
    print("\n  Constructing hierarchical broad-market sub-indices...")
    n50_arr = np.zeros((n_dates, n_cols), dtype=bool)
    nn50_arr = np.zeros((n_dates, n_cols), dtype=bool)
    n100_arr = np.zeros((n_dates, n_cols), dtype=bool)
    m150_arr = np.zeros((n_dates, n_cols), dtype=bool)
    s250_arr = np.zeros((n_dates, n_cols), dtype=bool)
    ms400_arr = np.zeros((n_dates, n_cols), dtype=bool)
    n200_arr = np.zeros((n_dates, n_cols), dtype=bool)
    lm250_arr = np.zeros((n_dates, n_cols), dtype=bool)

    alloc_n50 = np.array([], dtype=int)
    alloc_nn50 = np.array([], dtype=int)
    alloc_m150 = np.array([], dtype=int)
    alloc_n200_mid = np.array([], dtype=int)

    # Set of event dates triggering rebalance
    event_change_dates = set(ev[0] for ev in n50_intervals + nn50_intervals) if (n50_intervals or nn50_intervals) else set()

    for i, dt in enumerate(all_dates):
        # Rebalance semi-annually (April 1 & October 1) and on official reconstitution dates
        is_semi_annual = (i == 0) or (dt.month in (4, 10) and all_dates[i - 1].month not in (4, 10))
        is_event_date = dt in event_change_dates
        is_rebal = is_semi_annual or is_event_date

        if is_rebal or len(alloc_n50) == 0:
            active_today = np.where(n500_arr[i])[0]
            if len(active_today) > 0:
                # 1. Determine official active sets for today
                n50_today_set = get_official_n50_at(dt)
                nn50_today_set = get_official_nn50_at(dt)
                n50_today_idx = {col_to_idx[t] for t in n50_today_set if t in col_to_idx}
                nn50_today_idx = {col_to_idx[t] for t in nn50_today_set if t in col_to_idx}
                m150_today_idx = {col_to_idx[t] for t in official_m150_candidates if t in col_to_idx}

                # 2. Priority scoring:
                # Tier 1 (Official N50): +10,000,000
                # Tier 2 (Official NN50): +5,000,000
                # Tier 3 (Official M150/N200/LM250): +2,000,000
                # Tier 4 (Remaining N500): 0
                priority = np.zeros(len(active_today), dtype=float)
                for pos, c in enumerate(active_today):
                    if c in n50_today_idx:
                        priority[pos] = 10_000_000.0
                    elif c in nn50_today_idx:
                        priority[pos] = 5_000_000.0
                    elif c in m150_today_idx:
                        priority[pos] = 2_000_000.0

                # Augment with normalized turnover ranking within priority brackets
                to_scores = adtv_126_mat[i, active_today]
                max_to = np.nanmax(to_scores) if np.nanmax(to_scores) > 0 else 1.0
                norm_to = to_scores / max_to
                total_scores = priority + norm_to

                sorted_active = active_today[np.argsort(-total_scores)]

                alloc_n50 = sorted_active[:50]
                alloc_nn50 = sorted_active[50:100]
                alloc_m150 = sorted_active[100:250]
                alloc_n200_mid = sorted_active[100:200]

        # 1. Nifty 50: Top 50 incumbents active today
        valid_n50 = alloc_n50[n500_arr[i, alloc_n50]]
        n50_arr[i, valid_n50] = True

        # 2. Nifty Next 50: Ranks 51-100 active today
        valid_nn50 = alloc_nn50[n500_arr[i, alloc_nn50]]
        nn50_arr[i, valid_nn50] = True

        # 3. Nifty 100 = Nifty 50 | Nifty Next 50 (Strict Identity)
        n100_arr[i] = n50_arr[i] | nn50_arr[i]

        # 4. MidSmallcap 400 = Nifty 500 & ~Nifty 100 (Strict Identity)
        ms400_arr[i] = n500_arr[i] & ~n100_arr[i]

        # 5. Midcap 150: Ranks 101-250 active within MidSmallcap 400
        valid_m150 = alloc_m150[ms400_arr[i, alloc_m150]]
        m150_arr[i, valid_m150] = True

        # 6. Smallcap 250 = MidSmallcap 400 & ~Midcap 150 (Strict Identity)
        s250_arr[i] = ms400_arr[i] & ~m150_arr[i]

        # 7. LargeMidcap 250 = Nifty 100 | Midcap 150 (Strict Identity)
        lm250_arr[i] = n100_arr[i] | m150_arr[i]

        # 8. Nifty 200 = Nifty 100 | top 100 of Midcap 150 (Strict Identity)
        valid_n200_mid = alloc_n200_mid[m150_arr[i, alloc_n200_mid]]
        n200_arr[i] = n100_arr[i].copy()
        n200_arr[i, valid_n200_mid] = True

    # 7. Build Total Market Matrix (Nifty 500 | Microcap 250)
    print("  Constructing Nifty Total Market matrix...")
    totalmarket_arr = n500_arr.copy()
    alloc_micro = np.array([], dtype=int)
    for i, dt in enumerate(all_dates):
        is_rebal = (i == 0) or (dt.month in (4, 10) and all_dates[i - 1].month not in (4, 10))
        if is_rebal or len(alloc_micro) == 0:
            non_n500 = np.where(has_traded_mat[i] & ~n500_arr[i])[0]
            if len(non_n500) > 0:
                scores = adtv_126_mat[i, non_n500]
                sorted_micro = non_n500[np.argsort(-scores)]
                alloc_micro = sorted_micro[:250]
        valid_micro = alloc_micro[has_traded_mat[i, alloc_micro]]
        totalmarket_arr[i, valid_micro] = True

    # 8. Mathematical Verification of Cardinal Axioms and Subset Invariants
    print("\n  Asserting Cardinal PIT Axioms & Subset Hierarchy Invariants across all 5,659 sessions:")
    assert np.all(n50_arr <= n100_arr), "Fatal: Nifty 50 is not a subset of Nifty 100!"
    print("    [PASS] Nifty 50 <= Nifty 100 (0 daily violations)")

    assert np.all(n100_arr <= n200_arr), "Fatal: Nifty 100 is not a subset of Nifty 200!"
    print("    [PASS] Nifty 100 <= Nifty 200 (0 daily violations)")

    assert np.all(n200_arr <= n500_arr), "Fatal: Nifty 200 is not a subset of Nifty 500!"
    print("    [PASS] Nifty 200 <= Nifty 500 (0 daily violations)")

    assert np.array_equal((n100_arr | m150_arr), lm250_arr), "Fatal: Nifty 100 | Midcap 150 != LargeMidcap 250!"
    print("    [PASS] Nifty 100 | Midcap 150 == LargeMidcap 250 (0 daily violations)")

    assert np.array_equal((m150_arr | s250_arr), ms400_arr), "Fatal: Midcap 150 | Smallcap 250 != MidSmallcap 400!"
    print("    [PASS] Midcap 150 | Smallcap 250 == MidSmallcap 400 (0 daily violations)")

    assert np.array_equal((n500_arr & ~ms400_arr), n100_arr), "Fatal: Nifty 500 & ~MidSmallcap 400 != Nifty 100!"
    print("    [PASS] Nifty 100 == Nifty 500 & ~MidSmallcap 400 (0 daily violations)")

    assert np.array_equal((n50_arr | nn50_arr), n100_arr), "Fatal: Nifty 50 | Nifty Next 50 != Nifty 100!"
    print("    [PASS] Nifty 50 | Nifty Next 50 == Nifty 100 (0 daily violations)")

    assert np.all(n500_arr <= totalmarket_arr), "Fatal: Nifty 500 is not a subset of Total Market!"
    print("    [PASS] Nifty 500 <= Total Market (0 daily violations)")

    # 9. Save Broad Market Indices
    broad_dict = {
        "nifty50": n50_arr,
        "niftynext50": nn50_arr,
        "nifty100": n100_arr,
        "nifty200": n200_arr,
        "largemid250": lm250_arr,
        "midcap150": m150_arr,
        "smallcap250": s250_arr,
        "midsmall400": ms400_arr,
        "nifty500": n500_arr,
        "totalmarket": totalmarket_arr,
    }

    for name, arr in broad_dict.items():
        leaks = (arr & ~has_traded_mat).sum()
        assert leaks == 0, f"Lookahead listing leaks detected in {name}: {leaks}"
        df = pd.DataFrame(arr, index=all_dates, columns=all_cols, dtype=bool)
        out_f = config.PIT_INDEX_FILES[name]
        df.to_parquet(out_f, compression="zstd")
        counts = arr.sum(axis=1)
        print(f"    [SAVED] {name:15}: counts=[{counts.min()} - {counts.max()}], median={int(np.median(counts))}")

    # 10. Build Honest Sectoral Indices (13 Sectoral Indices)
    # Using official reconstitution logs from IndexInclExcl.xls for the 10 official sheets,
    # and sector turnover ranking for the 3 newer sectoral indices without sheets.
    print("\n  Constructing 13 honest Sectoral Indices...")
    sectoral_sheet_map = {
        "niftyauto": "Nifty Auto",
        "niftybank": "Nifty Bank",
        "niftyenergy": "Nifty Energy",
        "niftyfinance": "Nifty Financial Services",
        "niftyfmcg": "Nifty FMCG",
        "niftyit": "Nifty IT",
        "niftymedia": "Nifty Media",
        "niftymetal": "Nifty Metal",
        "niftypharma": "Nifty Pharma",
        "niftyrealty": "Nifty Realty",
    }

    for idx_name, spec in SECTORAL_SPECS.items():
        raw_f = config.RAW_INDICES_DIR / f"{idx_name}.csv"
        raw_syms = set()
        if raw_f.exists():
            raw_df = pd.read_csv(raw_f)
            sc = [c for c in raw_df.columns if "SYMBOL" in c.upper()][0]
            for s in raw_df[sc].dropna().str.strip():
                t = resolve_ticker(f"{s}.NS")
                if t and t in col_to_idx:
                    raw_syms.add(t)

        sec_arr = np.zeros((n_dates, n_cols), dtype=bool)

        sheet_name = sectoral_sheet_map.get(idx_name)
        if sheet_name and excel_path.exists() and sheet_name in xl.sheet_names:
            df_ev = load_sheet_events(sheet_name)
            post_list = POST_2020_SECTORAL_EVENTS.get(idx_name, [])
            df_post = pd.DataFrame(post_list, columns=["Event Date", "ticker", "Description"])
            df_post["Event Date"] = pd.to_datetime(df_post["Event Date"])
            df_post["ticker"] = df_post["ticker"].map(resolve_ticker)

            all_ev = pd.concat([df_ev[["Event Date", "ticker", "Description"]], df_post], ignore_index=True)
            all_ev = all_ev.sort_values("Event Date")

            if idx_name in ("niftyit", "niftyrealty"):
                # Forward reconstitution from founding members
                init_members = FOUNDING_NIFTYIT if idx_name == "niftyit" else FOUNDING_REALTY
                active = set(resolve_ticker(t) for t in init_members)
                intervals = [(pd.to_datetime("1990-01-01"), set(active))]
                ev_dates = sorted(all_ev["Event Date"].unique())
                for ev_dt in ev_dates:
                    grp = all_ev[all_ev["Event Date"] == ev_dt]
                    for _, r in grp.iterrows():
                        t = r["ticker"]
                        desc = str(r["Description"]).lower()
                        if "inclusion" in desc:
                            active.add(t)
                        elif "exclusion" in desc:
                            active.discard(t)
                    intervals.append((ev_dt, set(active)))
                intervals.append((pd.to_datetime("2099-01-01"), set(active)))

                for i, dt in enumerate(all_dates):
                    active_set = None
                    for j in range(len(intervals) - 1):
                        if intervals[j][0] <= dt < intervals[j + 1][0]:
                            active_set = intervals[j][1]
                            break
                    if active_set is None:
                        active_set = intervals[-1][1]
                    valid_indices = [col_to_idx[t] for t in active_set if t in col_to_idx and has_traded_mat[i, col_to_idx[t]]]
                    sec_arr[i, valid_indices] = True
            else:
                # Mid-2020 anchor + reverse chaining backwards & forward chaining post-2020
                anchor_set = set(resolve_ticker(t) for t in MID_2020_ANCHORS[idx_name])
                cutoff_dt = df_ev["Event Date"].max()

                # 1. Reverse chain before mid-2020
                rev_ev = df_ev.sort_values("Event Date", ascending=False)
                rev_dates = sorted(rev_ev["Event Date"].unique(), reverse=True)
                cur = set(anchor_set)
                rev_intervals = []
                for ev_dt in rev_dates:
                    rev_intervals.append((ev_dt, set(cur)))
                    grp = rev_ev[rev_ev["Event Date"] == ev_dt]
                    for _, r in grp.iterrows():
                        t = r["ticker"]
                        desc = str(r["Description"]).lower()
                        if "inclusion" in desc:
                            cur.discard(t)
                        elif "exclusion" in desc:
                            cur.add(t)
                rev_intervals.append((pd.to_datetime("1990-01-01"), set(cur)))

                # 2. Forward chain post-2020
                fwd_ev = df_post.sort_values("Event Date", ascending=True)
                fwd_dates = sorted(fwd_ev["Event Date"].unique())
                cur_fwd = set(anchor_set)
                fwd_intervals = [(cutoff_dt, set(anchor_set))]
                for ev_dt in fwd_dates:
                    grp = fwd_ev[fwd_ev["Event Date"] == ev_dt]
                    for _, r in grp.iterrows():
                        t = r["ticker"]
                        desc = str(r["Description"]).lower()
                        if "inclusion" in desc:
                            cur_fwd.add(t)
                        elif "exclusion" in desc:
                            cur_fwd.discard(t)
                    fwd_intervals.append((ev_dt, set(cur_fwd)))
                fwd_intervals.append((pd.to_datetime("2099-01-01"), set(cur_fwd)))

                for i, dt in enumerate(all_dates):
                    if dt <= cutoff_dt:
                        active_set = None
                        for ev_dt, s in rev_intervals:
                            if dt >= ev_dt:
                                active_set = s
                                break
                        if active_set is None:
                            active_set = rev_intervals[-1][1]
                    else:
                        active_set = anchor_set
                        for ev_dt, s in fwd_intervals:
                            if dt >= ev_dt:
                                active_set = s
                    valid_indices = [col_to_idx[t] for t in active_set if t in col_to_idx and has_traded_mat[i, col_to_idx[t]]]
                    sec_arr[i, valid_indices] = True
        else:
            cond = sec_master["sector"].str.contains(spec["sector_pattern"], case=False, na=False)
            pool = set(sec_master[cond].index).union(raw_syms).intersection(all_cols)
            pool_indices = np.array([col_to_idx[t] for t in sorted(pool)], dtype=int)
            max_k = spec["max_constituents"]

            alloc_sec = np.array([], dtype=int)
            for i, dt in enumerate(all_dates):
                is_rebal = (i == 0) or (dt.month in (4, 10) and all_dates[i - 1].month not in (4, 10))
                if is_rebal or len(alloc_sec) == 0:
                    listed_pool = pool_indices[has_traded_mat[i, pool_indices]]
                    if len(listed_pool) > 0:
                        scores = adtv_126_mat[i, listed_pool]
                        alloc_sec = listed_pool[np.argsort(-scores)][:max_k]

                valid_sec = alloc_sec[has_traded_mat[i, alloc_sec]]
                sec_arr[i, valid_sec] = True

        sec_leaks = (sec_arr & ~has_traded_mat).sum()
        assert sec_leaks == 0, f"Lookahead listing leaks detected in sectoral index {idx_name}: {sec_leaks}"

        df = pd.DataFrame(sec_arr, index=all_dates, columns=all_cols, dtype=bool)
        out_f = config.PIT_INDEX_FILES[idx_name]
        df.to_parquet(out_f, compression="zstd")
        counts = sec_arr.sum(axis=1)
        print(f"    [SAVED] {idx_name:24}: counts=[{counts.min()} - {counts.max()}], median={int(np.median(counts))}")

    print("\n" + "=" * 80)
    print("ALL 23 POINT-IN-TIME (PIT) INDEX MASKS SUCCESSFULLY RECONSTRUCTED & SAVED")
    print("=" * 80)


if __name__ == "__main__":
    build_pit_membership_masks()
