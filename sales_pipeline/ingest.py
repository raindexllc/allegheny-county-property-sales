"""Download complete CKAN resources without changing their bytes."""

from __future__ import annotations

import hashlib
import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sales_pipeline.storage import ROOT, atomic_json, file_hash

API_URL = "https://data.wprdc.org/api/3/action/package_show?id=real-estate-sales"
CONSOLIDATED_ID = "5bbe6c55-bce6-4edb-9d04-68edeb6bf7b1"


def request_bytes(url: str) -> tuple[bytes, dict]:
    """Retry transient network errors; never retry a permanent HTTP error."""
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "WPRDC-Property-Sales-Exercise/1.0"})
            with urlopen(request, timeout=180) as response:
                return response.read(), dict(response.headers)
        except (HTTPError, URLError, TimeoutError) as error:
            if isinstance(error, HTTPError) and error.code < 500 and error.code != 429:
                raise
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def save_raw(raw_dir: Path, resource_id: str, content: bytes, suffix: str) -> tuple[str, str]:
    digest = hashlib.sha256(content).hexdigest()
    path = raw_dir / resource_id / f"{digest}.{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(content)
        temporary.replace(path)
    return str(path.relative_to(raw_dir.parent)), digest


def discover(metadata: dict) -> list[dict]:
    """Select one consolidated CSV and every explicitly named annual CSV."""
    if not metadata.get("success"):
        raise ValueError("CKAN package_show was unsuccessful")
    resources = []
    for resource in metadata["result"]["resources"]:
        match = re.fullmatch(r"(\d{4}) Property Sales Transactions", resource["name"].strip())
        if resource["id"] == CONSOLIDATED_ID or match:
            if resource.get("format", "").upper() != "CSV":
                raise ValueError(f"Expected CSV resource: {resource['name']}")
            resources.append(
                {
                    "id": resource["id"],
                    "name": resource["name"],
                    "url": resource["url"],
                    "year": int(match[1]) if match else None,
                    "kind": "annual" if match else "consolidated",
                    "last_modified": resource.get("last_modified"),
                }
            )
    annual_years = sorted(r["year"] for r in resources if r["kind"] == "annual")
    if sum(r["kind"] == "consolidated" for r in resources) != 1 or not annual_years:
        raise ValueError("Missing consolidated or annual resources")
    if annual_years != list(range(2012, max(annual_years) + 1)):
        raise ValueError(f"Annual resources are missing or repeated: {annual_years}")
    with (ROOT / "config" / "resources.csv").open(newline="") as handle:
        baseline = list(csv.DictReader(handle))
    actual = {resource["id"]: resource for resource in resources}
    for expected in baseline:
        resource = actual.get(expected["id"])
        if not resource or resource["name"] != expected["name"]:
            raise ValueError(f"Expected resource missing or renamed: {expected['name']}")
    return sorted(resources, key=lambda r: (r["kind"] != "consolidated", r["year"] or 0))


def fetch_snapshot(data_dir: Path) -> Path:
    """A manifest is published only after every required resource downloads."""
    raw_dir = data_dir / "raw"
    metadata_bytes, _ = request_bytes(API_URL)
    resources = discover(json.loads(metadata_bytes))
    metadata_path, metadata_hash = save_raw(raw_dir, "package-metadata", metadata_bytes, "json")
    manifest = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "metadata_path": metadata_path,
        "metadata_sha256": metadata_hash,
        "resources": [],
    }
    for resource in resources:
        print(f"Downloading {resource['name']} ...", flush=True)
        content, headers = request_bytes(resource["url"])
        if not content or content.lstrip().startswith((b"<!DOCTYPE", b"<html")):
            raise ValueError(f"Empty or HTML response for {resource['name']}")
        path, digest = save_raw(raw_dir, resource["id"], content, "csv")
        manifest["resources"].append(
            {
                **resource,
                "path": path,
                "sha256": digest,
                "bytes": len(content),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "http_etag": headers.get("ETag"),
                "http_last_modified": headers.get("Last-Modified"),
            }
        )
        print(f"  {len(content):,} bytes; SHA256 {digest[:12]}", flush=True)
    # Recheck metadata to catch a publisher refresh during this multi-file fetch.
    after_bytes, _ = request_bytes(API_URL)
    after = discover(json.loads(after_bytes))
    if resources != after:
        raise ValueError("Source resource metadata changed during download; retry the run")
    manifests = data_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = manifests / f"{stamp}.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    # This pointer selects a complete raw snapshot, not a published model.
    latest = manifests / "latest.json"
    atomic_json(latest, manifest)
    return path


def verify_snapshot(manifest_path: Path, data_dir: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    files = [(manifest["metadata_path"], manifest["metadata_sha256"])]
    files.extend((r["path"], r["sha256"]) for r in manifest["resources"])
    for relative_path, expected in files:
        path = (data_dir / relative_path).resolve()
        if not path.is_relative_to(data_dir.resolve()):
            raise ValueError("Manifest path escapes the data directory")
        if file_hash(path) != expected:
            raise ValueError(f"Raw checksum mismatch: {relative_path}")
    expected_resources = discover(json.loads((data_dir / manifest["metadata_path"]).read_bytes()))
    observed_resources = [
        {key: resource[key] for key in expected_resources[0]} for resource in manifest["resources"]
    ]
    if observed_resources != expected_resources:
        raise ValueError("Manifest resource inventory does not match the saved CKAN metadata")
    return manifest
