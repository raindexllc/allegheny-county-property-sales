# Observed findings

Snapshot retrieved: 2026-10-27T15:26:12.218179+00:00.

## The source files have different coverage

| Sale year | Reconciled identities | In both | Annual only | Consolidated only |
|---|---:|---:|---:|---:|
| 2012 | 33,651 | 33,641 | 10 | 0 |
| 2013 | 34,095 | 34,085 | 10 | 0 |
| 2014 | 33,646 | 33,625 | 21 | 0 |
| 2015 | 34,641 | 34,622 | 19 | 0 |
| 2016 | 36,009 | 35,996 | 13 | 0 |
| 2017 | 35,279 | 35,264 | 15 | 0 |
| 2018 | 36,488 | 36,454 | 34 | 0 |
| 2019 | 35,670 | 35,625 | 45 | 0 |
| 2020 | 35,346 | 35,271 | 75 | 0 |
| 2021 | 40,233 | 40,138 | 95 | 0 |
| 2022 | 34,825 | 33,259 | 1,566 | 0 |
| 2023 | 30,859 | 4,653 | 26,206 | 0 |
| 2024 | 31,113 | 4,740 | 26,373 | 0 |
| 2025 | 31,551 | 509 | 31,042 | 0 |
| 2026 | 23,065 | 3 | 23,062 | 0 |

Coverage describes the downloaded resources, not every real-world sale. Missing records do not establish the cause of a coverage discrepancy.

## Transfer composition can change the comparison in either direction

| Municipality | Year | Recorded identities | Standard-valid sales | All priced transfers: median | Standard-valid sales: median | Difference |
|---|---:|---:|---:|---:|---:|---:|
| Pittsburgh | 2025 | 7,754 | 1,864 | \$100,000.00 | \$259,700.00 | 159.7% |
| Clairton | 2020 | 474 | 36 | \$164,000.00 | \$56,500.00 | -65.5% |

Standard-valid means publisher code 0 / VALID SALE, positive price, agreed analytical values, a complete deed key and no same-deed/different-date ambiguity. This is a selected subset of all priced transfers, not a separate population.

Family transfers and repeated multi-parcel deed prices help explain why the groups differ. The category counts and medians are descriptive evidence, not a causal decomposition. The result is not price appreciation or a home-only market estimate.

All conflicting analytical values are withheld; neither source family wins a dispute. Other identity concerns remain flagged, not automatically merged. See review_records.csv for evidence.

Clairton 2020 example: **173 distinct parcels** share deed book 18292/page 134 and repeat **\$185,000.00**. Do not sum this price across those parcel records.
