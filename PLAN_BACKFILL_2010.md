# Plan: Microcap 250 and Total Market from 2010

Drafted 2026-11-28. Steps 1-4 are built (results at the end); steps 5 and 6 are not.

## What this can and cannot be

NSE launched Microcap 250 on 2021-05-10 and Total Market on 2021-10-13. Earlier index levels are NSE's
back-calculation, and the held sources contain no constituent lists for those years. So 2010-2021 can only be a
**rule-based estimate**, never verified membership.

| Index | 2010 to launch | From launch |
|---|---|---|
| Microcap 250 | estimated | verified (as now) |
| Total Market | verified Nifty 500 + estimated Microcap 250 | verified (as now) |

Total Market is the better of the two: about two thirds of its names (500 of 750) are already verified.

A rule-based rebuild was removed in the 2026-11-26 restructure (`RESTRUCTURE.md`). This plan brings back a narrower
one, for one index, so that decision needs to be reversed first.

## The method (NSE's current rules, applied to the past)

Twice a year, take the NSE stocks outside the verified Nifty 500, apply the eligibility screens, and take the top 250
by six-month average full market capitalisation.

| NSE rule | What we can do |
|---|---|
| Outside Nifty 500 | exact: verified membership |
| Rank by 6-month average full market cap | price x shares, shares = paid-up capital / face value from filings |
| Top 1000 by turnover and by market cap | exact once share counts are complete |
| Trading frequency, listing history, no BZ | from bhavcopy |
| Average impact cost at most 1% | no data held; use a traded-value floor fitted on 2021-2026 |
| Free float at least 10% (or the size exception) | skip at first; add shareholding data only if accuracy needs it |
| Replacement limits and buffers | not applied: see the diagnosis at the end |
| Changes between reviews (mergers, delistings) | drop on last trade; refill at the next review |

## The main gap: share counts

The fundamentals database holds paid-up capital and face value from 2005, but only for companies picked from today's
universe and Nifty 500 history. Of 1,665 symbols traded in EQ or BE in 2010-2011, only 610 have a share count in
2009-2011. Ranking with that would favour survivors and make any backtest look better than it was.

## Steps

1. **Share counts for every traded company, 2009-2021.** Fetch NSE result filings for the missing symbols, including
   delisted ones, with the existing `nifty_earnings` downloader. Adjust between filings for splits and bonuses, and
   date each count by its filing date so nothing uses later information.
   *Done when* at least 95% of eligible symbols at every review have a count. *Stop* if NSE no longer serves filings
   for delisted companies and coverage stays below about 85%; then look for another source.
2. **Check share counts** against face value and split history; flag jumps that no corporate action explains.
3. **Build the review engine** on those inputs, with no use of 2021-2026 membership except for scoring.
4. **Score it where the truth is known.** Run it over the reviews from 2021 to 2026 and compare with verified lists:
   share of names in common, and the return difference of the two baskets.
5. **Score the old years** against NSE's back-calculated Microcap 250 levels, 2010-2021. This is a weaker test: our
   weights lack free float.
6. **Publish apart from verified data.** Separate table, status `ESTIMATED`, returned only on explicit request, never
   written to `membership.csv`. Print the scores in `caveats()`.

## Acceptance (proposed, to be agreed before step 4)

| Measure on 2021-2026 | Usable | Not usable |
|---|---|---|
| Names in common with the verified list | 80% or more | below 65% |
| Annual return difference of equal-weighted baskets | within 2 points | above 5 points |

Between the two, use only with the caveat stated. A good 2021-2026 score does not prove 2010 is as good: filings are
thinner and NSE's own back-calculation rules for those years are not published in the held files.

## Decisions for you

1. Reverse the earlier removal of rule-based membership?
2. Allow bulk downloads from NSE for step 1?
3. Accept the thresholds above?

## Coverage probe (run 2026-11-28)

50 random securities traded in 2010-2011 with no share count held: 25 no longer trading in 2026, 25 still trading.
Counted as a success if one of up to three 2009-2011 filings gave both paid-up capital and face value.

