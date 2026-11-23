# Index availability (generated 2026-11-23 by `api.index_availability()`)

Use `reliable_from`: membership is verified without a gap from that date to `membership_to`. Dates before `membership_from` can only be backfilled (`index_members(..., backfill=True)`, flagged `BACKFILLED_UNVERIFIED`). `values_from` is the first index level NSE publishes; levels before an index's launch are NSE's own back-calculation. `thin` = `reliable_from` is before 2010-01-01 (2007-2009 rests on less evidence). Regenerate after every build; the function is the source of truth.

| Index | Category | Index levels from | Membership verified from | Reliable from | Status | Gaps (unverified stretches inside) | Thin |
|---|---|---|---|---|---|---|---|
| Nifty 50 (`NIFTY50`) | broad_market | 1990-07-03 | 2007-01-02 | 2007-01-02 | FULL |  | yes |
| Nifty Next 50 (`NIFTYNEXT50`) | broad_market | 1996-11-04 | 2007-01-02 | 2007-01-02 | FULL |  | yes |
| Nifty 100 (`NIFTY100`) | broad_market | 2003-01-01 | 2007-01-02 | 2007-01-02 | FULL |  | yes |
| Nifty Next 100 (`NIFTYNEXT100`) | broad_market | 2010-10-01 |  | none | UNVERIFIED |  |  |
| Nifty 200 (`NIFTY200`) | broad_market | 2004-01-01 | 2010-11-01 | 2010-11-01 | FULL |  |  |
| Nifty Total Market (`NIFTYTOTALMARKET`) | broad_market | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty 500 (`NIFTY500`) | broad_market | 1995-01-01 | 2013-06-11 | 2013-08-26 | GAPS | 2013-08-02..2013-08-05; 2013-08-20..2013-08-25 |  |
| Nifty500 Multicap 50:25:25 (`NIFTY500MULTICAP502525`) | broad_market | 2005-04-01 | 2013-06-11 | 2013-08-26 | GAPS | 2013-08-02..2013-08-05; 2013-08-20..2013-08-25 |  |
| Nifty500 LargeMidSmall Equal-Cap Weighted (`NIFTY500LARGEMIDSMALLEQUALCAPWEIGHTED`) | broad_market | 2005-04-01 | 2013-06-11 | 2013-08-26 | GAPS | 2013-08-02..2013-08-05; 2013-08-20..2013-08-25 |  |
| Nifty 1000 (`NIFTY1000`) | broad_market | 2007-09-24 |  | none | UNVERIFIED |  |  |
| Nifty Midcap150 (`NIFTYMIDCAP150`) | broad_market | 2005-04-01 | 2016-09-30 | 2016-09-30 | FULL |  |  |
| Nifty Midcap 50 (`NIFTYMIDCAP50`) | broad_market | 2004-01-01 | 2012-09-28 | 2012-09-28 | FULL |  |  |
| Nifty Midcap Select (`NIFTYMIDCAPSELECT`) | broad_market | 2005-10-03 |  | none | UNVERIFIED |  |  |
| Nifty Midcap 100 (`NIFTYMIDCAP100`) | broad_market | 2003-01-01 | 2012-09-28 | 2012-09-28 | FULL |  |  |
| Nifty Smallcap 500 (`NIFTYSMALLCAP500`) | broad_market | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty Smallcap 250 (`NIFTYSMALLCAP250`) | broad_market | 2005-04-01 | 2016-09-30 | 2016-09-30 | FULL |  |  |
| Nifty Smallcap 50 (`NIFTYSMALLCAP50`) | broad_market | 2005-04-01 | 2019-03-29 | 2019-03-29 | FULL |  |  |
| Nifty Smallcap 100 (`NIFTYSMALLCAP100`) | broad_market | 2004-01-01 | 2018-04-02 | 2018-04-02 | FULL |  |  |
| Nifty Microcap 250 (`NIFTYMICROCAP250`) | broad_market | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty LargeMidcap 250 (`NIFTYLARGEMIDCAP250`) | broad_market | 2005-04-01 | 2016-09-30 | 2016-09-30 | FULL |  |  |
| Nifty MidSmallcap 400 (`NIFTYMIDSMALLCAP400`) | broad_market | 2005-04-01 | 2013-06-11 | 2013-08-26 | GAPS | 2013-08-02..2013-08-05; 2013-08-20..2013-08-25 |  |
| Nifty MidSmallcap400 50:50 (`NIFTYMIDSMALLCAP4005050`) | broad_market | 2005-04-01 | 2013-06-11 | 2013-08-26 | GAPS | 2013-08-02..2013-08-05; 2013-08-20..2013-08-25 |  |
| Nifty India FPI 150 (`NIFTYINDIAFPI150`) | broad_market | 2022-10-03 |  | none | UNVERIFIED |  |  |
| Nifty Auto (`NIFTYAUTO`) | sectoral | 2004-01-01 | 2019-03-29 | 2019-03-29 | FULL |  |  |
| Nifty Bank (`NIFTYBANK`) | sectoral | 2000-01-01 | 2007-01-02 | 2007-01-02 | FULL |  | yes |
| Nifty Capital Goods (`NIFTYCAPITALGOODS`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty Cement (`NIFTYCEMENT`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty Chemicals (`NIFTYCHEMICALS`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty Commercial & Transport Services (`NIFTYCOMMERCIAL&TRANSPORTSERVICES`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty Construction (`NIFTYCONSTRUCTION`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty Consumer Durables (`NIFTYCONSUMERDURABLES`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty Consumer Services (`NIFTYCONSUMERSERVICES`) | sectoral | 2020-07-01 |  | none | UNVERIFIED |  |  |
| Nifty Financial Services (`NIFTYFINANCIALSERVICES`) | sectoral | 2004-01-01 | 2018-04-02 | 2018-04-02 | FULL |  |  |
| Nifty Financial Services 25/50 (`NIFTYFINANCIALSERVICES2550`) | sectoral | 2004-01-01 | 2018-04-02 | 2018-04-02 | FULL |  |  |
| Nifty Financial Services Ex Bank (`NIFTYFINANCIALSERVICESEXBANK`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty FMCG (`NIFTYFMCG`) | sectoral | 1996-01-01 | 2007-11-29 | 2007-11-29 | FULL |  | yes |
| Nifty Healthcare (`NIFTYHEALTHCARE`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty Hospitals (`NIFTYHOSPITALS`) | sectoral | 2021-03-31 |  | none | UNVERIFIED |  |  |
| Nifty Housing Finance (`NIFTYHOUSINGFINANCE`) | sectoral | 2018-04-02 |  | none | UNVERIFIED |  |  |
| Nifty Insurance (`NIFTYINSURANCE`) | sectoral | 2019-09-27 |  | none | UNVERIFIED |  |  |
| Nifty IT (`NIFTYIT`) | sectoral | 1996-01-01 | 2015-05-29 | 2015-05-29 | FULL |  |  |
| Nifty Media (`NIFTYMEDIA`) | sectoral | 2005-12-30 | 2020-06-26 | 2020-06-26 | FULL |  |  |
| Nifty Metal (`NIFTYMETAL`) | sectoral | 2004-01-01 | 2010-11-01 | 2016-04-01 | GAPS | 2015-03-27..2016-03-31 |  |
| Nifty NBFC (`NIFTYNBFC`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty Oil and Gas (`NIFTYOIL&GAS`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty Pharma (`NIFTYPHARMA`) | sectoral | 2001-01-01 | 2007-01-02 | 2007-01-02 | FULL |  | yes |
| Nifty Power (`NIFTYPOWER`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty Private Bank (`NIFTYPRIVATEBANK`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty PSU Bank (`NIFTYPSUBANK`) | sectoral | 2004-01-01 | 2007-01-02 | 2020-06-26 | GAPS | 2016-09-30..2017-09-28; 2019-12-27..2020-06-25 |  |
| Nifty Realty (`NIFTYREALTY`) | sectoral | 2006-12-29 | 2007-08-06 | 2007-08-06 | FULL |  | yes |
| Nifty REITs & Realty (`NIFTYREITS&REALTY`) | sectoral | 2021-07-01 |  | none | UNVERIFIED |  |  |
| Nifty Retail (`NIFTYRETAIL`) | sectoral | 2018-04-02 |  | none | UNVERIFIED |  |  |
| Nifty Telecommunications (`NIFTYTELECOMMUNICATIONS`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty500 Healthcare (`NIFTY500HEALTHCARE`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty MidSmall Financial Services (`NIFTYMIDSMALLFINANCIALSERVICES`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty MidSmall Healthcare (`NIFTYMIDSMALLHEALTHCARE`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |
| Nifty MidSmall IT & Telecom (`NIFTYMIDSMALLIT&TELECOM`) | sectoral | 2005-04-01 |  | none | UNVERIFIED |  |  |

27 of 57 in-scope indices have verified membership; the other 30 have index levels only (no historical constituent sheet exists for them), so `index_members` refuses them on every date.
