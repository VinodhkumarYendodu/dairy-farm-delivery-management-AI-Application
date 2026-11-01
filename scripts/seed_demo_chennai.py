"""Idempotently add clearly marked Chennai demo master data and availability."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.repositories.master_data import MasterDataRepository
from database.repositories.subscriptions import SubscriptionRepository
from database.connection import sql_connection


ROUTES = [
    {"route_name": "DEMO - Adyar", "description": "DEMO ONLY - Chennai sample route"},
    {"route_name": "DEMO - Velachery", "description": "DEMO ONLY - Chennai sample route"},
    {"route_name": "DEMO - Anna Nagar", "description": "DEMO ONLY - Chennai sample route"},
]
PRODUCTS = [
    {"product_code": "DEMO-TONED", "product_name": "DEMO Toned Milk", "unit_of_measure": "litre",
     "initial_price": Decimal("50.00")},
    {"product_code": "DEMO-FULL-CREAM", "product_name": "DEMO Full Cream Milk", "unit_of_measure": "litre",
     "initial_price": Decimal("68.00")},
    {"product_code": "DEMO-CURD", "product_name": "DEMO Curd", "unit_of_measure": "kg",
     "initial_price": Decimal("80.00")},
]
CUSTOMERS = [
    {"customer_code": "DEMO-ADYAR-001", "full_name": "Demo Customer - Adyar", "mobile": "0000000001",
     "email": "demo.adyar@example.invalid", "address": "Demo address, Adyar, Chennai, Tamil Nadu",
     "area": "Adyar", "route_name": "DEMO - Adyar", "preferred_contact_method": "PHONE",
     "notes": "DEMO DATA ONLY - fictional customer; do not contact."},
    {"customer_code": "DEMO-VEL-001", "full_name": "Demo Customer - Velachery", "mobile": "0000000002",
     "email": "demo.velachery@example.invalid", "address": "Demo address, Velachery, Chennai, Tamil Nadu",
     "area": "Velachery", "route_name": "DEMO - Velachery", "preferred_contact_method": "PHONE",
     "notes": "DEMO DATA ONLY - fictional customer; do not contact."},
    {"customer_code": "DEMO-AN-001", "full_name": "Demo Customer - Anna Nagar", "mobile": "0000000003",
     "email": "demo.annanagar@example.invalid", "address": "Demo address, Anna Nagar, Chennai, Tamil Nadu",
     "area": "Anna Nagar", "route_name": "DEMO - Anna Nagar", "preferred_contact_method": "PHONE",
     "notes": "DEMO DATA ONLY - fictional customer; do not contact."},
]


def ensure_demo_audit(repository: MasterDataRepository, entity_type: str, entity_id: int, summary: dict) -> None:
    with sql_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT TOP (1) 1 FROM dbo.AuditLogs WHERE Actor=? AND Action='CREATE' AND EntityType=? AND EntityId=?",
            "DEMO_SEED", entity_type, str(entity_id),
        )
        exists = cursor.fetchone() is not None
        cursor.close()
    if not exists:
        repository.audit("DEMO_SEED", "CREATE", entity_type, entity_id, None, summary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write demo records; default is a preview")
    parser.add_argument("--availability-days", type=int, default=7, choices=range(1, 32),
                        help="number of days of sample availability to add (default: 7)")
    args = parser.parse_args()
    today = date.today()
    plan = {"routes": ROUTES, "products": PRODUCTS, "customers": CUSTOMERS,
            "availability_days": args.availability_days, "availability_start": today.isoformat()}
    if not args.apply:
        print(json.dumps(plan, indent=2, default=str))
        print("Preview only. Pass --apply to write these clearly marked demo records.")
        return 0

    repository = MasterDataRepository()
    existing_routes = {row["route_name"] for row in repository.list_routes()}
    for route in ROUTES:
        if route["route_name"] not in existing_routes:
            repository.create_route(route, "DEMO_SEED")

    route_ids = {row["route_name"]: row["id"] for row in repository.list_routes()}
    for route in repository.list_routes():
        if route["route_name"].startswith("DEMO - "):
            ensure_demo_audit(repository, "DeliveryRoute", route["id"], route)

    existing_products = {row["product_code"]: row for row in repository.list_products()}
    for product in PRODUCTS:
        if product["product_code"] not in existing_products:
            repository.create_product(
                {**product, "price_effective_from": today}, "DEMO_SEED"
            )
    for product in repository.list_products():
        if product["product_code"].startswith("DEMO-"):
            ensure_demo_audit(repository, "MilkProduct", product["id"], product)

    existing_customers = {row["customer_code"] for row in repository.list_customers()}
    for customer in CUSTOMERS:
        if customer["customer_code"] not in existing_customers:
            item = {**customer, "route_id": route_ids[customer["route_name"]]}
            item.pop("route_name")
            repository.create_customer(item, "DEMO_SEED")
    for customer in repository.list_customers():
        if customer["customer_code"].startswith("DEMO-"):
            ensure_demo_audit(repository, "Customer", customer["id"], customer)

    products_by_code = {row["product_code"]: row for row in repository.list_products()}
    subscription_repository = SubscriptionRepository()
    end = today + timedelta(days=args.availability_days - 1)
    existing_availability = {
        (row["availability_date"], row["product_id"])
        for row in subscription_repository.list_availability(today, end)
    }
    quantities = {"DEMO-TONED": Decimal("60.000"), "DEMO-FULL-CREAM": Decimal("40.000"),
                  "DEMO-CURD": Decimal("25.000")}
    availability_created = 0
    for day_offset in range(args.availability_days):
        day = today + timedelta(days=day_offset)
        for code, quantity in quantities.items():
            product_id = products_by_code[code]["id"]
            if (day, product_id) in existing_availability:
                continue
            subscription_repository.set_availability(day, product_id, quantity, "DEMO_SEED")
            availability_created += 1

    print(json.dumps({
        "routes_present": len(ROUTES),
        "products_present": len(PRODUCTS),
        "customers_present": len(CUSTOMERS),
        "availability_rows_added": availability_created,
        "availability_through": end.isoformat(),
        "actor": "DEMO_SEED",
    }, indent=2))
    print("All records are marked DEMO; email addresses use the reserved .invalid domain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
