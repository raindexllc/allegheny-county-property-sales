CREATE TABLE transfer_groups AS
SELECT transfer_id, count(*) AS source_row_count,
    count(DISTINCT row_fingerprint) AS distinct_versions,
    count(DISTINCT analytical_fingerprint) AS analytical_versions,
    bool_or(source_kind = 'consolidated') AS in_consolidated,
    bool_or(source_kind = 'annual') AS in_annual
FROM normalized GROUP BY transfer_id;

-- Flag possible date corrections across different candidate identities.
-- Do not assume these are duplicates, and do not silently merge them.
CREATE TABLE potential_date_conflicts AS
SELECT parcel_id, deed_book, deed_page, instrument_type
FROM normalized
WHERE deed_book IS NOT NULL AND deed_page IS NOT NULL AND instrument_type IS NOT NULL
GROUP BY parcel_id, deed_book, deed_page, instrument_type
HAVING count(DISTINCT sale_date) > 1;

CREATE TABLE clean_transfers AS
WITH representative AS (
    SELECT n.*, g.* EXCLUDE (transfer_id),
        CASE WHEN analytical_versions > 1 THEN 'conflicting_values'
             WHEN distinct_versions > 1 THEN 'descriptive_variation'
             ELSE 'agreed_values' END AS resolution,
        n.deed_book IS NULL OR n.deed_page IS NULL OR n.instrument_type IS NULL AS incomplete_deed_key,
        p.parcel_id IS NOT NULL AS potential_date_conflict
    FROM normalized n JOIN transfer_groups g USING (transfer_id)
    LEFT JOIN potential_date_conflicts p USING (parcel_id, deed_book, deed_page, instrument_type)
    -- No source family wins a factual dispute. This order only chooses a traceable
    -- representative for agreed values; conflicting analytical fields are masked.
    QUALIFY row_number() OVER (PARTITION BY transfer_id ORDER BY source_id, row_fingerprint, source_row) = 1
), resolved AS (
    SELECT transfer_id, parcel_id, sale_date, year(sale_date)::INTEGER AS sale_year,
        deed_book, deed_page, instrument_type, municipality_code, municipality,
        source_id AS representative_source_id, source_record_id AS representative_record_id,
        source_row_count, distinct_versions, analytical_versions,
        in_consolidated, in_annual, resolution, incomplete_deed_key, potential_date_conflict,
        CASE WHEN analytical_versions = 1 THEN price END AS price,
        CASE WHEN analytical_versions = 1 THEN sale_code END AS sale_code,
        CASE WHEN analytical_versions = 1 THEN sale_description END AS sale_description,
        CASE WHEN analytical_versions = 1 THEN record_date END AS record_date,
        CASE WHEN analytical_versions = 1 THEN analysis_group END AS analysis_group,
        analytical_versions = 1 AND NOT incomplete_deed_key AND NOT potential_date_conflict AS identity_usable,
        analytical_versions = 1 AND standard_valid_code AS standard_valid_code
    FROM representative
), classified AS (
    SELECT *, identity_usable AND price IS NOT NULL AS price_usable,
        identity_usable AND standard_valid_code AND coalesce(price > 0, false) AS is_standard_valid_sale,
        CASE WHEN resolution = 'conflicting_values' THEN 'conflicting_analytical_values'
             WHEN incomplete_deed_key THEN 'incomplete_deed_key'
             WHEN potential_date_conflict THEN 'potential_date_conflict'
             WHEN price IS NULL THEN 'missing_price'
             WHEN NOT standard_valid_code THEN 'other_classification'
             WHEN price <= 0 THEN 'nonpositive_price'
             ELSE 'standard_valid_sale' END AS eligibility_reason
    FROM resolved
)
SELECT *, CASE WHEN NOT identity_usable THEN 'Identity needs review'
               WHEN price IS NULL THEN 'Missing price'
               WHEN is_standard_valid_sale THEN 'Standard-valid sales'
               WHEN analysis_group IN ('Family transfers', 'Multi-parcel transfers') THEN analysis_group
               ELSE 'Other transfers' END AS transfer_category
FROM classified;

CREATE VIEW review_records AS
SELECT n.*, c.resolution, c.incomplete_deed_key, c.potential_date_conflict, c.eligibility_reason
FROM normalized n JOIN clean_transfers c USING (transfer_id)
WHERE NOT c.identity_usable OR c.resolution = 'descriptive_variation';

CREATE TABLE source_reconciliation AS
SELECT sale_year, count(*) AS reconciled_transfers,
    count(*) FILTER (WHERE in_consolidated AND in_annual) AS in_both,
    count(*) FILTER (WHERE in_annual AND NOT in_consolidated) AS annual_only,
    count(*) FILTER (WHERE in_consolidated AND NOT in_annual) AS consolidated_only,
    count(*) FILTER (WHERE resolution = 'conflicting_values') AS conflicting_values,
    count(*) FILTER (WHERE potential_date_conflict) AS potential_date_conflicts,
    count(*) FILTER (WHERE incomplete_deed_key) AS incomplete_deed_keys
FROM clean_transfers GROUP BY sale_year ORDER BY sale_year;
