"""Operational dashboard and filterable report/export endpoints."""
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response

from services.advanced_reporting_service import AdvancedReportingService

router = APIRouter(prefix="/api/v1/reports", tags=["reports and dashboard"])


def _json(value):
    return jsonable_encoder(value, custom_encoder={Decimal: lambda amount: format(amount, "f")})


def _service() -> AdvancedReportingService:
    return AdvancedReportingService()


def _safe_export_frame(rows: list[dict]):
    """Neutralize spreadsheet formula prefixes in user-controlled text fields."""
    frame = pd.DataFrame(rows)
    for column in frame.columns:
        frame[column] = frame[column].map(
            lambda value: "'" + value if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) else value
        )
    return frame


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=503, detail="Report could not be generated")


@router.get("/dashboard")
def dashboard(as_of: date | None = None):
    try:
        return _json(_service().dashboard(as_of))
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/{report_name}")
def report(
    report_name: Literal["availability", "demand", "sales", "collections", "routes", "customers",
                         "subscriptions", "deliveries", "ledger", "outstanding", "payments", "notifications"],
    from_date: date | None = None,
    through_date: date | None = None,
    customer_id: int | None = Query(default=None, ge=1),
    product_id: int | None = Query(default=None, ge=1),
    route_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None, max_length=40),
    active: bool | None = None,
    search: str | None = Query(default=None, max_length=100),
    output: Literal["json", "csv", "xlsx"] = Query(default="json", alias="format"),
):
    try:
        result = _service().report(report_name, from_date=from_date, through_date=through_date,
            customer_id=customer_id, product_id=product_id, route_id=route_id,
            status=status.upper() if status else None, active=active, search=search)
        if output == "json":
            return _json(result)
        rows = result.get("rows", [])
        frame = _safe_export_frame(rows)
        if output == "csv":
            content = frame.to_csv(index=False, lineterminator="\n").encode("utf-8-sig")
            media_type, extension = "text/csv; charset=utf-8", "csv"
        else:
            buffer = BytesIO()
            frame.to_excel(buffer, index=False, engine="openpyxl", sheet_name=report_name[:31])
            content = buffer.getvalue()
            media_type, extension = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
        return Response(content=content, media_type=media_type,
                        headers={"Content-Disposition": f'attachment; filename="{report_name}.{extension}"'})
    except Exception as exc:
        raise _error(exc) from exc
