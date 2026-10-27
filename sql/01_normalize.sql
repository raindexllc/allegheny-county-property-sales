-- CKAN _id is local to a resource and changes on reload; it is lineage, not identity.
-- Source dates are ISO YYYY-MM-DD, despite the dictionary's dd/mm/yyyy description.
CREATE TABLE normalized AS
WITH typed AS (
    SELECT
        source_id, source_kind, source_year, source_row,
        _id AS source_record_id,
        nullif(trim(PARID), '') AS parcel_id,
        nullif(trim(FULL_ADDRESS), '') AS full_address,
        try_cast(nullif(trim(PROPERTYHOUSENUM), '') AS DECIMAL(20, 2)) AS house_number,
        nullif(trim(PROPERTYFRACTION), '') AS house_fraction,
        nullif(trim(PROPERTYADDRESSDIR), '') AS street_direction,
        nullif(trim(PROPERTYADDRESSSTREET), '') AS street_name,
        nullif(trim(PROPERTYADDRESSSUF), '') AS street_suffix,
        nullif(trim(PROPERTYADDRESSUNITDESC), '') AS unit_description,
        nullif(trim(PROPERTYUNITNO), '') AS unit_number,
        nullif(trim(PROPERTYCITY), '') AS postal_city,
        nullif(trim(PROPERTYSTATE), '') AS state,
        try_cast(nullif(trim(PROPERTYZIP), '') AS INTEGER) AS postal_code,
        nullif(trim(SCHOOLCODE), '') AS school_code,
        nullif(trim(SCHOOLDESC), '') AS school_name,
        try_cast(nullif(trim(MUNICODE), '') AS INTEGER) AS source_municipality_code,
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
), identified AS (
    SELECT *,
        -- A candidate parcel-transfer identity, tested for collisions on each run.
        -- JSON struct encoding distinguishes nulls and embedded delimiters.
        sha256(to_json(struct_pack(
            parcel := parcel_id, sale_date := sale_date,
            deed_book := deed_book, deed_page := deed_page, instrument := instrument_type
        ))) AS transfer_id,
        sha256(to_json(struct_pack(
            parcel := parcel_id, address := full_address, house := house_number,
            fraction := house_fraction, direction := street_direction, street := street_name,
            suffix := street_suffix, unit_desc := unit_description, unit := unit_number,
            postal_city := postal_city, state := state, zip := postal_code,
            school := school_code, school_name := school_name,
            muni := source_municipality_code, muni_name := source_municipality_name,
            recorded := record_date, sold := sale_date, price := price,
            book := deed_book, page := deed_page, code := sale_code,
            description := sale_description, instrument := instrument_type,
            instrument_description := instrument_description
        ))) AS row_fingerprint,
        CASE
            WHEN source_municipality_code BETWEEN 101 AND 132 THEN 100
            WHEN source_municipality_code BETWEEN 201 AND 202 THEN 200
            WHEN source_municipality_code BETWEEN 301 AND 303 THEN 300
            WHEN source_municipality_code BETWEEN 401 AND 412 THEN 400
            ELSE source_municipality_code
        END AS municipality_code,
        CASE
            WHEN source_municipality_code BETWEEN 101 AND 132 THEN 'Pittsburgh'
            WHEN source_municipality_code BETWEEN 201 AND 202 THEN 'Clairton'
            WHEN source_municipality_code BETWEEN 301 AND 303 THEN 'Duquesne'
            WHEN source_municipality_code BETWEEN 401 AND 412 THEN 'McKeesport'
            ELSE source_municipality_name
        END AS municipality
    FROM typed
)
SELECT * FROM identified;
