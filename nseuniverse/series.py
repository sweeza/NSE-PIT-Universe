"""Series codes. Equity and SME-equity series define the equity universe; every other series
(debt, gold bonds, preference shares, warrants, InvITs, ...) stays in the bhavcopy table but is
outside the equity universe and is never linked to an equity security by ISIN."""
PRIMARY_SERIES = ["EQ", "BE", "BZ", "BL", "SM", "ST", "SZ", "BT", "IL"]
EQUITY_SERIES = frozenset(PRIMARY_SERIES)
