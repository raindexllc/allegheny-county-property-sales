# `municipality_year`: one municipality and sale year

Only combinations with recorded candidate identities occur. Absent groups do not receive invented zero prices. City rollups use project-assigned IDs; source geography remains available in `normalized` and the checked crosswalk.

| Field | Meaning |
|---|---|
| `municipality_code`, `municipality` | Canonical project municipality, including four city rollups |
| `sale_year` | Calendar year of SALEDATE |
| `recorded_transfers` | Candidate parcel-transfer identities, including records under review |
| `priced_transfers` | Otherwise usable identities with a non-null price; includes zero prices |
| `standard_valid_sales` | Usable identity, code 0 / VALID SALE and positive price |
| `family_transfers` | Usable priced records with code 3 |
| `multi_parcel_transfers` | Usable priced records with code H |
| `other_transfers` | Other usable priced records, including code-0 records with nonpositive price |
| `missing_price_transfers` | Usable identity with missing price |
| `identity_review_transfers` | Disputed analytical values, incomplete deed keys or potential date conflicts |
| `zero_price_transfers` | Priced transfers with explicit zero; overlaps category counts |
| `conflicting_values` | More than one analytical version under the candidate identity |
| `potential_date_conflicts` | Same parcel/book/page/instrument appears on multiple sale dates |
| `incomplete_deed_keys` | Missing book, page or instrument; these diagnostic counts can overlap |
| `median_all_transfer_price` | Median of priced transfers, including zero and non-market classifications |
| `median_standard_valid_price` | Median within the standard-valid subset; null if none qualify |
| `median_family_price` | Median within the family-transfer category |
| `median_multi_parcel_price` | Median within the multi-parcel category; may reflect entire deed prices |
| `median_other_price` | Median within the other-transfer category |
| `first_sale_date`, `last_sale_date` | Observed date bounds for the municipality/year |
| `standard_valid_share` | Standard-valid count / recorded identities; fraction 0–1 |
| `median_gap_dollars` | Standard-valid median − all-priced-transfer median |
| `median_gap_pct` | Standard-valid median / all-priced-transfer median − 1; null if denominator zero |
| `is_partial_year` | Sale year is the snapshot's current calendar year or later; completed years can still receive corrections |

**Six disjoint categories:** standard-valid + family + multi-parcel + other + missing price + identity review = recorded transfers. `priced_transfers` equals the first four categories. Diagnostic flags such as zero prices or incomplete keys are not extra additive categories.

Supporting audit files:

- `source_reconciliation.csv`: presence in both/annual-only/consolidated-only source families, plus identity concerns by year.
- `review_records.csv`: every source variant for identities under review or with descriptive differences, including lineage and flags.
- `repeated_deed_examples.csv`: largest observed repeated-price deed group for each municipality/year, limited to usable H records. This is an illustration, not an estimate of total deed activity.
- `sale_code_profile.csv`: selected, resolved classifications; disputed values are null rather than an arbitrary winner.
- `quality_checks.csv`: violation counts; any nonzero count blocks model publication.
- `manifest.json`: exact locally retained source bytes and resource metadata.
- `run_report.json`: totals, transformations, source inventory and checksums for every data/audit output above.

Never average municipality medians to estimate a county median. Recompute from the underlying usable transfer rows.
