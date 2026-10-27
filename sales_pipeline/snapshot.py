"""Export the current validated output as the small, reviewable submission snapshot."""

import json
import shutil
from pathlib import Path

import duckdb

from sales_pipeline.model import ROOT, current_generation


def export_snapshot(data_dir: Path = ROOT / "data", destination: Path = ROOT / "results") -> None:
    generation = current_generation(data_dir)
    destination.mkdir(parents=True, exist_ok=True)
    for filename in (
        "municipality_year.csv", "source_reconciliation.csv", "quality_checks.csv",
        "sale_code_profile.csv", "run_report.json", "manifest.json",
    ):
        shutil.copyfile(generation / filename, destination / filename)
    report = json.loads((generation / "run_report.json").read_text())
    with duckdb.connect(str(generation / "sales.duckdb"), read_only=True) as connection:
        # Store readable evidence examples; retain every source variant in DuckDB.
        examples = connection.execute("""
            SELECT parcel_id, sale_date, price, sale_code, sale_description,
                source_kind, source_year, source_record_id, resolution
            FROM conflict_records WHERE resolution = 'unresolved_conflict'
            ORDER BY transfer_id, source_kind, row_fingerprint
        """).fetchdf()
        examples.to_csv(destination / "unresolved_conflicts.csv", index=False)
        year = int(connection.execute("SELECT max(sale_year) FROM municipality_year WHERE sale_year < ?", [int(report["snapshot_fetched_at"][:4])]).fetchone()[0])
        rows = connection.execute("""
            SELECT municipality, recorded_transfers, eligible_market_sales,
                median_recorded_price, median_market_price, median_difference_pct
            FROM municipality_year WHERE sale_year = ? AND eligible_market_sales >= 30
                AND median_recorded_price > 0
            ORDER BY median_difference_pct DESC, municipality LIMIT 10
        """, [year]).fetchall()
        output = ["# Observed findings", "", f"Snapshot retrieved: {report['snapshot_fetched_at']}.", "",
                  "These are measurements from the downloaded resources, not claims of complete real-world sales coverage.", "",
                  "## Source reconciliation", "",
                  "| Sale year | Reconciled identities | In both | Annual only | Consolidated only | Unresolved |",
                  "|---|---:|---:|---:|---:|---:|"]
        for item in report["reconciliation"]:
            output.append(f"| {item['sale_year']} | {item['reconciled_transfers']:,} | {item['in_both']:,} | {item['annual_only']:,} | {item['consolidated_only']:,} | {item['unresolved_conflicts']} |")
        output.extend(["", f"## Largest median differences in {year}", "",
                       "Municipalities with at least 30 eligible sales and a positive all-transfer median. Percentage difference = eligible median / all-priced-transfer median − 1.", "",
                       "| Municipality | Recorded transfers | Eligible sales | All-priced-transfer median | Eligible-sale median | Difference |",
                       "|---|---:|---:|---:|---:|---:|"])
        for name, count, eligible, all_median, market_median, difference in rows:
            output.append(f"| {name} | {count:,} | {eligible:,} | ${all_median:,.2f} | ${market_median:,.2f} | {difference:.1%} |")
        output.extend(["", "Eligible means sale code 0 (`VALID SALE`), positive price, and no unresolved identity conflict. This is a deliberately narrow analytical subset, not an estimate of all market transactions.", "",
                       "The two medians describe different transaction groups. Their difference is not price appreciation, a causal effect, or a measure of housing affordability. Property types and sale-code review practices may differ across municipalities and years.", "",
                       "The latest observed year is partial. Even a completed calendar year can receive late recordings and corrections.", ""])
        (destination / "findings.md").write_text("\n".join(output))
    print(f"Exported submission snapshot to {destination}")


if __name__ == "__main__":
    export_snapshot()
