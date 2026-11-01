"""Parameterized SQL repository for Phase 2 master data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from database.connection import sql_connection


def _safe_audit_value(value: Any) -> str | None:
    if not value:
        return None
    if not isinstance(value, dict):
        return str(value)[:2000]
    safe_keys = (
        "id", "customer_code", "product_code", "product_name", "unit_of_measure", "route_id", "route_name",
        "is_active", "preferred_contact_method",
    )
    return "; ".join(f"{key}={value[key]}" for key in safe_keys if key in value)[:2000]


class MasterDataRepository:
    def _fetch_all(self, query: str, *params: Any) -> list[dict[str, Any]]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(query, *params)
            names = [column[0] for column in cursor.description]
            result = [dict(zip(names, row)) for row in cursor.fetchall()]
            cursor.close()
            return result

    def _execute(self, query: str, *params: Any) -> dict[str, Any] | None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(query, *params)
            row = cursor.fetchone() if cursor.description else None
            result = dict(zip((c[0] for c in cursor.description), row)) if row else None
            connection.commit()
            cursor.close()
            return result

    def list_customers(self, search: str | None = None, active: bool | None = None) -> list[dict[str, Any]]:
        return self._fetch_all(
            "SELECT c.CustomerId AS id, c.CustomerCode AS customer_code, c.FullName AS full_name, "
            "c.Mobile AS mobile, c.Email AS email, c.Address AS address, c.Area AS area, "
            "c.RouteId AS route_id, r.RouteName AS route_name, c.PreferredContactMethod AS preferred_contact_method, "
            "c.IsActive AS is_active, c.Notes AS notes, c.CreatedAt AS created_at, c.UpdatedAt AS updated_at "
            "FROM dbo.Customers c LEFT JOIN dbo.DeliveryRoutes r ON r.RouteId=c.RouteId "
            + ("WHERE c.IsActive=? " if active is not None else "")
            + ("AND " if active is not None and search else "WHERE " if search and active is None else "")
            + ("(c.CustomerCode LIKE ? OR c.FullName LIKE ? OR c.Mobile LIKE ?) " if search else "")
            + "ORDER BY c.FullName",
            *(([active] if active is not None else [])
              + ([f"%{search}%", f"%{search}%", f"%{search}%"] if search else [])),
        )

    def get_customer(self, customer_id: int) -> dict[str, Any] | None:
        rows = self._fetch_all(
            "SELECT c.CustomerId AS id, c.CustomerCode AS customer_code, c.FullName AS full_name, "
            "c.Mobile AS mobile, c.Email AS email, c.Address AS address, c.Area AS area, "
            "c.RouteId AS route_id, r.RouteName AS route_name, c.PreferredContactMethod AS preferred_contact_method, "
            "c.IsActive AS is_active, c.Notes AS notes, c.CreatedAt AS created_at, c.UpdatedAt AS updated_at "
            "FROM dbo.Customers c LEFT JOIN dbo.DeliveryRoutes r ON r.RouteId=c.RouteId WHERE c.CustomerId=?",
            customer_id,
        )
        return rows[0] if rows else None

    def create_customer(self, item: dict[str, Any], actor: str) -> dict[str, Any]:
        row = self._execute(
            "INSERT INTO dbo.Customers(CustomerCode,FullName,Mobile,Email,Address,Area,RouteId,PreferredContactMethod,Notes) "
            "OUTPUT inserted.CustomerId AS id, inserted.CustomerCode AS customer_code, inserted.FullName AS full_name "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            item["customer_code"], item["full_name"], item["mobile"], item.get("email"), item["address"],
            item.get("area"), item.get("route_id"), item["preferred_contact_method"], item.get("notes"),
        )
        self.audit(actor, "CREATE", "Customer", row["id"], None, row)
        return row

    def update_customer(self, customer_id: int, item: dict[str, Any], actor: str) -> dict[str, Any] | None:
        before = self.get_customer(customer_id)
        if before is None:
            return None
        fields = {
            "full_name": "FullName", "mobile": "Mobile", "email": "Email", "address": "Address",
            "area": "Area", "route_id": "RouteId", "preferred_contact_method": "PreferredContactMethod",
            "notes": "Notes",
        }
        updates = [(fields[key], value) for key, value in item.items() if key in fields]
        if updates:
            assignments = ", ".join(f"{column}=?" for column, _ in updates)
            self._execute(
                f"UPDATE dbo.Customers SET {assignments}, UpdatedAt=SYSUTCDATETIME() WHERE CustomerId=?",
                *(value for _, value in updates), customer_id,
            )
        after = self.get_customer(customer_id)
        self.audit(actor, "UPDATE", "Customer", customer_id, before, after)
        return after

    def deactivate_customer(self, customer_id: int, actor: str) -> dict[str, Any] | None:
        before = self.get_customer(customer_id)
        if before is None:
            return None
        self._execute("UPDATE dbo.Customers SET IsActive=0, UpdatedAt=SYSUTCDATETIME() WHERE CustomerId=?", customer_id)
        after = self.get_customer(customer_id)
        self.audit(actor, "DEACTIVATE", "Customer", customer_id, before, after)
        return after

    def list_products(self, active: bool | None = None) -> list[dict[str, Any]]:
        return self._fetch_all(
            "SELECT p.MilkProductId AS id, p.ProductCode AS product_code, p.ProductName AS product_name, "
            "p.UnitOfMeasure AS unit_of_measure, p.IsActive AS is_active, p.CreatedAt AS created_at, p.UpdatedAt AS updated_at, "
            "price.PricePerUnit AS current_price, price.EffectiveFrom AS price_effective_from "
            "FROM dbo.MilkProducts p OUTER APPLY (SELECT TOP (1) PricePerUnit, EffectiveFrom FROM dbo.ProductPrices "
            "WHERE MilkProductId=p.MilkProductId AND EffectiveFrom<=CONVERT(date,SYSUTCDATETIME()) "
            "AND (EffectiveTo IS NULL OR EffectiveTo>=CONVERT(date,SYSUTCDATETIME())) ORDER BY EffectiveFrom DESC) price "
            + ("WHERE p.IsActive=? " if active is not None else "")
            + "ORDER BY p.ProductName",
            *(([active] if active is not None else [])),
        )

    def get_product(self, product_id: int) -> dict[str, Any] | None:
        rows = self._fetch_all(
            "SELECT p.MilkProductId AS id,p.ProductCode AS product_code,p.ProductName AS product_name,"
            "p.UnitOfMeasure AS unit_of_measure,p.IsActive AS is_active,p.CreatedAt AS created_at,"
            "p.UpdatedAt AS updated_at,price.PricePerUnit AS current_price,"
            "price.EffectiveFrom AS price_effective_from FROM dbo.MilkProducts p OUTER APPLY ("
            "SELECT TOP(1) PricePerUnit,EffectiveFrom FROM dbo.ProductPrices WHERE MilkProductId=p.MilkProductId "
            "AND EffectiveFrom<=CONVERT(date,SYSUTCDATETIME()) "
            "AND (EffectiveTo IS NULL OR EffectiveTo>=CONVERT(date,SYSUTCDATETIME())) "
            "ORDER BY EffectiveFrom DESC) price WHERE p.MilkProductId=?", product_id,
        )
        return rows[0] if rows else None

    def create_product(self, item: dict[str, Any], actor: str) -> dict[str, Any]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "INSERT INTO dbo.MilkProducts(ProductCode,ProductName,UnitOfMeasure) "
                "OUTPUT inserted.MilkProductId AS id, inserted.ProductCode AS product_code, inserted.ProductName AS product_name "
                "VALUES (?,?,?)", item["product_code"], item["product_name"], item["unit_of_measure"],
            )
            row = dict(zip((c[0] for c in cursor.description), cursor.fetchone()))
            if item.get("initial_price") is not None:
                cursor.execute(
                    "INSERT INTO dbo.ProductPrices(MilkProductId,PricePerUnit,EffectiveFrom) VALUES (?,?,?)",
                    row["id"], item["initial_price"], item["price_effective_from"],
                )
            cursor.execute(
                "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,AfterSummary) VALUES (?,?,?,?,?)",
                actor, "CREATE", "MilkProduct", str(row["id"]), f"code={row['product_code']}; name={row['product_name']}",
            )
            connection.commit()
            cursor.close()
            return row

    def update_product(self, product_id: int, updates: dict[str, Any], actor: str) -> dict[str, Any] | None:
        before = self.get_product(product_id)
        if before is None:
            return None
        columns = {"product_code": "ProductCode", "product_name": "ProductName",
                   "unit_of_measure": "UnitOfMeasure"}
        values = [(columns[key], value) for key, value in updates.items() if key in columns and value is not None]
        if not values:
            raise ValueError("Supply at least one product field to update")
        assignments = ",".join(f"{column}=?" for column, _ in values)
        params = [value for _, value in values] + [product_id]
        self._execute(
            f"UPDATE dbo.MilkProducts SET {assignments},UpdatedAt=SYSUTCDATETIME() WHERE MilkProductId=?",
            *params,
        )
        after = self.get_product(product_id)
        self.audit(actor, "UPDATE", "MilkProduct", product_id, before, after)
        return after

    def set_product_active(self, product_id: int, active: bool, actor: str) -> dict[str, Any] | None:
        before = self.get_product(product_id)
        if before is None:
            return None
        self._execute(
            "UPDATE dbo.MilkProducts SET IsActive=?, UpdatedAt=SYSUTCDATETIME() WHERE MilkProductId=?",
            active, product_id,
        )
        after = self.get_product(product_id)
        self.audit(actor, "ACTIVATE" if active else "DEACTIVATE", "MilkProduct", product_id, before, after)
        return after

    def list_prices(self, product_id: int) -> list[dict[str, Any]]:
        return self._fetch_all(
            "SELECT ProductPriceId AS id, MilkProductId AS product_id, PricePerUnit AS price_per_unit, "
            "EffectiveFrom AS effective_from, EffectiveTo AS effective_to FROM dbo.ProductPrices "
            "WHERE MilkProductId=? ORDER BY EffectiveFrom DESC", product_id,
        )

    def add_price(self, product_id: int, price: Decimal, effective_from: date, actor: str) -> dict[str, Any]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT ProductName FROM dbo.MilkProducts WHERE MilkProductId=?", product_id)
            product = cursor.fetchone()
            if not product:
                cursor.close()
                raise LookupError("Product not found")
            cursor.execute(
                "SELECT ProductPriceId,EffectiveFrom FROM dbo.ProductPrices WITH (UPDLOCK,HOLDLOCK) "
                "WHERE MilkProductId=? AND (EffectiveTo IS NULL OR EffectiveTo>=?) ORDER BY EffectiveFrom",
                product_id, effective_from,
            )
            overlapping = cursor.fetchall()
            for existing in overlapping:
                if existing[1] >= effective_from:
                    cursor.close()
                    raise ValueError("Price effective dates cannot overlap or go backwards")
            cursor.execute(
                "UPDATE dbo.ProductPrices SET EffectiveTo=DATEADD(day,-1,?) "
                "WHERE MilkProductId=? AND EffectiveTo IS NULL AND EffectiveFrom<?",
                effective_from, product_id, effective_from,
            )
            cursor.execute(
                "INSERT INTO dbo.ProductPrices(MilkProductId,PricePerUnit,EffectiveFrom) "
                "OUTPUT inserted.ProductPriceId AS id, inserted.MilkProductId AS product_id, "
                "inserted.PricePerUnit AS price_per_unit, inserted.EffectiveFrom AS effective_from, "
                "inserted.EffectiveTo AS effective_to VALUES (?,?,?)",
                product_id, price, effective_from,
            )
            row = dict(zip((c[0] for c in cursor.description), cursor.fetchone()))
            cursor.execute(
                "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,AfterSummary) VALUES (?,?,?,?,?)",
                actor, "PRICE_SET", "ProductPrice", str(row["id"]),
                f"product={product[0]}; price={price}; from={effective_from.isoformat()}",
            )
            connection.commit()
            cursor.close()
            return row

    def list_routes(self, active: bool | None = None) -> list[dict[str, Any]]:
        return self._fetch_all(
            "SELECT RouteId AS id, RouteName AS route_name, Description AS description, IsActive AS is_active "
            "FROM dbo.DeliveryRoutes " + ("WHERE IsActive=? " if active is not None else "") + "ORDER BY RouteName",
            *(([active] if active is not None else [])),
        )

    def create_route(self, item: dict[str, Any], actor: str) -> dict[str, Any]:
        row = self._execute(
            "INSERT INTO dbo.DeliveryRoutes(RouteName,Description) OUTPUT inserted.RouteId AS id, "
            "inserted.RouteName AS route_name, inserted.Description AS description VALUES (?,?)",
            item["route_name"], item.get("description"),
        )
        self.audit(actor, "CREATE", "DeliveryRoute", row["id"], None, row)
        return row

    def audit(self, actor: str, action: str, entity: str, entity_id: int, before: Any, after: Any) -> None:
        self._execute(
            "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,BeforeSummary,AfterSummary) "
            "VALUES (?,?,?,?,?,?)",
            actor, action, entity, str(entity_id), _safe_audit_value(before), _safe_audit_value(after),
        )

