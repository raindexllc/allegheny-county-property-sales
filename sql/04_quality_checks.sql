-- Each query returns a count of violations. Any nonzero count blocks publication.
CREATE TABLE quality_checks AS
SELECT 'required_identifiers' AS check_name, count(*) AS violations
FROM normalized
WHERE parcel_id IS NULL OR length(parcel_id) <> 16 OR sale_date IS NULL
   OR municipality_code IS NULL OR municipality IS NULL
UNION ALL
SELECT 'typed_dates_and_price', count(*) FROM source_rows
WHERE (nullif(trim(SALEDATE), '') IS NOT NULL AND try_cast(SALEDATE AS DATE) IS NULL)
   OR (nullif(trim(RECORDDATE), '') IS NOT NULL AND try_cast(RECORDDATE AS DATE) IS NULL)
   OR (nullif(trim(PRICE), '') IS NOT NULL AND try_cast(PRICE AS DECIMAL(20, 2)) IS NULL)
   OR (nullif(trim(MUNICODE), '') IS NOT NULL AND try_cast(MUNICODE AS INTEGER) IS NULL)
UNION ALL
SELECT 'nonnegative_prices', count(*) FROM normalized WHERE price < 0
UNION ALL
SELECT 'sale_date_in_snapshot_range', count(*) FROM normalized
WHERE sale_date < DATE '2012-01-01' OR sale_date > (SELECT snapshot_date FROM run_context)
UNION ALL
-- Discovered by profiling: annual files partition by SALEDATE, not RECORDDATE.
SELECT 'annual_file_matches_sale_year', count(*) FROM normalized
WHERE source_kind = 'annual' AND source_year <> year(sale_date)
UNION ALL
SELECT 'reviewed_sale_code_descriptions', count(*) FROM normalized n
LEFT JOIN sale_codes d ON n.sale_code = d.sale_code
WHERE d.sale_code IS NULL OR n.sale_description IS DISTINCT FROM d.sale_description
UNION ALL
SELECT 'consolidated_identity_unambiguous', count(*) FROM transfer_groups
WHERE consolidated_versions > 1
UNION ALL
SELECT 'identity_has_one_municipality', count(*) FROM (
    SELECT transfer_id FROM normalized GROUP BY transfer_id
    HAVING count(DISTINCT municipality_code) <> 1 OR count(DISTINCT municipality) <> 1
)
UNION ALL
SELECT 'municipality_code_has_one_name', count(*) FROM (
    SELECT municipality_code FROM normalized GROUP BY municipality_code
    HAVING count(DISTINCT municipality) <> 1
)
UNION ALL
-- Discovered by profiling: codes 101-132, 201-202, 301-303 and 401-412 are wards.
SELECT 'ward_labels_match_city_rollup', count(*) FROM normalized
WHERE (source_municipality_code BETWEEN 101 AND 132 AND NOT regexp_matches(upper(source_municipality_name), 'WARD\s*-\s*PITTSBURGH$'))
   OR (source_municipality_code BETWEEN 201 AND 202 AND NOT regexp_matches(upper(source_municipality_name), 'WARD\s*-\s*CLAIRTON$'))
   OR (source_municipality_code BETWEEN 301 AND 303 AND NOT regexp_matches(upper(source_municipality_name), 'WARD\s*-\s*DUQUESNE$'))
   OR (source_municipality_code BETWEEN 401 AND 412 AND NOT regexp_matches(upper(source_municipality_name), 'WARD\s*-\s*MCKEESPORT$'))
UNION ALL
SELECT 'clean_transfer_identity_unique', count(*) FROM (
    SELECT transfer_id FROM clean_transfers GROUP BY transfer_id HAVING count(*) <> 1
)
UNION ALL
SELECT 'every_source_identity_represented', abs(
    (SELECT count(DISTINCT transfer_id) FROM normalized) - (SELECT count(*) FROM clean_transfers)
)
UNION ALL
SELECT 'unresolved_values_never_used', count(*) FROM clean_transfers
WHERE resolution = 'unresolved_conflict'
  AND (price IS NOT NULL OR sale_code IS NOT NULL OR is_eligible_market_sale)
UNION ALL
SELECT 'market_sale_definition', count(*) FROM clean_transfers
WHERE is_eligible_market_sale AND (
    sale_code IS DISTINCT FROM '0' OR sale_description IS DISTINCT FROM 'VALID SALE'
    OR price IS NULL OR price <= 0 OR resolution = 'unresolved_conflict'
)
UNION ALL
-- Dataset warning confirmed in actual rows: H prices may repeat a whole deed price.
SELECT 'multi_parcel_excluded_from_market', count(*) FROM clean_transfers
WHERE sale_code = 'H' AND is_eligible_market_sale
UNION ALL
SELECT 'output_grain_unique', count(*) FROM (
    SELECT municipality_code, sale_year FROM municipality_year
    GROUP BY municipality_code, sale_year HAVING count(*) <> 1
)
UNION ALL
SELECT 'output_count_reconciliation', abs(
    (SELECT coalesce(sum(recorded_transfers), 0) FROM municipality_year)
    - (SELECT count(*) FROM clean_transfers)
)
UNION ALL
SELECT 'output_market_reconciliation', abs(
    (SELECT coalesce(sum(eligible_market_sales), 0) FROM municipality_year)
    - (SELECT count(*) FROM clean_transfers WHERE is_eligible_market_sale)
)
UNION ALL
SELECT 'output_nonempty', CASE WHEN count(*) > 0 THEN 0 ELSE 1 END FROM municipality_year;