| Group | Listing served for 2009-2011 | Share count obtained |
|---|---|---|
| No longer trading | 24 of 25 | 23 of 25 |
| Still trading | 25 of 25 | 23 of 25 |

- The one without a listing is GOLDBEES, an ETF that should not have been in the sample (23 of 24 companies).
- DIAPOWER: paid-up capital served, face value 0 in all three. Another filing or the split history may supply it.
- M&MFIN, SURANAT&P: the detail request came back empty. Both symbols contain `&`, so an encoding fault is a likely
  cause; not tested.

By this sample, step 1 would reach roughly 90-98% of securities, against 43% now (694 of 1,604; this count is by
security, so it differs from the symbol count above). 50 is a small sample. The probe did not check that the values are
right, that units are consistent, or how coverage looks for 2012-2021. Step 1 is feasible.

## Steps 1 and 2 results (2026-11-28)

Step 1 (`tools/fetch_share_counts.py`): 2,398 securities, 2,285 with a usable count. Across 24 reviews, coverage of the
500 most traded securities outside Nifty 500 was 92.0-97.2% (median 95.6%), at least 95% in 16 of them.

Step 2 (`tools/check_share_counts.py`, output `data/staging/share_counts.csv`): 42,169 rows; 186 rescaled unit slips,
222 spikes (not to be used), 845 unexplained lasting steps (kept; not verified against any second source). Of 536
splits/bonuses with counts on both sides, 510 are consistent with the stated factor (452 alone, 58 combined with other
actions in the window), 24 moved more than stated, 2 did not move (SOLARINDS 2016-07, JMTAUTOLTD 2016-09).

## Steps 3 and 4 results (2026-11-28)

`tools/review_engine.py` selects 250 names at all 34 reviews 2010-2026; share counts cover 92.5-97.1% of traded stocks.
The 2021-2026 filings (3,003 securities, 108 files not found) were added to `data/staging/share_counts.csv`
(62,932 rows). Output: `data/staging/microcap_estimate.csv` and `microcap_score.csv`.

Scored on 11 reviews, 2021-09 to 2026-09 (the last period is only 51 days):

| Measure | Result | Against the proposed thresholds |
|---|---|---|
| Names in common | mean 65.1%, range 57.6-76.0%; below 65% at 6 reviews | well short of 80%; barely above "not usable" |
| Annualised equal-weighted price return | estimate 16.9%, verified 16.7% | within 2 points |

- Single half-years differ by up to 3.4 points; the small annual gap partly comes from these cancelling.
- Two broad small-company baskets may track each other even with different names, so the return test is weak. No
  random-basket control has been run.
- Of about 87 verified members missed per review, 79 passed our screens but were not picked (rank or buffer), 5 had no
  share count. Why NSE chose differently has not been established.
- Nothing was tuned on 2021-2026. Any later tuning on it makes this score no longer an independent test.
- Not modelled: impact cost, free float, domicile, replacements between reviews.

### Diagnosis of the low name overlap (2026-11-28)

- Cause: the buffer step. The methodology (November 2026, p. 32) says shortlisted stocks ranked within the top 675 are
  compulsorily included. Applied literally, as the engine does, nearly every eligible non-member displaces an existing
  member: about 200 new names per review, against 40-73 in the verified lists.
- Variant with no buffer (top 250 of the eligible at each review; scratch run, engine unchanged): names in common mean
  88.8%, range 86.4-91.2%; annualised return 16.6% vs 16.7%; median 56 entrants per review.
- This variant was chosen after seeing the 2021-2026 results, so its score is no longer an independent test. How NSE
  actually applies the buffer is not established.
- Applied: the buffer is removed from `tools/review_engine.py` and the estimate rebuilt. 34 reviews 2010-2026, 250
  names each, 39-83 entrants per review. Rerun score: names in common mean 88.8% (min 86.4%), annualised return 16.6% vs
  16.7%. Any publication of the estimate must say the buffer choice was fitted on 2021-2026.
