"""Tiny, explicitly synthetic CKAN-style snapshots for behavioral tests."""

import csv
import io
import json

import pytest

from sales_pipeline.ingest import CONSOLIDATED_ID, save_raw
from sales_pipeline.model import BUSINESS_COLUMNS


def row(parcel="0001A00001000000", **changes):
    result = dict.fromkeys(["_id", *BUSINESS_COLUMNS], "")
    result.update({
        "_id": "1", "PARID": parcel, "FULL_ADDRESS": "100 MAIN ST, PITTSBURGH, PA 15222",
        "PROPERTYHOUSENUM": "100", "PROPERTYCITY": "PITTSBURGH", "PROPERTYSTATE": "PA",
        "PROPERTYZIP": "15222", "SCHOOLCODE": "47", "SCHOOLDESC": "Pittsburgh",
        "MUNICODE": "101", "MUNIDESC": "1st Ward  - PITTSBURGH",
        "RECORDDATE": "2013-02-15", "SALEDATE": "2013-02-10", "PRICE": "100000",
        "DEEDBOOK": "12345", "DEEDPAGE": "1", "SALECODE": "0", "SALEDESC": "VALID SALE",
        "INSTRTYP": "DE", "INSTRTYPDESC": "DEED",
    })
    result.update(changes)
    return result


@pytest.fixture
def snapshot_factory(tmp_path):
    def make(consolidated=None, annual=None):
        data_dir = tmp_path / "data"
        annual = annual if annual is not None else [row()]
        consolidated = consolidated if consolidated is not None else [row()]
        # Keep one independent 2012 record so every discovered annual resource is nonempty.
        historical = [row("0000A00001000000", SALEDATE="2012-06-01", RECORDDATE="2012-06-02", PRICE="50000")]
        definitions = [
            (CONSOLIDATED_ID, "Property Sales Transactions", None, consolidated),
            ("annual-2012", "2012 Property Sales Transactions", 2012, historical),
            ("annual-2013", "2013 Property Sales Transactions", 2013, annual),
        ]
        metadata = {"success": True, "result": {"resources": [
            {"id": resource_id, "name": name, "format": "CSV", "url": f"https://example.test/{resource_id}", "last_modified": "2026-10-26T00:00:00"}
            for resource_id, name, _, _ in definitions
        ]}}
        metadata_bytes = json.dumps(metadata).encode()
        path, digest = save_raw(data_dir / "raw", "package-metadata", metadata_bytes, "json")
        manifest = {"fetched_at": "2026-10-27T12:00:00+00:00", "metadata_path": path, "metadata_sha256": digest, "resources": []}
        for resource_id, name, year, records in definitions:
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=["_id", *BUSINESS_COLUMNS])
            writer.writeheader()
            # Reproduce the observed CKAN header-CRLF/body-LF dialect.
            writer = csv.DictWriter(buffer, fieldnames=["_id", *BUSINESS_COLUMNS], lineterminator="\n")
            writer.writerows(records)
            content = buffer.getvalue().encode()
            path, digest = save_raw(data_dir / "raw", resource_id, content, "csv")
            manifest["resources"].append({
                "id": resource_id, "name": name, "url": f"https://example.test/{resource_id}",
                "year": year, "kind": "annual" if year else "consolidated",
                "last_modified": "2026-10-26T00:00:00", "path": path, "sha256": digest,
                "bytes": len(content), "fetched_at": manifest["fetched_at"],
            })
        manifest_dir = data_dir / "manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "latest.json"
        manifest_path.write_text(json.dumps(manifest))
        return data_dir, manifest_path
    return make
