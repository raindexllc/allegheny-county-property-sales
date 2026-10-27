import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

from conftest import row
from sales_pipeline import ingest
from sales_pipeline.ingest import discover, verify_snapshot
from sales_pipeline.model import QualityError, build_model, validate_csv
from sales_pipeline.snapshot import export_snapshot
from sales_pipeline.storage import current_generation, run_lock, verify_bundle


def scalar(generation, query):
    with duckdb.connect(str(generation / "sales.duckdb"), read_only=True) as connection:
        return connection.execute(query).fetchone()[0]


def test_identical_rerun_reuses_verified_generation(snapshot_factory):
    data, manifest = snapshot_factory()
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (data / "raw").rglob("*")
        if p.is_file()
    }
    first = build_model(manifest, data)
    second = build_model(manifest, data)
    assert first == second
    assert scalar(second, "SELECT count(*) FROM clean_transfers") == 15
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}


def test_source_correction_and_removal(snapshot_factory):
    data, manifest = snapshot_factory(
        consolidated=[row(), row("0002A00001000000")], annual=[row(), row("0002A00001000000")]
    )
    first = build_model(manifest, data)
    data, manifest = snapshot_factory(
        consolidated=[row(PRICE="200000")], annual=[row(PRICE="200000")]
    )
    second = build_model(manifest, data)
    assert (
        scalar(first, "SELECT recorded_transfers FROM municipality_year WHERE sale_year=2013") == 2
    )
    assert (
        scalar(second, "SELECT recorded_transfers FROM municipality_year WHERE sale_year=2013") == 1
    )
    assert (
        scalar(
            second, "SELECT median_standard_valid_price FROM municipality_year WHERE sale_year=2013"
        )
        == 200000
    )


def test_neither_source_wins_price_dispute(snapshot_factory):
    data, manifest = snapshot_factory(consolidated=[row(PRICE="200000")], annual=[row()])
    generation = build_model(manifest, data)
    assert (
        scalar(
            generation,
            "SELECT identity_review_transfers FROM municipality_year WHERE sale_year=2013",
        )
        == 1
    )
    assert (
        scalar(
            generation,
            "SELECT median_all_transfer_price FROM municipality_year WHERE sale_year=2013",
        )
        is None
    )
    assert scalar(generation, "SELECT count(*) FROM review_records WHERE year(sale_date)=2013") == 2


def test_descriptive_difference_preserves_agreed_analytical_values(snapshot_factory):
    data, manifest = snapshot_factory(annual=[row(FULL_ADDRESS="UPDATED ADDRESS")])
    generation = build_model(manifest, data)
    assert (
        scalar(generation, "SELECT resolution FROM clean_transfers WHERE sale_year=2013")
        == "descriptive_variation"
    )
    assert (
        scalar(
            generation, "SELECT standard_valid_sales FROM municipality_year WHERE sale_year=2013"
        )
        == 1
    )


def test_numeric_format_and_resource_ids_are_not_versions(snapshot_factory):
    data, manifest = snapshot_factory(consolidated=[row(_id="999", PRICE="100000.0")])
    generation = build_model(manifest, data)
    assert (
        scalar(generation, "SELECT distinct_versions FROM clean_transfers WHERE sale_year=2013")
        == 1
    )


def test_date_correction_candidate_excluded_without_merging(snapshot_factory):
    data, manifest = snapshot_factory(annual=[row(SALEDATE="2013-02-11")])
    generation = build_model(manifest, data)
    assert (
        scalar(generation, "SELECT recorded_transfers FROM municipality_year WHERE sale_year=2013")
        == 2
    )
    assert (
        scalar(
            generation,
            "SELECT potential_date_conflicts FROM municipality_year WHERE sale_year=2013",
        )
        == 2
    )
    assert (
        scalar(generation, "SELECT priced_transfers FROM municipality_year WHERE sale_year=2013")
        == 0
    )


def test_incomplete_deed_excluded_but_preserved(snapshot_factory):
    data, manifest = snapshot_factory(consolidated=[row(DEEDPAGE="")], annual=[row(DEEDPAGE="")])
    generation = build_model(manifest, data)
    assert (
        scalar(generation, "SELECT recorded_transfers FROM municipality_year WHERE sale_year=2013")
        == 1
    )
    assert (
        scalar(generation, "SELECT priced_transfers FROM municipality_year WHERE sale_year=2013")
        == 0
    )


