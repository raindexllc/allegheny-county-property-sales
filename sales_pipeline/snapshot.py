"""Stage, verify, then replace the small Git submission bundle with rollback."""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

import duckdb

from sales_pipeline.storage import ROOT, current_generation, data_directory, run_lock, verify_bundle


def write_findings(connection, report: dict, destination: Path) -> None:
    rows = connection.execute("""
        SELECT municipality, sale_year, recorded_transfers, standard_valid_sales,
            median_all_transfer_price, median_standard_valid_price, median_gap_pct
        FROM municipality_year
        WHERE (municipality = 'Pittsburgh' AND sale_year = 2025)
           OR (municipality = 'Clairton' AND sale_year = 2020)
        ORDER BY sale_year DESC, municipality
    """).fetchall()
    lines = [
        "# Observed findings",
        "",
        f"Snapshot retrieved: {report['snapshot_fetched_at']}.",
        "",
        "## The source files have different coverage",
        "",
        "| Sale year | Reconciled identities | In both | Annual only | Consolidated only |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in report["reconciliation"]:
        lines.append(
            f"| {row['sale_year']} | {row['reconciled_transfers']:,} | {row['in_both']:,} | {row['annual_only']:,} | {row['consolidated_only']:,} |"
        )
    lines += [
        "",
        "Coverage describes the downloaded resources, not every real-world sale. Missing records do not establish the cause of a coverage discrepancy.",
        "",
        "## Transfer composition can change the comparison in either direction",
        "",
        "| Municipality | Year | Recorded identities | Standard-valid sales | All priced transfers: median | Standard-valid sales: median | Difference |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, year, total, valid, all_price, valid_price, gap in rows:
        if all_price is not None and valid_price is not None:
            lines.append(
                f"| {name} | {year} | {total:,} | {valid:,} | ${all_price:,.2f} | ${valid_price:,.2f} | {gap:.1%} |"
            )
    lines += [
        "",
        "Standard-valid means publisher code 0 / VALID SALE, positive price, agreed analytical values, a complete deed key and no same-deed/different-date ambiguity. This is a selected subset of all priced transfers, not a separate population.",
        "",
        "Family transfers and repeated multi-parcel deed prices help explain why the groups differ. The category counts and medians are descriptive evidence, not a causal decomposition. The result is not price appreciation or a home-only market estimate.",
        "",
        "All conflicting analytical values are withheld; neither source family wins a dispute. Other identity concerns remain flagged, not automatically merged. See review_records.csv for evidence.",
        "",
    ]
    example = connection.execute("""
        SELECT deed_book, deed_page, price, count(DISTINCT parcel_id) AS parcels
        FROM clean_transfers WHERE municipality='Clairton' AND sale_year=2020
            AND sale_code='H' AND price_usable
        GROUP BY deed_book, deed_page, price ORDER BY parcels DESC, deed_book, deed_page LIMIT 1
    """).fetchone()
    if example:
        book, page, price, count = example
        lines += [
            f"Clairton 2020 example: **{count:,} distinct parcels** share deed book {book}/page {page} and repeat **${price:,.2f}**. Do not sum this price across those parcel records.",
            "",
        ]
    (destination / "findings.md").write_text("\n".join(lines).replace("$", "\\$"))


def export_snapshot(data_dir: Path | None = None, destination: Path = ROOT / "results") -> None:
    data_dir = data_directory() if data_dir is None else data_dir.resolve()
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with run_lock(data_dir):
        generation = current_generation(data_dir)
        report = verify_bundle(generation)
        staging = Path(tempfile.mkdtemp(prefix=".results-building-", dir=destination.parent))
        backup = staging.with_name(staging.name.replace("building", "backup"))
        try:
            for filename in [*report["output_hashes"], "run_report.json"]:
                shutil.copyfile(generation / filename, staging / filename)
            with duckdb.connect(str(generation / "sales.duckdb"), read_only=True) as connection:
                write_findings(connection, report, staging)
            verify_bundle(staging)
            if destination.exists():
                destination.rename(backup)
            try:
                staging.rename(destination)
            except Exception:
                if backup.exists():
                    backup.rename(destination)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    print(f"Exported verified submission bundle to {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=data_directory())
    parser.add_argument("--destination", type=Path, default=ROOT / "results")
    args = parser.parse_args()
    export_snapshot(args.data_dir, args.destination)
