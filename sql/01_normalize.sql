-- Keep identifiers as text. Parse money only after preserving the original input.
-- The reference crosswalk contains all source geographies, including pass-throughs.
CREATE TABLE normalized AS
WITH typed AS (
    SELECT source_id, source_kind, source_year, source_row, _id AS source_record_id,
        nullif(trim(PARID), '') AS parcel_id,
        nullif(trim(FULL_ADDRESS), '') AS full_address,
        nullif(trim(PROPERTYHOUSENUM), '') AS house_number,
        nullif(trim(PROPERTYFRACTION), '') AS house_fraction,
        nullif(trim(PROPERTYADDRESSDIR), '') AS street_direction,
        nullif(trim(PROPERTYADDRESSSTREET), '') AS street_name,
        nullif(trim(PROPERTYADDRESSSUF), '') AS street_suffix,
        nullif(trim(PROPERTYADDRESSUNITDESC), '') AS unit_description,
        nullif(trim(PROPERTYUNITNO), '') AS unit_number,
        nullif(trim(PROPERTYCITY), '') AS postal_city,
        nullif(trim(PROPERTYSTATE), '') AS state,
        nullif(trim(PROPERTYZIP), '') AS postal_code,
        nullif(trim(SCHOOLCODE), '') AS school_code,
        nullif(trim(SCHOOLDESC), '') AS school_name,
        nullif(trim(MUNICODE), '') AS source_municipality_code,
        nullif(trim(MUNIDESC), '') AS source_municipality_name,
        try_cast(nullif(trim(RECORDDATE), '') AS DATE) AS record_date,
        try_cast(nullif(trim(SALEDATE), '') AS DATE) AS sale_date,
        try_cast(nullif(trim(PRICE), '') AS DECIMAL(20, 2)) AS price,
        nullif(trim(DEEDBOOK), '') AS deed_book,
        nullif(trim(DEEDPAGE), '') AS deed_page,
        nullif(trim(SALECODE), '') AS sale_code,
        nullif(trim(SALEDESC), '') AS sale_description,
        nullif(trim(INSTRTYP), '') AS instrument_type,
        nullif(trim(INSTRTYPDESC), '') AS instrument_description
    FROM source_rows
), mapped AS (
    SELECT t.*, m.municipality_code::INTEGER AS municipality_code, m.municipality,
        d.analysis_group, coalesce(d.standard_valid::BOOLEAN, false) AS standard_valid_code
    FROM typed t
    LEFT JOIN municipalities m ON t.source_municipality_code = m.source_code
    LEFT JOIN sale_codes d ON t.sale_code = d.sale_code
)
SELECT *,
    -- A candidate identity, not a publisher-guaranteed transaction ID.
    sha256(to_json(struct_pack(parcel := parcel_id, sold := sale_date,
        book := deed_book, page := deed_page, instrument := instrument_type))) AS transfer_id,
    sha256(to_json(struct_pack(parcel := parcel_id, address := full_address,
        house := house_number, fraction := house_fraction, direction := street_direction,
        street := street_name, suffix := street_suffix, unit_desc := unit_description,
        unit := unit_number, postal_city := postal_city, state := state, zip := postal_code,
        school := school_code, school_name := school_name,
        muni := source_municipality_code, muni_name := source_municipality_name,
        recorded := record_date, sold := sale_date, price := price,
        book := deed_book, page := deed_page, code := sale_code,
        description := sale_description, instrument := instrument_type,
        instrument_description := instrument_description))) AS row_fingerprint,
    -- Descriptive differences do not dispute a shared price/classification.
    sha256(to_json(struct_pack(muni := municipality_code, price := price,
        code := sale_code, description := sale_description))) AS analytical_fingerprint
FROM mapped;
