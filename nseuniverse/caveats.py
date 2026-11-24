"""Catalogue of the known limits of the data, each with its backtest impact and the way to handle it.

    api.caveats()                    every flag, with live counts of what it touches in this build
    api.caveats("PRICES")            one category (PRICES, ACTIONS, MEMBERSHIP, INDEX, MARKET, GENERAL)
    api.explain(symbols, start, end, index=None)
                                     the flags that apply to this selection, with the dates and securities concerned

A flag is a fact about the data, not an opinion: each one names the column, function or file that shows it.
"""
from __future__ import annotations

import pandas as pd

COLUMNS = ["id", "category", "severity", "what", "backtest_impact", "handling", "shown_by"]

# severity: HIGH = results can be wrong if ignored; MEDIUM = changes results at the margin; LOW = good to know.
CATALOGUE = [
    ("DOCUMENTED_ADJUSTMENT_BREAK", "PRICES", "MEDIUM",
     "Demergers and schemes the feed gives no ratio for (about 108), plus overnight moves nothing explains. The break stays in the adjusted series.",
     "One day of fake return (typically -30% to -70%) on the day of the event; cumulative adjusted prices before it are overstated or understated by that move.",
     "prices() sets adj_return to NaN on documented-event days (class ON_ACTION_DAY) by default (mask_gaps='events'); UNEXPLAINED moves are flagged but not masked because they can be real crashes (mask_gaps='all' masks them too). The days are in frame.attrs['flagged'] and api.adjustment_gaps(). Do not compound adj_close across a flagged day.",
     "prices().adj_gap and adj_gap_class; api.adjustment_gaps()"),
    ("DEMERGER_ESTIMATED_FACTOR", "PRICES", "MEDIUM",
     "Five demergers carry an ESTIMATED adjustment factor (data/curated/demerger_estimates.csv: Bajaj Holdings 2008, Alembic 2011, Triveni 2011, ABFRL 2025, SKF India 2025): the documented 1:1 ratio, valued at the first listing day of the new company as parent close / (parent close + new close). Accepted only where it agrees with the parent's own ex-day move within 10% (it differed by -6% to +3%); three other 1:1 demergers (Zuari, Orient Paper, Raymond) disagreed by 22-53% and stay unadjusted.",
     "Adjusted prices before the event are scaled by an estimate, accurate to a few percent, not exact. The event day's own return carries that error.",
     "The event day is class DEMERGER_ESTIMATED and its adj_return is NaN by default (mask_gaps='events'). Use adjust_mode=None if you need exact prices.",
     "adjustments kind DEMERGER_EST; prices().adj_gap_class"),
    ("UNQUANTIFIED_CORPORATE_ACTIONS", "ACTIONS", "MEDIUM",
     "Events the feed gives no usable size for: rights issues with no issue price, text the parser cannot read (about 90 UNPARSED/UNKNOWN since 2007), and about 600 mergers, demergers, buy-backs and capital reductions: recorded, not quantified.",
     "No adjustment is applied. For rights this shifts earlier adjusted prices by the missing dilution (typically a few percent to 20%).",
     "Treat the security's returns around the ex-date as unreliable; list the events with api.explain().",
     "build/actions/events.parquet kinds UNPARSED, UNKNOWN, SCHEME"),
    ("NOT_SERVED_ADJUSTED", "PRICES", "MEDIUM",
     "Adjusted prices are refused for SME-platform securities (the feed holds no records for them) and for the named securities in data/curated/adjustment_unreliable.csv (ETFs with non-round unit ratios, SUNTV, CCAVENUE, GULFPETRO, AHLEAST). ETFs are not otherwise identifiable in the data: other ETFs trade in series EQ and are adjusted like any stock.",
     "prices() raises CoverageError for them with an adjust_mode; as-published prices (adjust_mode=None) are exact.",
     "Build the equity universe from api.securities() and drop api.sme_securities() and api.unreliable_adjusted(); ETFs have to be excluded by your own list.",
     "api.sme_securities(); api.unreliable_adjusted()"),
    ("EX_DATE_NOT_ANNOUNCEMENT_DATE", "ACTIONS", "LOW",
     "NSE's feed carries no announcement dates; adjustments use ex-dates. This is point-in-time safe for prices, but 'what was known when' is not available.",
     "as_of= limits actions by ex-date, not by announcement date; a strategy that reacts to announcements cannot be tested.",
     "Do not use the feed to time announcement-driven signals.",
     "prices(as_of=...)"),
    ("FEED_ENDS", "ACTIONS", "MEDIUM",
     "The corporate-action feed is a download as of a date (see the manifest); actions announced after it are missing and appear as unexplained jumps.",
     "Recent splits and bonuses are not adjusted until the feed is refreshed.",
     "Refresh the feed after each month-end (A19) and rebuild; treat the last weeks as unadjusted.",
     "data/raw/corporate_actions; ratchet unexplained moves"),
    ("FEED_LAGS_BHAVCOPY", "ACTIONS", "MEDIUM",
     "The newest corporate-action feed file ends more than 14 days before the newest bhavcopy. The feed cannot be downloaded by script, so it ages between manual downloads; `update` prints a warning when this happens.",
     "Splits and bonuses after the feed end are not applied; a split shows as a one-day crash in adjusted prices.",
     "Download the feed in a browser (NSE Corporate Actions, Equity), save it in data/raw/corporate_actions, rebuild; until then treat the weeks after the feed end as unadjusted.",
     "actions.feed_lag_warning(); `update` output; caveats() affected"),
    ("PARTIAL_WEEKEND_SESSIONS", "MARKET", "LOW",
     "Two weekend special sessions, 2010-05-16 and 2012-11-11, are in the trading calendar with partial bhavcopies (7 and 14 symbols) and no index file.",
     "A rule that assumes a full cross-section on every trading day breaks on those two days; index members look untraded and index levels are missing.",
     "Skip 2010-05-16 and 2012-11-11, or use only days with a full cross-section.",
     "calendar in verify (weekend sessions); docs/AUDIT_REPORT.md S3-6, S3-7"),
    ("T0_CLOSE_OUTSIDE_RANGE", "PRICES", "LOW",
     "On 217 of 241 rows of series T0 (trade-to-trade, one-time segment) the close lies outside the day's low-high range. No other series has this.",
     "A check that close is within [low, high] fails on T0 rows.",
     "Exclude series T0 from such checks, or from the universe.",
     "bhavcopy series == 'T0'; docs/AUDIT_REPORT.md S3-8"),
    ("MEMBERSHIP_NOT_VERIFIED", "MEMBERSHIP", "HIGH",
     "Index membership is verified only on the windows in coverage() (from 2010-01-01, or from the index's launch if later); other dates and indices outside the 27 verified equity indices are refused.",
     "No member list exists for those dates; any estimate would be a model.",
     "Query within api.coverage() windows. The API raises CoverageError otherwise.",
     "CoverageError from index_members(); api.coverage()"),
    ("MEMBERSHIP_BACKFILLED", "MEMBERSHIP", "HIGH",
     "index_members(..., backfill=True) returns, for dates from 2007-01-01 up to an index's first verified day, the first verified list restricted to securities already trading.",
     "Survivorship and look-ahead bias: members are chosen with knowledge of later outcomes. Not suitable for out-of-sample claims.",
     "Opt-in only. Use it as a stress test or for a proxy universe, not as the published membership.",
     "membership_status='BACKFILLED_UNVERIFIED'; backfilled_from; DataQualityWarning"),
    ("MEMBERSHIP_RECONSTRUCTED", "MEMBERSHIP", "HIGH",
     "index_members(..., reconstruct=True) returns, for any unverified date from the first review (2007-04), a rule-based rebuild: rank by 6-month average market capitalisation with the current methodology bands. Shares outstanding are the 2024-26 issued capital carried back through splits and bonuses (imputed from traded value for securities with none), free float, F&O/turnover screens and buffers are ignored, and sectoral indices are not rebuilt.",
     "A model, not NSE's list: members near each rank boundary are often wrong, delisted stocks are sized from traded value, and the rebuild uses information (today's share counts) not known then. Measured overlap with the verified lists is in api.reconstruction_accuracy().",
     "Opt-in only; read reconstruction_accuracy() for the index and era you need and do not report results as using published membership. Prefer verified dates; use the rebuild as a stress test or a proxy universe.",
     "membership_status='RECONSTRUCTED_UNVERIFIED'; DataQualityWarning; api.index_start_dates()"),
    ("DUAL_CLASS_EXTRA_MEMBER", "MEMBERSHIP", "LOW",
     "Tata Motors DVR was an extra security in several indices (51 securities for 50 companies) while the parent was a member.",
     "Member counts exceed the official size by one on those days; weights are not in the data.",
     "Count companies, not securities, if a rule depends on the index size.",
     "data/curated/index_dual_class.csv"),
    ("INDEX_HISTORY_IS_BACKCAST", "INDEX", "MEDIUM",
     "NSE's published index levels before an index's launch date are back-calculated by NSE (for example Nifty Midcap 150 from 2005-04-01).",
     "The level series exists, but the constituents behind it were never published, so it cannot be reproduced from membership.",
     "Use the levels as benchmarks, not as evidence of what the index held.",
     "index_values(); methodology document"),
    ("DELIVERY_SOURCE_DISAGREEMENTS", "MARKET", "LOW",
     "NSE's delivery file and the bhavcopy disagree on traded quantity for about 0.07% of rows.",
     "A delivery percentage on those rows rests on one of two conflicting volumes.",
     "Compare api.delivery().traded_qty with the bhavcopy volume when a delivery signal triggers on a single day.",
     "verify check `market`"),
    ("SEC_ID_NOT_STABLE", "GENERAL", "MEDIUM",
     "sec_id labels are renumbered when the data is rebuilt.",
     "Anything saved by sec_id can point at another security after a rebuild.",
     "Key durable data by symbol plus ISIN.",
     "api.securities()"),
]


def catalogue() -> pd.DataFrame:
    return pd.DataFrame(CATALOGUE, columns=COLUMNS)
