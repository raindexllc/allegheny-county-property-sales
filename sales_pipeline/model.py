"""Build in a private staging directory; publish only a validated generation."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import uuid
import sys
from datetime import datetime
from pathlib import Path

import duckdb

from sales_pipeline.ingest import verify_snapshot
from sales_pipeline.storage import (
    atomic_json,
    current_generation,
    data_directory,
    file_hash,
    run_lock,
    verify_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
BUSINESS_COLUMNS = [
    "PARID",
    "FULL_ADDRESS",
    "PROPERTYHOUSENUM",
    "PROPERTYFRACTION",
    "PROPERTYADDRESSDIR",
    "PROPERTYADDRESSSTREET",
    "PROPERTYADDRESSSUF",
    "PROPERTYADDRESSUNITDESC",
    "PROPERTYUNITNO",
    "PROPERTYCITY",
    "PROPERTYSTATE",
    "PROPERTYZIP",
    "SCHOOLCODE",
    "SCHOOLDESC",
    "MUNICODE",
    "MUNIDESC",
    "RECORDDATE",
    "SALEDATE",
    "PRICE",
    "DEEDBOOK",
    "DEEDPAGE",
    "SALECODE",
    "SALEDESC",
    "INSTRTYP",
    "INSTRTYPDESC",
]


class QualityError(ValueError):
    """A source or modeled invariant failed; retain the last good publication."""

    def __init__(self, message, checks=None, examples=None):
        super().__init__(message)
        self.checks = checks or []
        self.examples = examples or []


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


def load_sources(
    connection: duckdb.DuckDBPyConnection, manifest: dict, data_dir: Path
) -> list[dict]:
    inventory = []
    for index, resource in enumerate(manifest["resources"]):
        path = data_dir / resource["path"]
        expected_count = validate_csv(path)
        # CKAN dumps use CRLF for the header and LF for records. strict_mode=False
        # accepts this dialect; ignore_errors remains False. Width and count checks
        # ensure no source record disappears because of permissive dialect handling.
        connection.read_csv(
            str(path),
            header=True,
            all_varchar=True,
            delimiter=",",
            quotechar='"',
            escapechar='"',
            strict_mode=False,
            ignore_errors=False,
        ).create_view("incoming")
        query = """
            SELECT *, ?::VARCHAR AS source_id, ?::VARCHAR AS source_kind,
                ?::INTEGER AS source_year, row_number() OVER () AS source_row
            FROM incoming
        """
        statement = (
            "CREATE TABLE source_rows AS " if index == 0 else "INSERT INTO source_rows BY NAME "
        )
        connection.execute(statement + query, [resource["id"], resource["kind"], resource["year"]])
        observed_count = connection.execute(
            "SELECT count(*) FROM source_rows WHERE source_id = ?", [resource["id"]]
        ).fetchone()[0]
        if observed_count != expected_count:
            raise QualityError(
                f"CSV records lost in {resource['name']}: {observed_count} != {expected_count}"
            )
        inventory.append({**resource, "row_count": observed_count})
    connection.execute("DROP VIEW incoming")
    return inventory


def run_sql(connection: duckdb.DuckDBPyConnection, filename: str) -> None:
    connection.execute((ROOT / "sql" / filename).read_text())


def build_database(
    connection: duckdb.DuckDBPyConnection, manifest: dict, data_dir: Path
) -> tuple[list, list]:
    inventory = load_sources(connection, manifest, data_dir)
    snapshot_date = datetime.fromisoformat(manifest["fetched_at"]).date()
    connection.execute("CREATE TABLE run_context (snapshot_date DATE)")
    connection.execute("INSERT INTO run_context VALUES (?)", [snapshot_date])
    connection.read_csv(str(ROOT / "config" / "sale_codes.csv"), all_varchar=True).create(
        "sale_codes"
    )
    connection.read_csv(str(ROOT / "config" / "municipalities.csv"), all_varchar=True).create(
        "municipalities"
    )
    for filename in (
        "01_normalize.sql",
        "02_reconcile.sql",
        "03_municipality_year.sql",
        "04_quality_checks.sql",
    ):
        run_sql(connection, filename)
    checks = [
        dict(zip(("check_name", "violations"), row))
        for row in connection.execute(
            "SELECT check_name, violations FROM quality_checks ORDER BY check_name"
        ).fetchall()
    ]
    failures = [check for check in checks if check["violations"]]
    if failures:
        examples = query_dicts(
            connection,
            "SELECT * FROM quality_violations ORDER BY check_name, source_id, source_record_id LIMIT 20",
        )
        raise QualityError("Data quality checks failed: " + json.dumps(failures), checks, examples)
    # Detect a material loss from an older annual file, not ordinary corrections.
    try:
        previous = json.loads((current_generation(data_dir) / "run_report.json").read_text())
    except FileNotFoundError:
        previous = {"resources": []}
    old_counts = {r["id"]: r["row_count"] for r in previous["resources"]}
    coverage_changes = [
        r
        for r in inventory
        if r["kind"] == "annual"
        and r["year"] < snapshot_date.year
        and old_counts.get(r["id"], 0) - r["row_count"] >= 100
        and r["row_count"] < old_counts[r["id"]] * 0.8
    ]
    if coverage_changes:
        raise QualityError(
            "Historical annual coverage fell over 20% and at least 100 rows; investigate before publishing",
            examples=coverage_changes,
        )
    return inventory, checks


def query_dicts(connection: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    cursor = connection.execute(sql)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def export_table(connection: duckdb.DuckDBPyConnection, query: str, path: Path) -> None:
    # Relation API handles the destination path without SQL string interpolation.
    connection.sql(query).write_csv(str(path), header=True)


def transformation_hashes() -> dict:
    paths = sorted(
        [
            *ROOT.glob("sales_pipeline/*.py"),
            *ROOT.glob("sql/*.sql"),
            *ROOT.glob("config/*.csv"),
            ROOT / "requirements.lock",
        ]
    )
    return {str(path.relative_to(ROOT)): file_hash(path) for path in paths}


def build_model(manifest_path: Path, data_dir: Path, *, already_locked: bool = False) -> Path:
    if not already_locked:
        with run_lock(data_dir):
            return build_model(manifest_path, data_dir, already_locked=True)
    published = data_dir / "published"
    published.mkdir(parents=True, exist_ok=True)
    generation_id = uuid.uuid4().hex
    staging = published / f".building-{generation_id}"
    staging.mkdir()
    try:
        manifest = verify_snapshot(manifest_path, data_dir)
        code_hashes = transformation_hashes()
        runtime = {"python": sys.version.split()[0], "duckdb": duckdb.__version__}
        signature = hashlib.sha256(
            json.dumps(
                {
                    "sources": [(r["id"], r["sha256"]) for r in manifest["resources"]],
                    "snapshot_date": manifest["fetched_at"][:10],
                    "transformations": code_hashes,
                    "runtime": runtime,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        try:
            current = current_generation(data_dir)
            prior_report = json.loads((current / "run_report.json").read_text())
            if prior_report.get("input_signature") == signature:
                verify_bundle(current)
                shutil.rmtree(staging)
                print(f"Unchanged sources and transformations; reusing {current.name}")
                return current
        except FileNotFoundError:
            pass
        with duckdb.connect(str(staging / "sales.duckdb")) as connection:
            inventory, checks = build_database(connection, manifest, data_dir)
            export_table(
                connection,
                "SELECT * FROM municipality_year ORDER BY municipality_code, sale_year",
                staging / "municipality_year.csv",
            )
            export_table(
                connection,
                "SELECT * FROM source_reconciliation ORDER BY sale_year",
                staging / "source_reconciliation.csv",
            )
            export_table(
                connection,
                "SELECT * FROM quality_checks ORDER BY check_name",
                staging / "quality_checks.csv",
            )
            export_table(
                connection,
                """
                SELECT sale_code, sale_description, count(*) AS transfers,
                    count(*) FILTER (WHERE is_standard_valid_sale) AS standard_valid_sales
                FROM clean_transfers GROUP BY sale_code, sale_description ORDER BY transfers DESC
            """,
                staging / "sale_code_profile.csv",
            )
            export_table(
                connection,
                "SELECT * FROM review_records ORDER BY transfer_id, source_id, row_fingerprint",
                staging / "review_records.csv",
            )
            export_table(
                connection,
                """
                SELECT municipality, sale_year, deed_book, deed_page, price,
                    count(*) AS parcel_rows, count(DISTINCT parcel_id) AS distinct_parcels
                FROM clean_transfers WHERE sale_code = 'H' AND price_usable
                GROUP BY municipality, sale_year, deed_book, deed_page, price
                HAVING count(*) > 1
                QUALIFY row_number() OVER (PARTITION BY municipality, sale_year
                    ORDER BY count(*) DESC, deed_book, deed_page, price) = 1
                ORDER BY municipality, sale_year
            """,
                staging / "repeated_deed_examples.csv",
            )
            totals = query_dicts(
                connection,
                """
                SELECT count(*) AS transfers, count(DISTINCT municipality_code) AS municipalities,
                    count(*) FILTER (WHERE is_standard_valid_sale) AS standard_valid_sales,
                    count(*) FILTER (WHERE resolution = 'conflicting_values') AS conflicting_values,
                    count(*) FILTER (WHERE NOT identity_usable) AS identity_review_transfers,
                    count(*) FILTER (WHERE potential_date_conflict) AS potential_date_conflicts,
                    count(*) FILTER (WHERE incomplete_deed_key) AS incomplete_deed_keys,
                    count(*) FILTER (WHERE record_date < sale_date) AS recording_before_sale,
                    min(sale_date) AS first_sale_date, max(sale_date) AS last_sale_date
                FROM clean_transfers
            """,
            )[0]
            reconciliation = query_dicts(
                connection, "SELECT * FROM source_reconciliation ORDER BY sale_year"
            )
        shutil.copyfile(manifest_path, staging / "manifest.json")
        output_hashes = {path.name: file_hash(path) for path in sorted(staging.glob("*.csv"))}
        output_hashes["manifest.json"] = file_hash(staging / "manifest.json")
        output_hash = hashlib.sha256((staging / "municipality_year.csv").read_bytes()).hexdigest()
        report = {
            "snapshot_fetched_at": manifest["fetched_at"],
            "output_sha256": output_hash,
            "input_signature": signature,
            "transformation_hashes": code_hashes,
            "runtime": runtime,
            "output_hashes": output_hashes,
            "totals": totals,
            "checks": checks,
            "resources": inventory,
            "reconciliation": reconciliation,
            "definition": "Standard-valid: code 0 / VALID SALE, positive price, agreed analytical values, complete deed key, no date conflict.",
        }
        (staging / "run_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
        verify_bundle(staging)
        generation = published / generation_id
        staging.rename(generation)
        # One atomic pointer switches the database, CSV and reports together.
        # A dashboard resolves this once per rerun and sees a consistent generation.
        pointer = published / "current.json"
        atomic_json(pointer, {"generation": generation_id})
        # Keep the current and one previous successful database generation.
        generations = sorted(
            [
                p
                for p in published.iterdir()
                if p.is_dir() and len(p.name) == 32 and all(c in "0123456789abcdef" for c in p.name)
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in generations[2:]:
            shutil.rmtree(old)
        print(f"Published {totals['transfers']:,} transfers; output SHA256 {output_hash}")
        return generation
    except Exception as error:
        failures = data_dir / "failures"
        failures.mkdir(parents=True, exist_ok=True)
        atomic_json(
            failures / f"{generation_id}.json",
            {
                "manifest": str(manifest_path),
                "error": str(error),
                "checks": getattr(error, "checks", []),
                "examples": getattr(error, "examples", []),
            },
        )
        shutil.rmtree(staging, ignore_errors=True)
        raise
