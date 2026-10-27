"""Run with: python -m sales_pipeline [--offline | --manifest PATH]."""

import argparse
from pathlib import Path

from sales_pipeline.ingest import fetch_snapshot
from sales_pipeline.model import build_model


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile WPRDC property sales and build municipal metrics.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Rebuild the last complete raw snapshot, without networking")
    mode.add_argument("--manifest", type=Path, help="Rebuild a specific saved snapshot")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    args.data_dir = args.data_dir.resolve()
    if args.manifest:
        manifest_path = args.manifest.resolve()
    elif args.offline:
        manifest_path = args.data_dir / "manifests" / "latest.json"
    else:
        manifest_path = fetch_snapshot(args.data_dir)
    if not manifest_path.exists():
        parser.error("No saved snapshot exists. Run without --offline first.")
    generation = build_model(manifest_path, args.data_dir)
    print(f"Analytical table: {generation / 'municipality_year.csv'}")


if __name__ == "__main__":
    main()
