"""Import admin-provided master data from JSON without built-in business values."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.repositories.master_data import MasterDataRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON file with routes, products, and customers arrays")
    parser.add_argument("--apply", action="store_true", help="write imported records; default is validation only")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    expected = {"routes", "products", "customers"}
    if set(payload) - expected:
        parser.error(f"Unexpected input keys: {sorted(set(payload) - expected)}")
    for key in expected:
        if key in payload and not isinstance(payload[key], list):
            parser.error(f"{key} must be a JSON array")
    counts = {key: len(payload.get(key, [])) for key in expected}
    if not args.apply:
        print(json.dumps({"validated_counts": counts, "written": False}, indent=2))
        return 0

    repository = MasterDataRepository()
    for route in payload.get("routes", []):
        repository.create_route(route, "SeedImport")
    for product in payload.get("products", []):
        repository.create_product(product, "SeedImport")
    for customer in payload.get("customers", []):
        repository.create_customer(customer, "SeedImport")
    print(json.dumps({"imported_counts": counts, "written": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

