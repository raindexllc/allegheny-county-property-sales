CREATE TABLE transfer_groups AS
SELECT
    transfer_id,
    count(*) AS source_row_count,
    count(DISTINCT row_fingerprint) AS distinct_versions,
    count(DISTINCT row_fingerprint) FILTER (WHERE source_kind = 'consolidated') AS consolidated_versions,
    bool_or(source_kind = 'consolidated') AS in_consolidated,
    bool_or(source_kind = 'annual') AS in_annual
FROM normalized
GROUP BY transfer_id;

CREATE TABLE clean_transfers AS
WITH chosen AS (
    SELECT n.*, g.* EXCLUDE (transfer_id),
        CASE
            WHEN consolidated_versions = 1 AND distinct_versions > 1 THEN 'consolidated_preferred'
            WHEN distinct_versions = 1 THEN 'uncontested'
            ELSE 'unresolved_conflict'
        END AS resolution
    FROM normalized n
    JOIN transfer_groups g USING (transfer_id)
    -- Pick the consolidated version when available. A fingerprint is only a
    -- deterministic tie-breaker; unresolved values are masked below, never trusted.
    QUALIFY row_number() OVER (
        PARTITION BY transfer_id
        ORDER BY (source_kind = 'consolidated') DESC, row_fingerprint, source_id, source_row
    ) = 1
), masked AS (
    SELECT
        transfer_id, parcel_id, sale_date, year(sale_date)::INTEGER AS sale_year,
        deed_book, deed_page, instrument_type,
        municipality_code, municipality,
        CASE WHEN resolution <> 'unresolved_conflict' THEN full_address END AS full_address,
        CASE WHEN resolution <> 'unresolved_conflict' THEN record_date END AS record_date,
        CASE WHEN resolution <> 'unresolved_conflict' THEN price END AS price,
        CASE WHEN resolution <> 'unresolved_conflict' THEN sale_code END AS sale_code,
        CASE WHEN resolution <> 'unresolved_conflict' THEN sale_description END AS sale_description,
        CASE WHEN resolution <> 'unresolved_conflict' THEN source_id END AS selected_source_id,
        CASE WHEN resolution <> 'unresolved_conflict' THEN source_record_id END AS selected_source_record_id,
        resolution, source_row_count, distinct_versions, in_consolidated, in_annual,
        CASE WHEN deed_book IS NULL OR deed_page IS NULL OR instrument_type IS NULL
             THEN 'incomplete_deed_key' ELSE 'complete_deed_key' END AS identity_quality
    FROM chosen
)
SELECT *,
    CASE
        WHEN resolution = 'unresolved_conflict' THEN 'unresolved_conflict'
        WHEN sale_code <> '0' OR sale_code IS NULL THEN 'not_standard_valid_sale'
        WHEN price IS NULL THEN 'missing_price'
        WHEN price <= 0 THEN 'nonpositive_price'
        ELSE 'eligible_market_sale'
    END AS eligibility_reason,
    coalesce(resolution <> 'unresolved_conflict' AND sale_code = '0' AND price > 0, false)
        AS is_eligible_market_sale
FROM masked;

-- Preserve every competing source record, including all unresolved variants.
CREATE VIEW conflict_records AS
SELECT n.*, c.resolution
FROM normalized n
JOIN clean_transfers c USING (transfer_id)
WHERE c.distinct_versions > 1;

CREATE TABLE source_reconciliation AS
SELECT
    sale_year,
    count(*) AS reconciled_transfers,
    count(*) FILTER (WHERE in_consolidated AND in_annual) AS in_both,
    count(*) FILTER (WHERE in_annual AND NOT in_consolidated) AS annual_only,
    count(*) FILTER (WHERE in_consolidated AND NOT in_annual) AS consolidated_only,
    count(*) FILTER (WHERE distinct_versions > 1) AS competing_versions,
    count(*) FILTER (WHERE resolution = 'unresolved_conflict') AS unresolved_conflicts
FROM clean_transfers
GROUP BY sale_year
ORDER BY sale_year;
