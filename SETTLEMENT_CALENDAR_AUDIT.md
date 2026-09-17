# NSE capital-market settlement calendar: development period

The frozen [`nse_settlement_calendar_2015_2023.parquet`](data/processed/nse_settlement_calendar_2015_2023.parquet) covers every calendar date from **2015-04-01 through 2023-03-31** (2,922 distinct dates). It has 1,938 settlement business days and 150 weekday settlement closures. Saturday and Sunday are not settlement business days even if a special equity session traded. The columns are `date`, `settlement_business_day`, `source_notice`, `source_date`, and `notes`.

The build parses the capital-market holiday tables from nine official NSE Clearing annual PDF circulars: [2015 CMPT28438](https://archives.nseindia.com/content/circulars/CMPT28438.pdf), [2016 CMPT31421](https://archives.nseindia.com/content/circulars/CMPT31421.pdf), [2017 CMPT33820](https://archives.nseindia.com/content/circulars/CMPT33820.pdf), [2018 revised CMPT36634](https://archives.nseindia.com/content/circulars/CMPT36634.pdf), [2019 CMPT39791](https://archives.nseindia.com/content/circulars/CMPT39791.pdf), [2020 CMPT42962](https://archives.nseindia.com/content/circulars/CMPT42962.pdf), [2021 CMPT46687](https://archives.nseindia.com/content/circulars/CMPT46687.pdf), [2022 CMPT50630](https://archives.nseindia.com/content/circulars/CMPT50630.pdf), and [2023 CMPT54855](https://archives.nseindia.com/content/circulars/CMPT54855.pdf). The 2018 revised circular supersedes the prior annual version.

The [NSE Clearing circular archive](https://www.archive.nseclearing.in/circulars) was searched for annual holiday notices and changes in capital-market settlement schedules. Two additional closures within the development period were applied from the official amendments: **2017-02-21** municipal corporation elections ([CMPT34182](https://archives.nseindia.com/content/circulars/CMPT34182.pdf)) and **2018-04-02** annual bank closing ([CMPT37310](https://archives.nseindia.com/content/circulars/CMPT37310.pdf)). Later 2023 changes listed by the archive fall after the development cutoff and were not used. These searches and notices establish the documented calendar; they do not prove no unindexed emergency circular ever existed.

All 11 PDFs are preserved under [`data/evidence/settlement_official`](data/evidence/settlement_official), with source URL, issue date, local path, and SHA-256 in [`source_manifest.csv`](data/evidence/settlement_official/source_manifest.csv). [`settlement_calendar.py`](settlement_calendar.py) checks parsed date/weekday consistency, annual coverage, and the exact wording/date of the amendments before writing the Parquet file. The development equity trading calendar was read with a `date <= 2023-03-31` predicate only to compare trading and settlement dates. The account runner constructs holiday-date metadata through 2023-04-10 in memory to assign late-March obligations; it reads **no** April 2023 market prices.

| Span | Calendar dates | Settlement business days |
|---|---:|---:|
| Apr–Dec 2015 | 275 | 180 |
| 2016 | 366 | 241 |
| 2017 | 365 | 242 |
| 2018 | 365 | 240 |
| 2019 | 365 | 244 |
| 2020 | 366 | 245 |
| 2021 | 365 | 241 |
| 2022 | 365 | 244 |
| Jan–Mar 2023 | 90 | 61 |

For 1,977 equity trading dates through 2023-03-27 where both comparison dates lie inside the frozen calendar, **94** T+2 settlement dates differ from the date two trading sessions later; **65 distinct weekday settlement closures** occur in those affected settlement windows. The two amendments each affect two such trade dates. For instance, a 2017-02-17 trade settles 2017-02-22 rather than 2017-02-21; a 2018-03-28 trade settles 2018-04-04 rather than treating the bank closure on April 2 as a business day. A 2015-06-29 trade settles 2015-07-02 because July 1 is a settlement holiday even though equity traded. Comparing to two calendar days differs for 940 of those trade dates, primarily because of weekends.

This is the frozen project's **uniform T+2 availability convention**, including after India's actual move toward T+1. It is not a reconstruction of every security's actual historical settlement cycle. Focused calendar tests passed; the full suite passed at the time of this audit.
