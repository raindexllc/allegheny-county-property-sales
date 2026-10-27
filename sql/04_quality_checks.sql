-- Keep bounded examples of failures, not only a pass/fail total.
CREATE TABLE quality_violations AS
SELECT 'required_identifiers' AS check_name, source_id, _id AS source_record_id,
    concat('parcel=', PARID, '; sale=', SALEDATE) AS detail
FROM source_rows
WHERE nullif(trim(PARID), '') IS NULL OR length(trim(PARID)) <> 16
   OR nullif(trim(SALEDATE), '') IS NULL
UNION ALL
SELECT 'date_parsing', source_id, _id, concat('sale=', SALEDATE, '; recorded=', RECORDDATE)
FROM source_rows WHERE (nullif(trim(SALEDATE), '') IS NOT NULL AND try_cast(SALEDATE AS DATE) IS NULL)
   OR (nullif(trim(RECORDDATE), '') IS NOT NULL AND try_cast(RECORDDATE AS DATE) IS NULL)
UNION ALL
SELECT 'price_format_and_precision', source_id, _id, concat('price=', PRICE)
FROM source_rows WHERE nullif(trim(PRICE), '') IS NOT NULL
  AND (NOT regexp_full_match(trim(PRICE), '[-+]?[0-9]+(\.[0-9]{1,2}0*)?')
       OR try_cast(PRICE AS DECIMAL(20,2)) IS NULL)
UNION ALL
SELECT 'nonnegative_prices', source_id, source_record_id, concat('price=', price)
FROM normalized WHERE price < 0
UNION ALL
SELECT 'municipality_reference', s.source_id, s._id, concat('code=', s.MUNICODE, '; name=', s.MUNIDESC)
FROM source_rows s LEFT JOIN municipalities m ON trim(s.MUNICODE) = m.source_code
WHERE m.source_code IS NULL OR trim(s.MUNIDESC) IS DISTINCT FROM m.source_name
UNION ALL
SELECT 'observed_sale_code_pairs', n.source_id, n.source_record_id,
    concat('code=', n.sale_code, '; description=', n.sale_description)
FROM normalized n LEFT JOIN sale_codes d USING (sale_code)
WHERE d.sale_code IS NULL OR n.sale_description IS DISTINCT FROM d.sale_description
UNION ALL
SELECT 'annual_sale_year', source_id, source_record_id,
    concat('file year=', source_year, '; sale=', sale_date)
FROM normalized WHERE source_kind = 'annual' AND source_year <> year(sale_date)
UNION ALL
SELECT 'sale_date_range', source_id, source_record_id, concat('sale=', sale_date)
FROM normalized WHERE sale_date < DATE '2012-01-01'
   OR sale_date > (SELECT snapshot_date FROM run_context);

CREATE TABLE quality_checks AS
SELECT names.check_name, count(v.check_name) AS violations
FROM (VALUES ('required_identifiers'), ('date_parsing'), ('price_format_and_precision'),
    ('nonnegative_prices'), ('municipality_reference'), ('observed_sale_code_pairs'),
    ('annual_sale_year'), ('sale_date_range')) names(check_name)
LEFT JOIN quality_violations v USING (check_name) GROUP BY names.check_name
UNION ALL
SELECT 'reference_keys_unique', count(*) FROM (
    SELECT source_code FROM municipalities GROUP BY source_code HAVING count(*) <> 1
    UNION ALL SELECT sale_code FROM sale_codes GROUP BY sale_code HAVING count(*) <> 1
)
UNION ALL
SELECT 'source_rows_preserved', abs((SELECT count(*) FROM source_rows) - (SELECT count(*) FROM normalized))
UNION ALL
SELECT 'crosswalk_rollup_labels', count(*) FROM municipalities
WHERE CASE WHEN regexp_matches(upper(source_name), '^[0-9]+(ST|ND|RD|TH) WARD\s*-\s*')
    THEN upper(municipality) <> regexp_extract(upper(source_name), 'WARD\s*-\s*(.+)$', 1)
    ELSE source_name <> municipality OR source_code <> municipality_code END
UNION ALL
SELECT 'canonical_municipality_has_one_name', count(*) FROM (
    SELECT municipality_code FROM municipalities GROUP BY municipality_code
    HAVING count(DISTINCT municipality) <> 1
)
UNION ALL
SELECT 'identity_has_one_municipality', count(*) FROM (
    SELECT transfer_id FROM normalized GROUP BY transfer_id
    HAVING count(DISTINCT municipality_code) <> 1 OR count(DISTINCT municipality) <> 1
)
UNION ALL
SELECT 'clean_identity_unique', count(*) FROM (
    SELECT transfer_id FROM clean_transfers GROUP BY transfer_id HAVING count(*) <> 1
)
UNION ALL
SELECT 'every_source_identity_represented', abs(
    (SELECT count(DISTINCT transfer_id) FROM normalized) - (SELECT count(*) FROM clean_transfers))
UNION ALL
SELECT 'uncertain_identity_never_priced', count(*) FROM clean_transfers
WHERE NOT identity_usable AND (price_usable OR is_standard_valid_sale)
UNION ALL
SELECT 'conflicting_values_masked', count(*) FROM clean_transfers
WHERE resolution = 'conflicting_values' AND (price IS NOT NULL OR sale_code IS NOT NULL)
UNION ALL
SELECT 'standard_valid_definition', count(*) FROM clean_transfers
WHERE is_standard_valid_sale AND (sale_code IS DISTINCT FROM '0'
    OR sale_description IS DISTINCT FROM 'VALID SALE' OR price IS NULL OR price <= 0)
UNION ALL
SELECT 'multi_parcel_excluded', count(*) FROM clean_transfers
WHERE sale_code = 'H' AND is_standard_valid_sale
UNION ALL
SELECT 'output_grain_unique', count(*) FROM (
    SELECT municipality_code, sale_year FROM municipality_year GROUP BY municipality_code, sale_year HAVING count(*) <> 1
)
UNION ALL
SELECT 'composition_adds_up', count(*) FROM municipality_year
WHERE recorded_transfers <> standard_valid_sales + family_transfers + multi_parcel_transfers
    + other_transfers + missing_price_transfers + identity_review_transfers
UNION ALL
SELECT 'output_count_reconciliation', abs(
    (SELECT coalesce(sum(recorded_transfers),0) FROM municipality_year) - (SELECT count(*) FROM clean_transfers))
UNION ALL
SELECT 'output_standard_valid_reconciliation', abs(
    (SELECT coalesce(sum(standard_valid_sales),0) FROM municipality_year)
    - (SELECT count(*) FROM clean_transfers WHERE is_standard_valid_sale))
UNION ALL
SELECT 'output_nonempty', CASE WHEN count(*) > 0 THEN 0 ELSE 1 END FROM municipality_year;
