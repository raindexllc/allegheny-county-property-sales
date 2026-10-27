import hashlib
import json

import duckdb
import pytest

from sales_pipeline.ingest import discover, verify_snapshot
from sales_pipeline.model import QualityError, build_model, current_generation, validate_csv
from conftest import row


def read_scalar(generation, query):
    with duckdb.connect(str(generation / "sales.duckdb"), read_only=True) as connection:
        return connection.execute(query).fetchone()[0]


def test_identical_reruns_and_raw_preservation(snapshot_factory):
    data_dir, manifest = snapshot_factory()
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (data_dir / "raw").rglob("*") if path.is_file()}
    first = build_model(manifest, data_dir)
    second = build_model(manifest, data_dir)
    assert (first / "municipality_year.csv").read_bytes() == (second / "municipality_year.csv").read_bytes()
    assert read_scalar(second, "SELECT count(*) FROM clean_transfers") == 2
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before}


def test_correction_replaces_price_instead_of_adding_transfer(snapshot_factory):
    data_dir, manifest = snapshot_factory()
    first = build_model(manifest, data_dir)
    data_dir, manifest = snapshot_factory(consolidated=[row(PRICE="200000")], annual=[row(PRICE="200000")])
    second = build_model(manifest, data_dir)
    assert read_scalar(first, "SELECT median_market_price FROM municipality_year WHERE sale_year=2013") == 100000
    assert read_scalar(second, "SELECT median_market_price FROM municipality_year WHERE sale_year=2013") == 200000
    assert read_scalar(second, "SELECT recorded_transfers FROM municipality_year WHERE sale_year=2013") == 1


def test_source_removal_does_not_leave_stale_transfer(snapshot_factory):
    old = row("0002A00001000000")
    data_dir, manifest = snapshot_factory(consolidated=[row(), old], annual=[row(), old])
    first = build_model(manifest, data_dir)
    data_dir, manifest = snapshot_factory()
    second = build_model(manifest, data_dir)
    assert read_scalar(first, "SELECT count(*) FROM clean_transfers") == 3
    assert read_scalar(second, "SELECT count(*) FROM clean_transfers") == 2


def test_resource_local_ids_and_numeric_formatting_do_not_create_duplicates(snapshot_factory):
    data_dir, manifest = snapshot_factory(consolidated=[row(_id="99999", PRICE="100000.0")])
    generation = build_model(manifest, data_dir)
    assert read_scalar(generation, "SELECT distinct_versions FROM clean_transfers WHERE sale_year=2013") == 1


def test_repeated_sales_of_a_parcel_and_multi_parcel_deeds_are_preserved(snapshot_factory):
    records = [row(), row(SALEDATE="2013-03-10", DEEDPAGE="2"),
               row("0002A00001000000", SALECODE="H", SALEDESC="MULTI-PARCEL SALE"),
               row("0003A00001000000", SALECODE="H", SALEDESC="MULTI-PARCEL SALE")]
    data_dir, manifest = snapshot_factory(consolidated=records, annual=records)
    generation = build_model(manifest, data_dir)
    assert read_scalar(generation, "SELECT recorded_transfers FROM municipality_year WHERE sale_year=2013") == 4
    assert read_scalar(generation, "SELECT eligible_market_sales FROM municipality_year WHERE sale_year=2013") == 2


def test_unresolved_versions_do_not_supply_market_prices(snapshot_factory):
    contested = row("0002A00001000000")
    data_dir, manifest = snapshot_factory(annual=[row(), contested, {**contested, "PRICE": "900000"}])
    generation = build_model(manifest, data_dir)
    assert read_scalar(generation, "SELECT recorded_transfers FROM municipality_year WHERE sale_year=2013") == 2
    assert read_scalar(generation, "SELECT median_market_price FROM municipality_year WHERE sale_year=2013") == 100000
    assert read_scalar(generation, "SELECT count(*) FROM conflict_records WHERE resolution='unresolved_conflict'") == 2
    assert read_scalar(generation, "SELECT count(*) FROM clean_transfers WHERE resolution='unresolved_conflict' AND price IS NOT NULL") == 0


def test_consolidated_precedence_is_explicit(snapshot_factory):
    data_dir, manifest = snapshot_factory(consolidated=[row(PRICE="200000")], annual=[row()])
    generation = build_model(manifest, data_dir)
    assert read_scalar(generation, "SELECT median_market_price FROM municipality_year WHERE sale_year=2013") == 200000
    assert read_scalar(generation, "SELECT resolution FROM clean_transfers WHERE sale_year=2013") == "consolidated_preferred"