def test_repeated_sales_and_multi_parcel_deeds(snapshot_factory):
    records = [
        row(),
        row(SALEDATE="2013-03-10", DEEDPAGE="2"),
        row("0002A00001000000", SALECODE="H", SALEDESC="MULTI-PARCEL SALE"),
        row("0003A00001000000", SALECODE="H", SALEDESC="MULTI-PARCEL SALE"),
    ]
    data, manifest = snapshot_factory(consolidated=records, annual=records)
    generation = build_model(manifest, data)
    assert (
        scalar(generation, "SELECT recorded_transfers FROM municipality_year WHERE sale_year=2013")
        == 4
    )
    assert (
        scalar(
            generation, "SELECT standard_valid_sales FROM municipality_year WHERE sale_year=2013"
        )
        == 2
    )


def test_text_identifiers_preserved(snapshot_factory):
    record = row(PROPERTYHOUSENUM="100A", PROPERTYZIP="00123")
    data, manifest = snapshot_factory(consolidated=[record], annual=[record])
    generation = build_model(manifest, data)
    assert (
        scalar(generation, "SELECT min(postal_code) FROM normalized WHERE year(sale_date)=2013")
        == "00123"
    )
    assert (
        scalar(generation, "SELECT min(house_number) FROM normalized WHERE year(sale_date)=2013")
        == "100A"
    )


@pytest.mark.parametrize(
    "changes,check_name",
    [
        ({"SALEDATE": "not-a-date"}, "date_parsing"),
        ({"PRICE": "bad"}, "price_format_and_precision"),
        ({"PRICE": "100000.001"}, "price_format_and_precision"),
        ({"PRICE": "-10"}, "nonnegative_prices"),
        ({"PARID": "broken"}, "required_identifiers"),
        ({"MUNICODE": "101.4"}, "municipality_reference"),
        ({"MUNICODE": "999999", "MUNIDESC": "Made Up Town"}, "municipality_reference"),
        ({"MUNIDESC": "Wrong City"}, "municipality_reference"),
        ({"SALECODE": "NEW", "SALEDESC": "NEW CATEGORY"}, "observed_sale_code_pairs"),
        ({"SALECODE": "0", "SALEDESC": "MULTI-PARCEL SALE"}, "observed_sale_code_pairs"),
        ({"SALEDATE": "2014-02-10"}, "annual_sale_year"),
    ],
)
def test_bad_data_blocks_publication_and_retains_examples(snapshot_factory, changes, check_name):
    data, manifest = snapshot_factory()
    first = build_model(manifest, data)
    pointer = (data / "published/current.json").read_bytes()
    data, manifest = snapshot_factory(consolidated=[row(**changes)], annual=[row(**changes)])
    with pytest.raises(QualityError, match=check_name):
        build_model(manifest, data)
    assert (data / "published/current.json").read_bytes() == pointer
    assert current_generation(data) == first
    failure = json.loads(next((data / "failures").glob("*.json")).read_text())
    assert failure["examples"]
    assert not list((data / "published").glob(".building-*"))


def test_all_four_city_rollups(snapshot_factory):
    records = [
        row(),
        row("0002A00001000000", MUNICODE="102", MUNIDESC="2nd Ward - PITTSBURGH"),
        row("0003A00001000000", MUNICODE="201", MUNIDESC="1st Ward - CLAIRTON"),
        row("0004A00001000000", MUNICODE="301", MUNIDESC="1st Ward  - DUQUESNE"),
        row("0005A00001000000", MUNICODE="401", MUNIDESC="1st Ward  - McKEESPORT"),
        row("0006A00001000000", MUNICODE="884", MUNIDESC="Franklin Park", PROPERTYCITY="SEWICKLEY"),
    ]
    data, manifest = snapshot_factory(consolidated=records, annual=records)
    generation = build_model(manifest, data)
    assert (
        scalar(
            generation,
            "SELECT recorded_transfers FROM municipality_year WHERE municipality='Pittsburgh' AND sale_year=2013",
        )
        == 2
    )
    assert scalar(generation, "SELECT count(*) FROM municipality_year WHERE sale_year=2013") == 5
    with duckdb.connect(str(generation / "sales.duckdb"), read_only=True) as connection:
        names = {
            r[0]
            for r in connection.execute(
                "SELECT municipality FROM municipality_year WHERE sale_year=2013"
            ).fetchall()
        }
    assert names == {"Pittsburgh", "Clairton", "Duquesne", "McKeesport", "Franklin Park"}


