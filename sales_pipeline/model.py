"""Build in a private staging directory; publish only a validated generation."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import duckdb

from sales_pipeline.ingest import verify_snapshot

ROOT = Path(__file__).resolve().parents[1]
BUSINESS_COLUMNS = [
    "PARID", "FULL_ADDRESS", "PROPERTYHOUSENUM", "PROPERTYFRACTION",
    "PROPERTYADDRESSDIR", "PROPERTYADDRESSSTREET", "PROPERTYADDRESSSUF",
    "PROPERTYADDRESSUNITDESC", "PROPERTYUNITNO", "PROPERTYCITY", "PROPERTYSTATE",
    "PROPERTYZIP", "SCHOOLCODE", "SCHOOLDESC", "MUNICODE", "MUNIDESC",
    "RECORDDATE", "SALEDATE", "PRICE", "DEEDBOOK", "DEEDPAGE", "SALECODE",
    "SALEDESC", "INSTRTYP", "INSTRTYPDESC",
]


class QualityError(ValueError):
    """A source or modeled invariant failed; retain the last good publication."""


def validate_csv(path: Path) -> int:
    """Check every record's width before DuckDB reads CKAN's mixed-newline CSV."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.reader(handle, strict=True)
        header = next(rows, [])
        if len(header) != len(set(header)) or set(header) != {"_id", *BUSINESS_COLUMNS}:
            raise QualityError(f"Unexpected CSV schema in {path.name}: {header}")
        count = 0
        for line_number, row in enumerate(rows, start=2):
            if len(row) != len(header):
                raise QualityError(f"CSV row width mismatch in {path.name}, record {line_number}")
            count += 1
    if not count:
        raise QualityError(f"Empty resource: {path.name}")
    return count


def load_sources(connection: duckdb.DuckDBPyConnection, manifest: dict, data_dir: Path) -> list[dict]:
    inventory = []
    for index, resource in enumerate(manifest["resources"]):
        path = data_dir / resource["path"]
        expected_count = validate_csv(path)
        # CKAN dumps use CRLF for the header and LF for records. strict_mode=False
        # accepts this dialect; ignore_errors remains False. Width and count checks
        # ensure no source record disappears because of permissive dialect handling.
        connection.read_csv(
            str(path), header=True, all_varchar=True, delimiter=",",
            quotechar='"', escapechar='"', strict_mode=False, ignore_errors=False,
        ).create_view("incoming")
        query = """
            SELECT *, ?::VARCHAR AS source_id, ?::VARCHAR AS source_kind,
                ?::INTEGER AS source_year, row_number() OVER () AS source_row
            FROM incoming
        """
        statement = "CREATE TABLE source_rows AS " if index == 0 else "INSERT INTO source_rows BY NAME "
        connection.execute(statement + query, [resource["id"], resource["kind"], resource["year"]])
        observed_count = connection.execute(
            "SELECT count(*) FROM source_rows WHERE source_id = ?", [resource["id"]]
        ).fetchone()[0]
        if observed_count != expected_count:
            raise QualityError(f"CSV records lost in {resource['name']}: {observed_count} != {expected_count}")
        inventory.append({**resource, "row_count": observed_count})
    connection.execute("DROP VIEW incoming")
    return inventory


def run_sql(connection: duckdb.DuckDBPyConnection, filename: str) -> None:
    connection.execute((ROOT / "sql" / filename).read_text())


def build_database(connection: duckdb.DuckDBPyConnection, manifest: dict, data_dir: Path) -> tuple[list, list]:
    inventory = load_sources(connection, manifest, data_dir)
    snapshot_date = datetime.fromisoformat(manifest["fetched_at"]).date()
    connection.execute("CREATE TABLE run_context (snapshot_date DATE)")
    connection.execute("INSERT INTO run_context VALUES (?)", [snapshot_date])
    connection.read_csv(str(ROOT / "config" / "sale_codes.csv"), all_varchar=True).create("sale_codes")
    for filename in ("01_normalize.sql", "02_reconcile.sql", "03_municipality_year.sql", "04_quality_checks.sql"):
        run_sql(connection, filename)
    checks = [dict(zip(("check_name", "violations"), row)) for row in connection.execute(
        "SELECT check_name, violations FROM quality_checks ORDER BY check_name"
    ).fetchall()]
    failures = [check for check in checks if check["violations"]]
    if failures:
        raise QualityError("Data quality checks failed: " + json.dumps(failures))
    return inventory, checks


