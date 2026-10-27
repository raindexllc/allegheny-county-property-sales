# Code walkthrough

Follow the execution in this order. The dashboard is downstream of the pipeline; its charts do not decide which records qualify.

## 1. Entry point and snapshot selection

`python -m sales_pipeline` invokes `sales_pipeline/__main__.py`.

- With no options: fetch a fresh, complete source snapshot, then model it.
- With `--offline`: rebuild the last complete raw manifest.
- With `--manifest`: rebuild the requested snapshot explicitly.

The raw-snapshot pointer and the successful-publication pointer are different. A newly downloaded snapshot can fail modeling while the previous analytical publication remains selected.

## 2. Discovery and unchanged raw landing

`ingest.discover()` selects resource metadata by consolidated ID and annual naming pattern. It excludes HTML links and verifies annual continuity.

`request_bytes()` makes ordinary HTTP GET requests with a timeout and bounded retries. `save_raw()` computes SHA256 on the exact response bytes before storing them. A resource's URL is mutable; its content hash identifies the downloaded version.

`fetch_snapshot()` saves a manifest only after all resources finish. It compares resource metadata before and after the download to catch a visible refresh during ingestion. This is a consistency check, not a transaction across publisher files.

`verify_snapshot()` recomputes file hashes and checks that the manifest's resource inventory matches its saved CKAN metadata.

## 3. CSV records become typed rows

`model.validate_csv()` checks every CSV record using Python's CSV parser. `load_sources()` loads the same record set into DuckDB with all source fields as text and reconciles row counts. Mixed header/record line endings are handled explicitly.

`01_normalize.sql` parses dates/prices, trims surrounding whitespace, and keeps identifiers as strings. It builds two different hashes:

- **Transfer ID:** the candidate parcel/deed/date/instrument identity.
- **Row fingerprint:** all normalized business fields, excluding CKAN `_id`.

A source correction can change the fingerprint without changing the transfer ID. A repeat sale of one parcel on another date gets another transfer ID. Two parcels on the same deed retain different transfer IDs. Nulls are encoded explicitly through a JSON struct before hashing.

Ward ranges are rolled up to four cities. The quality checks verify that the source descriptions still agree with those ranges.

## 4. Conflicting records remain inspectable

`02_reconcile.sql` groups all versions by transfer ID. A deterministic row order selects a representative, preferring the consolidated version. The order does not turn a disputed annual version into an authoritative record: if annual-only versions conflict, their price, classification, address and recording date are masked in the clean representation.

The shared municipality is used only after asserting that every version has the same municipality. A conflicting consolidated identity blocks publication.

`source_rows` preserves original parsed source fields; `normalized` preserves typed versions; `conflict_records` exposes the competing versions. `clean_transfers` contains one analytical identity with explicit resolution and eligibility fields.

## 5. Build one question-specific analytical table

`03_municipality_year.sql` groups by municipality and sale year.

- The recorded count includes unresolved identities.
- The all-transfer median includes non-null resolved prices, including zero.
- The eligible median includes only resolved standard-valid positive-price sales.
- Missing-price, multi-parcel, family-transfer and unresolved counts make the differences interpretable.
- Percentage difference divides the eligible median by the all-transfer median, then subtracts one. A zero denominator gives null, not infinity.

Never average these medians to create a county median. Recompute a county median from the underlying clean transfer records if needed.

## 6. Fail before publishing

`04_quality_checks.sql` produces a row per check with a violation count. `build_database()` raises `QualityError` if any count is nonzero. `build_model()` writes into a separate generation and changes the publication pointer only after the database, CSV and reports finish successfully.

Useful demonstrations:

```bash
python -m sales_pipeline --offline
python -m pytest tests/test_pipeline.py -k identical_reruns -v
python -m pytest tests/test_pipeline.py -k correction_replaces -v
python -m pytest tests/test_pipeline.py -k bad_data_fails -v
```

The bad-data tests pass because the deliberately bad inputs raise errors and leave the previous publication selected. They do not change the real downloaded data.

## 7. Read-only dashboard

`dashboard.py` resolves a successful generation, verifies the analytical CSV against its run report and reads aggregate output. Without a local publication, it labels and displays the checked-in submission snapshot.

Filters select year, municipality and a display sample threshold. The trend excludes the partial current year; the source-coverage tab retains it with an explicit caveat. No dashboard operation changes raw data or reruns ingestion.

## Boundaries to explain candidly

The candidate identity is not a publisher-provided transaction ID. Consolidated precedence is a documented choice, not a guarantee of authority. The five unresolved identities remain unresolved. Sale code 0 is a narrow subset, and classification can change. Municipality medians compare transaction groups, not identical properties. Publisher snapshots can change after this submission, so live refreshes can produce new results legitimately.