def test_city_wards_roll_up_but_postal_city_does_not_define_municipality(snapshot_factory):
    records = [row(), row("0002A00001000000", MUNICODE="102", MUNIDESC="2nd Ward - PITTSBURGH"),
               row("0003A00001000000", MUNICODE="884", MUNIDESC="Franklin Park", PROPERTYCITY="SEWICKLEY")]
    data_dir, manifest = snapshot_factory(consolidated=records, annual=records)
    generation = build_model(manifest, data_dir)
    assert read_scalar(generation, "SELECT recorded_transfers FROM municipality_year WHERE municipality='Pittsburgh' AND sale_year=2013") == 2
    assert read_scalar(generation, "SELECT count(*) FROM municipality_year WHERE municipality='Franklin Park'") == 1


@pytest.mark.parametrize("changes, check_name", [
    ({"SALEDATE": "not-a-date"}, "typed_dates_and_price"),
    ({"PRICE": "not-a-price"}, "typed_dates_and_price"),
    ({"PRICE": "-10"}, "nonnegative_prices"),
    ({"PARID": "broken"}, "required_identifiers"),
    ({"SALECODE": "NEW", "SALEDESC": "NEW CATEGORY"}, "reviewed_sale_code_descriptions"),
    ({"SALECODE": "0", "SALEDESC": "MULTI-PARCEL SALE"}, "reviewed_sale_code_descriptions"),
    ({"SALEDATE": "2014-02-10"}, "annual_file_matches_sale_year"),
    ({"MUNIDESC": "Wrong City"}, "ward_labels_match_city_rollup"),
])
def test_bad_data_fails_and_preserves_last_successful_publication(snapshot_factory, changes, check_name):
    data_dir, manifest = snapshot_factory()
    first = build_model(manifest, data_dir)
    pointer_before = (data_dir / "published" / "current.json").read_bytes()
    data_dir, manifest = snapshot_factory(consolidated=[row(**changes)], annual=[row(**changes)])
    with pytest.raises(QualityError, match=check_name):
        build_model(manifest, data_dir)
    assert (data_dir / "published" / "current.json").read_bytes() == pointer_before
    assert current_generation(data_dir) == first
    assert not list((data_dir / "published").glob(".building-*"))


def test_ambiguous_consolidated_identity_fails(snapshot_factory):
    data_dir, manifest = snapshot_factory(consolidated=[row(), row(PRICE="200000")])
    with pytest.raises(QualityError, match="consolidated_identity_unambiguous"):
        build_model(manifest, data_dir)


def test_raw_tampering_fails_checksum(snapshot_factory):
    data_dir, manifest_path = snapshot_factory()
    manifest = json.loads(manifest_path.read_text())
    raw_path = data_dir / manifest["resources"][0]["path"]
    raw_path.write_bytes(raw_path.read_bytes() + b"corruption")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_snapshot(manifest_path, data_dir)


def test_missing_resource_in_manifest_fails(snapshot_factory):
    data_dir, manifest_path = snapshot_factory()
    manifest = json.loads(manifest_path.read_text())
    manifest["resources"].pop()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="inventory"):
        verify_snapshot(manifest_path, data_dir)


def test_malformed_csv_row_fails(tmp_path):
    from sales_pipeline.model import BUSINESS_COLUMNS
    path = tmp_path / "broken.csv"
    path.write_text(",".join(["_id", *BUSINESS_COLUMNS]) + "\nonly,two\n")
    with pytest.raises(QualityError, match="row width"):
        validate_csv(path)


def test_discovery_skips_html_and_detects_missing_years():
    resources = [
        {"id": "5bbe6c55-bce6-4edb-9d04-68edeb6bf7b1", "name": "Property Sales Transactions", "format": "CSV", "url": "https://example.test/main"},
        {"id": "a", "name": "2012 Property Sales Transactions", "format": "CSV", "url": "https://example.test/a"},
        {"id": "html", "name": "Dashboard", "format": "HTML", "url": "https://example.test/dashboard"},
    ]
    assert len(discover({"success": True, "result": {"resources": resources}})) == 2
    resources.append({"id": "b", "name": "2014 Property Sales Transactions", "format": "CSV", "url": "https://example.test/b"})
    with pytest.raises(ValueError, match="missing or repeated"):
        discover({"success": True, "result": {"resources": resources}})