def test_discovery_detects_missing_latest_resource(snapshot_factory):
    data, manifest_path = snapshot_factory()
    manifest = json.loads(manifest_path.read_text())
    metadata = json.loads((data / manifest["metadata_path"]).read_text())
    metadata["result"]["resources"] = [
        r for r in metadata["result"]["resources"] if not r["name"].startswith("2026 ")
    ]
    with pytest.raises(ValueError, match="Expected resource missing"):
        discover(metadata)


def test_material_historical_count_loss_blocks(snapshot_factory):
    records = [row(f"{i:04d}A00001000000") for i in range(1, 202)]
    data, manifest = snapshot_factory(consolidated=records, annual=records)
    first = build_model(manifest, data)
    data, manifest = snapshot_factory(consolidated=[row()], annual=[row()])
    with pytest.raises(QualityError, match="coverage fell"):
        build_model(manifest, data)
    assert current_generation(data) == first


def test_corrupt_raw_or_missing_manifest_resource_fails(snapshot_factory):
    data, manifest_path = snapshot_factory()
    manifest = json.loads(manifest_path.read_text())
    raw = data / manifest["resources"][0]["path"]
    raw.write_bytes(raw.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_snapshot(manifest_path, data)
    data, manifest_path = snapshot_factory(consolidated=[row(PRICE="200000")])
    manifest = json.loads(manifest_path.read_text())
    manifest["resources"].pop()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="inventory"):
        verify_snapshot(manifest_path, data)


def test_malformed_csv_fails(tmp_path):
    from sales_pipeline.model import BUSINESS_COLUMNS

    path = tmp_path / "broken.csv"
    path.write_text(",".join(["_id", *BUSINESS_COLUMNS]) + "\nonly,two\n")
    with pytest.raises(QualityError, match="row width"):
        validate_csv(path)


def test_lock_is_exclusive_and_released(tmp_path):
    with run_lock(tmp_path):
        with pytest.raises(RuntimeError, match="Another run"):
            with run_lock(tmp_path):
                pass
    assert not (tmp_path / "run.lock").exists()


def test_only_two_generations_retained(snapshot_factory):
    for price in ["100000", "110000", "120000", "130000"]:
        data, manifest = snapshot_factory(
            consolidated=[row(PRICE=price)], annual=[row(PRICE=price)]
        )
        build_model(manifest, data)
    assert len([p for p in (data / "published").iterdir() if p.is_dir()]) == 2


def test_every_output_verified(snapshot_factory):
    data, manifest = snapshot_factory()
    generation = build_model(manifest, data)
    with (generation / "source_reconciliation.csv").open("a") as handle:
        handle.write("corrupt")
    with pytest.raises(ValueError, match="source_reconciliation"):
        verify_bundle(generation)


def test_export_failure_preserves_submission_bundle(snapshot_factory, tmp_path):
    data, manifest = snapshot_factory()
    build_model(manifest, data)
    destination = tmp_path / "submission"
    export_snapshot(data, destination)
    before = (destination / "municipality_year.csv").read_bytes()
    with patch(
        "sales_pipeline.snapshot.shutil.copyfile", side_effect=OSError("simulated copy failure")
    ):
        with pytest.raises(OSError):
            export_snapshot(data, destination)
    assert (destination / "municipality_year.csv").read_bytes() == before
    verify_bundle(destination)


def test_download_retries_transient_error():
    from urllib.error import URLError
    from unittest.mock import MagicMock

    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b"data"
    response.headers = {}
    with (
        patch.object(ingest, "urlopen", side_effect=[URLError("temporary"), response]) as get,
        patch.object(ingest.time, "sleep"),
    ):
        assert ingest.request_bytes("https://example.test")[0] == b"data"
        assert get.call_count == 2


def test_failed_download_or_changed_metadata_does_not_publish_manifest(snapshot_factory):
    data, manifest_path = snapshot_factory()
    before = manifest_path.read_bytes()
    manifest = json.loads(before)
    metadata = (data / manifest["metadata_path"]).read_bytes()
    with patch.object(
        ingest, "request_bytes", side_effect=[(metadata, {}), OSError("download failed")]
    ):
        with pytest.raises(OSError):
            ingest.fetch_snapshot(data)
    assert manifest_path.read_bytes() == before
    changed = json.loads(metadata)
    changed["result"]["resources"][0]["last_modified"] = "changed"
    responses = (
        [(metadata, {})]
        + [((data / r["path"]).read_bytes(), {}) for r in manifest["resources"]]
        + [(json.dumps(changed).encode(), {})]
    )
    with patch.object(ingest, "request_bytes", side_effect=responses):
        with pytest.raises(ValueError, match="changed during download"):
            ingest.fetch_snapshot(data)
    assert manifest_path.read_bytes() == before
