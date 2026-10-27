-- The single analytical output: one municipality and sale year per row.
-- All-price medians are explicitly a naive benchmark, not a market valuation.
CREATE TABLE municipality_year AS
WITH metrics AS (
    SELECT
        municipality_code, municipality, sale_year,
        count(*) AS recorded_transfers,
        count(price) AS transfers_with_price,
        count(*) FILTER (WHERE price IS NULL AND resolution <> 'unresolved_conflict') AS missing_price_transfers,
        count(*) FILTER (WHERE price = 0) AS zero_price_transfers,
        count(*) FILTER (WHERE sale_code = '3') AS love_affection_transfers,
        count(*) FILTER (WHERE sale_code = 'H') AS multi_parcel_transfers,
        count(*) FILTER (WHERE resolution = 'unresolved_conflict') AS unresolved_conflicts,
        count(*) FILTER (WHERE identity_quality = 'incomplete_deed_key') AS incomplete_deed_keys,
        count(*) FILTER (WHERE is_eligible_market_sale) AS eligible_market_sales,
        median(price) AS median_recorded_price,
        median(price) FILTER (WHERE is_eligible_market_sale) AS median_market_price,
        min(sale_date) AS first_sale_date,
        max(sale_date) AS last_sale_date
    FROM clean_transfers
    GROUP BY municipality_code, municipality, sale_year
)
SELECT *,
    eligible_market_sales::DOUBLE / recorded_transfers AS eligible_share,
    median_market_price - median_recorded_price AS median_difference,
    (median_market_price / nullif(median_recorded_price, 0) - 1)::DOUBLE AS median_difference_pct,
    eligible_market_sales >= 30 AS meets_sample_threshold,
    sale_year = year((SELECT max(sale_date) FROM clean_transfers)) AS latest_observed_year
FROM metrics
ORDER BY municipality_code, sale_year;