def query_dicts(connection: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    cursor = connection.execute(sql)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def export_table(connection: duckdb.DuckDBPyConnection, query: str, path: Path) -> None:
    # Relation API handles the destination path without SQL string interpolation.
    connection.sql(query).write_csv(str(path), header=True)


def build_model(manifest_path: Path, data_dir: Path) -> Path:
    manifest = verify_snapshot(manifest_path, data_dir)
    published = data_dir / "published"
    published.mkdir(parents=True, exist_ok=True)
    generation_id = uuid.uuid4().hex
    staging = published / f".building-{generation_id}"
    staging.mkdir()
    try:
        with duckdb.connect(str(staging / "sales.duckdb")) as connection:
            inventory, checks = build_database(connection, manifest, data_dir)
            export_table(connection, "SELECT * FROM municipality_year ORDER BY municipality_code, sale_year", staging / "municipality_year.csv")
            export_table(connection, "SELECT * FROM source_reconciliation ORDER BY sale_year", staging / "source_reconciliation.csv")
            export_table(connection, "SELECT * FROM quality_checks ORDER BY check_name", staging / "quality_checks.csv")
            export_table(connection, """
                SELECT sale_code, sale_description, count(*) AS transfers,
                    count(*) FILTER (WHERE is_eligible_market_sale) AS eligible_market_sales
                FROM clean_transfers GROUP BY sale_code, sale_description ORDER BY transfers DESC
            """, staging / "sale_code_profile.csv")
            totals = query_dicts(connection, """
                SELECT count(*) AS transfers, count(DISTINCT municipality_code) AS municipalities,
                    count(*) FILTER (WHERE is_eligible_market_sale) AS eligible_market_sales,
                    count(*) FILTER (WHERE resolution = 'unresolved_conflict') AS unresolved_conflicts,
                    count(*) FILTER (WHERE identity_quality = 'incomplete_deed_key') AS incomplete_deed_keys,
                    count(*) FILTER (WHERE record_date < sale_date) AS recording_before_sale,
                    min(sale_date) AS first_sale_date, max(sale_date) AS last_sale_date
                FROM clean_transfers
            """)[0]
            reconciliation = query_dicts(connection, "SELECT * FROM source_reconciliation ORDER BY sale_year")
        output_hash = hashlib.sha256((staging / "municipality_year.csv").read_bytes()).hexdigest()
        report = {
            "snapshot_fetched_at": manifest["fetched_at"], "output_sha256": output_hash,
            "totals": totals, "checks": checks, "resources": inventory,
            "reconciliation": reconciliation,
            "definition": "Eligible: SALECODE='0', SALEDESC='VALID SALE', positive price, resolved identity.",
            "minimum_market_sample": 30,
        }
        (staging / "run_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
        shutil.copyfile(manifest_path, staging / "manifest.json")
        generation = published / generation_id
        staging.rename(generation)
        # One atomic pointer switches the database, CSV and reports together.
        # A dashboard resolves this once per rerun and sees a consistent generation.
        pointer = published / "current.json"
        temporary = pointer.with_suffix(".tmp")
        temporary.write_text(json.dumps({"generation": generation_id}) + "\n")
        temporary.replace(pointer)
        print(f"Published {totals['transfers']:,} transfers; output SHA256 {output_hash}")
        return generation
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def current_generation(data_dir: Path) -> Path:
    pointer = data_dir / "published" / "current.json"
    generation_id = json.loads(pointer.read_text())["generation"]
    if not isinstance(generation_id, str) or len(generation_id) != 32 or any(
        character not in "0123456789abcdef" for character in generation_id
    ):
        raise ValueError("Invalid publication pointer")
    return pointer.parent / generation_id
