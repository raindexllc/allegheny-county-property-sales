"""Small synthetic snapshots using the real, checked resource inventory."""

import csv
import io
import json
from pathlib import Path

import pytest

from sales_pipeline.ingest import save_raw
from sales_pipeline.model import BUSINESS_COLUMNS
from sales_pipeline.storage import ROOT


def row(parcel="0001A00001000000", **changes):
    result = dict.fromkeys(["_id", *BUSINESS_COLUMNS], "")
    result.update(
        {
            "_id": "1",
            "PARID": parcel,
            "FULL_ADDRESS": "100 MAIN ST, PITTSBURGH, PA 15222",
            "PROPERTYHOUSENUM": "100",
            "PROPERTYCITY": "PITTSBURGH",
            "PROPERTYSTATE": "PA",
            "PROPERTYZIP": "15222",
            "SCHOOLCODE": "47",
            "SCHOOLDESC": "Pittsburgh",
            "MUNICODE": "101",
            "MUNIDESC": "1st Ward  - PITTSBURGH",
            "RECORDDATE": "2013-02-15",
            "SALEDATE": "2013-02-10",
            "PRICE": "100000",
            "DEEDBOOK": "12345",
            "DEEDPAGE": "1",
            "SALECODE": "0",
            "SALEDESC": "VALID SALE",
            "INSTRTYP": "DE",
            "INSTRTYPDESC": "DEED",
        }
    )
    result.update(changes)
    return result


@pytest.fixture
def snapshot_factory(tmp_path):
    def make(consolidated=None, annual=None):
        data_dir = tmp_path / "data"
        with (ROOT / "config/resources.csv").open(newline="") as handle:
            inventory = list(csv.DictReader(handle))
        definitions = []
        for resource in inventory:
            year = int(resource["year"]) if resource["year"] else None
            if year is None:
                records = [row()] if consolidated is None else consolidated
            elif year == 2013:
                records = [row()] if annual is None else annual
            else:
                records = [
                    row(
                        f"{year}Z00001000000",
                        SALEDATE=f"{year}-01-02",
                        RECORDDATE=f"{year}-01-03",
                        DEEDBOOK=f"YEAR{year}",
                        PRICE="50000",
                    )
                ]
            definitions.append((resource, year, records))
        metadata = {
            "success": True,
            "result": {
                "resources": [
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "format": "CSV",
                        "url": f"https://example.test/{r['id']}",
                        "last_modified": "2026-10-26T00:00:00",
                    }
                    for r, _, _ in definitions
                ]
            },
        }
        metadata_bytes = json.dumps(metadata).encode()
        path, digest = save_raw(data_dir / "raw", "package-metadata", metadata_bytes, "json")
        manifest = {
            "fetched_at": "2026-10-27T12:00:00+00:00",
            "metadata_path": path,
            "metadata_sha256": digest,
            "resources": [],
        }
        for resource, year, records in definitions:
            buffer = io.StringIO(newline="")
            csv.DictWriter(buffer, fieldnames=["_id", *BUSINESS_COLUMNS]).writeheader()
            csv.DictWriter(
                buffer, fieldnames=["_id", *BUSINESS_COLUMNS], lineterminator="\n"
            ).writerows(records)
            content = buffer.getvalue().encode()
            path, digest = save_raw(data_dir / "raw", resource["id"], content, "csv")
            manifest["resources"].append(
                {
                    "id": resource["id"],
                    "name": resource["name"],
                    "url": f"https://example.test/{resource['id']}",
                    "year": year,
                    "kind": resource["kind"],
                    "last_modified": "2026-10-26T00:00:00",
                    "path": path,
                    "sha256": digest,
                    "bytes": len(content),
                    "fetched_at": manifest["fetched_at"],
                }
            )
        manifest_dir = data_dir / "manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "latest.json"
        manifest_path.write_text(json.dumps(manifest))
        return data_dir, manifest_path

    return make
