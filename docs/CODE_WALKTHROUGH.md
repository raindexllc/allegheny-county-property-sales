# Walk through one record, then the pipeline

## Concrete example from the source

A Clairton transfer record for parcel **0879N00036000200**, sale date 2020-12-16, deed book 18292/page 134 and code H enters unchanged raw storage. The annual resource is `4531f69a-b368-4e46-8b93-a308faaab46b`; its resource-local record ID in this snapshot is `21361340`. The source has 173 distinct parcel IDs sharing that deed reference/date and a $185,000 price in the reviewed snapshot. Keeping the parcel identifier as text preserves its leading zero.

Inspect both source versions in DuckDB:

```sql
SELECT source_kind, source_record_id, parcel_id, source_municipality_code,
       municipality, sale_date, price, sale_code
FROM normalized
WHERE parcel_id = '0879N00036000200' AND sale_date = DATE '2020-12-16'
ORDER BY source_kind;
```

1. `ingest.py` downloads each CSV; SHA256 identifies its exact bytes. Nothing is edited in raw storage. The manifest links the resource ID, URL and file hash.
2. `model.load_sources()` checks CSV schema/record widths and lands the parsed record with source resource, row ID and row position. Overlap between consolidated and annual files remains visible here.
3. `01_normalize.sql` trims fields, parses ISO dates/money and joins the checked municipal and sale-code references. Clairton's ward code maps to project municipality 200. Parcel and deed identifiers remain text.
4. The **transfer identity** includes parcel/date/deed/instrument. Thus 173 parcels retain 173 identities. The **row fingerprint** compares source versions. An additional analytical fingerprint compares price, municipality and classification, so an address variation does not create a price dispute.
5. `02_reconcile.sql` checks agreement. No source family wins disputed analytical values. Missing deed references and same-deed/different-date candidates remain flagged and are excluded from price analysis, not silently merged. A usable H record is a multi-parcel transfer, not a standard-valid sale.
6. `03_municipality_year.sql` counts the record once in Clairton 2020. Its usable price enters the explicitly naive all-transfer median, but not the standard-valid median. No parcel-price total is presented. The six category counts add up to the recorded identity count.
7. `04_quality_checks.sql` verifies source/reference/price/date and reconciliation contracts. A nonzero violation prevents publication and saves bounded examples.
8. `storage.py` selects a finished generation only after its artifacts verify. Streamlit reads that generation and displays the two medians, category composition and the repeated-deed example.

The example explains the multi-parcel price warning; it does not prove that this one deed causally explains the entire median difference.

## Entry points

- `python -m sales_pipeline`: lock, discover, download, model, validate, publish.
- `python -m sales_pipeline --offline`: verify and rebuild the saved raw snapshot without networking.
- `python -m sales_pipeline --manifest PATH`: reproduce a selected raw snapshot with current, recorded transformations.
- `python -m sales_pipeline.snapshot`: stage and verify the small submission bundle, then replace it with rollback protection.
- `python -m streamlit run dashboard.py`: read-only local exploration; `results/` is the labeled fallback when no local publication exists.

All use `SALES_DATA_DIR` when configured. One writer at a time; an unchanged source/transformation signature reuses a verified publication. Keep the last two successful databases and retain raw snapshots for earlier rebuilds. The raw-snapshot pointer and successful-model pointer are different: new raw inputs can fail checks while the old analytical output remains selected.

## Useful demonstrations

```bash
python -m sales_pipeline --offline
python -m pytest tests/test_pipeline.py -k identical_rerun -v
python -m pytest tests/test_pipeline.py -k source_correction -v
python -m pytest tests/test_pipeline.py -k neither_source -v
python -m pytest tests/test_pipeline.py -k bad_data_blocks -v
```

The bad-data tests pass because the input is rejected, evidence is saved and the last good pointer is preserved. They never edit the real raw snapshot.

## Explain these limits candidly

The composite identity is a candidate key, not a publisher-guaranteed event ID. Same-deed/date anomalies may be legitimate or corrected records; the pipeline flags uncertainty without deciding which event happened. Reference CSVs are observed baselines with explicit project choices. Code 0 describes a selected publisher-classified subset, not every economically valid sale. Missing source records have no established cause. Metadata stability during download is not a transactional guarantee. A local raw snapshot plus transformation hashes is needed to reproduce historical output exactly.
