-- One required analytical output: municipality and sale year.
-- The six composition categories are disjoint and sum to recorded_transfers.
CREATE TABLE municipality_year AS
WITH metrics AS (
    SELECT municipality_code, municipality, sale_year,
        count(*) AS recorded_transfers,
        count(*) FILTER (WHERE price_usable) AS priced_transfers,
        count(*) FILTER (WHERE is_standard_valid_sale) AS standard_valid_sales,
        count(*) FILTER (WHERE transfer_category = 'Family transfers') AS family_transfers,
        count(*) FILTER (WHERE transfer_category = 'Multi-parcel transfers') AS multi_parcel_transfers,
        count(*) FILTER (WHERE transfer_category = 'Other transfers') AS other_transfers,
        count(*) FILTER (WHERE transfer_category = 'Missing price') AS missing_price_transfers,
        count(*) FILTER (WHERE transfer_category = 'Identity needs review') AS identity_review_transfers,
        count(*) FILTER (WHERE price_usable AND price = 0) AS zero_price_transfers,
        count(*) FILTER (WHERE resolution = 'conflicting_values') AS conflicting_values,
        count(*) FILTER (WHERE potential_date_conflict) AS potential_date_conflicts,
        count(*) FILTER (WHERE incomplete_deed_key) AS incomplete_deed_keys,
        median(price) FILTER (WHERE price_usable) AS median_all_transfer_price,
        median(price) FILTER (WHERE is_standard_valid_sale) AS median_standard_valid_price,
        median(price) FILTER (WHERE transfer_category = 'Family transfers') AS median_family_price,
        median(price) FILTER (WHERE transfer_category = 'Multi-parcel transfers') AS median_multi_parcel_price,
        median(price) FILTER (WHERE transfer_category = 'Other transfers') AS median_other_price,
        min(sale_date) AS first_sale_date, max(sale_date) AS last_sale_date
    FROM clean_transfers GROUP BY municipality_code, municipality, sale_year
)
SELECT *, standard_valid_sales::DOUBLE / recorded_transfers AS standard_valid_share,
    median_standard_valid_price - median_all_transfer_price AS median_gap_dollars,
    (median_standard_valid_price / nullif(median_all_transfer_price, 0) - 1)::DOUBLE AS median_gap_pct,
    sale_year >= year((SELECT snapshot_date FROM run_context)) AS is_partial_year
FROM metrics ORDER BY municipality_code, sale_year;
