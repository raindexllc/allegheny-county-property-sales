# `municipality_year` output dictionary

Grain: one municipality and sale year with at least one reconciled candidate transfer identity. The CSV and DuckDB table contain the same ordered analytical rows.

| Field | Meaning |
|---|---|
| `municipality_code` | Source municipality code, with city rollups 100=Pittsburgh, 200=Clairton, 300=Duquesne, 400=McKeesport |
| `municipality` | Municipality name after the four city rollups |
| `sale_year` | Calendar year of `SALEDATE` |
| `recorded_transfers` | Distinct candidate parcel-transfer identities, including unresolved identities |
| `transfers_with_price` | Resolved identities with a non-null price; denominator of the naive price median |
| `missing_price_transfers` | Resolved identities with a missing price |
| `zero_price_transfers` | Resolved identities with an explicit zero price |
| `love_affection_transfers` | Resolved identities with code 3 |
| `multi_parcel_transfers` | Resolved identities with code H |
| `unresolved_conflicts` | Identities whose annual-only versions disagree; price and sale classification withheld |
| `incomplete_deed_keys` | Identities missing deed book, deed page or instrument type |
| `eligible_market_sales` | Resolved identities with standard-valid code 0 and positive price |
| `median_recorded_price` | Median of all non-null resolved prices, including zero and non-market records; nominal dollars |
| `median_market_price` | Median price within the eligible subset; null if none qualify |
| `first_sale_date` | Earliest sale date in the municipality-year group |
| `last_sale_date` | Latest sale date in the municipality-year group |
| `eligible_share` | Eligible sales divided by all recorded transfer identities; fraction from 0 to 1 |
| `median_difference` | Eligible median minus naive median, in dollars |
| `median_difference_pct` | Eligible median / naive median − 1; a fraction, null for a zero denominator |
| `meets_sample_threshold` | At least 30 eligible sales; default display rule, not a statistical confidence claim |
| `latest_observed_year` | This row's year equals the maximum observed sale year in the snapshot; not a guarantee of full-year coverage |

Reconciliation diagnostics in `source_reconciliation.csv` describe presence in source families, competing versions and unresolved counts by sale year. They are audit outputs supporting the single analytical table.

`run_report.json` contains snapshot retrieval time, source inventory and hashes, quality counts, coverage dates, anomaly counts and the analytical CSV checksum. `manifest.json` points to the exact locally landed raw resources used for the submission.
