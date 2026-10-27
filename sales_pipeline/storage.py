"""Small shared helpers for one data directory and verifiable publications."""

import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def data_directory() -> Path:
    return Path(os.environ.get("SALES_DATA_DIR", str(ROOT / "data"))).resolve()


@contextmanager
def run_lock(data_dir: Path):
    """Portable exclusive creation. A crashed process leaves an inspectable lock."""
    data_dir.mkdir(parents=True, exist_ok=True)
    lock = data_dir / "run.lock"
    try:
        handle = lock.open("x")
    except FileExistsError:
        raise RuntimeError(
            f"Another run or stale lock exists: {lock}. Check its PID before removing it."
        ) from None
    try:
        with handle:
            handle.write(f"pid={os.getpid()}\n")
        yield
    finally:
        lock.unlink(missing_ok=True)


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, default=str) + "\n")
    temporary.replace(path)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def current_generation(data_dir: Path) -> Path:
    generation = json.loads((data_dir / "published" / "current.json").read_text())["generation"]
    if (
        not isinstance(generation, str)
        or len(generation) != 32
        or any(c not in "0123456789abcdef" for c in generation)
    ):
        raise ValueError("Invalid publication pointer")
    return data_dir / "published" / generation


def verify_bundle(directory: Path) -> dict:
    report = json.loads((directory / "run_report.json").read_text())
    required = {
        "municipality_year.csv",
        "source_reconciliation.csv",
        "sale_code_profile.csv",
        "quality_checks.csv",
        "review_records.csv",
        "repeated_deed_examples.csv",
        "manifest.json",
    }
    hashes = report.get("output_hashes", {})
    if not required.issubset(hashes):
        raise ValueError("Publication is missing required output checksums; rebuild the pipeline")
    for filename, expected in hashes.items():
        path = (directory / filename).resolve()
        if not path.is_relative_to(directory.resolve()) or file_hash(path) != expected:
            raise ValueError(f"Publication checksum mismatch: {filename}")
    if not report.get("checks") or any(check["violations"] for check in report["checks"]):
        raise ValueError("Publication has missing or failing quality checks")
    return report
