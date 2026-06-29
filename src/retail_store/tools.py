from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

from retail_store.analytics import (
    get_stockout_risk as analytics_get_stockout_risk,
)
from retail_store.analytics import (
    top_products_by_profit_margin as analytics_top_products_by_profit_margin,
)
from retail_store.services import (
    create_order,
    create_promotion as service_create_promotion,
    process_return as service_process_return,
    receive_purchase_order as service_receive_purchase_order,
    reorder_low_stock as service_reorder_low_stock,
)


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: Any | None
    error: str | None
    session_updates: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "session_updates": self.session_updates,
        }


ToolCallable = Callable[..., ToolResult]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    callable: ToolCallable

    def invoke(
        self, connection: sqlite3.Connection, **arguments: Any
    ) -> ToolResult:
        return self.callable(connection, **arguments)


def _success(data: Any, **session_updates: Any) -> ToolResult:
    return ToolResult(
        ok=True,
        data=data,
        error=None,
        session_updates=session_updates,
    )


def _failure(action: str, exc: Exception) -> ToolResult:
    return ToolResult(
        ok=False,
        data=None,
        error=str(exc) or exc.__class__.__name__,
        session_updates={"last_action": action},
    )


def _ring_up_order(connection: sqlite3.Connection, **arguments: Any) -> ToolResult:
    try:
        data = create_order(connection, **arguments)
        input_items = arguments.get("items", [])
        return _success(
            data,
            last_order_id=data["order_id"],
            last_customer_name=arguments.get("customer_name") or "walk-in",
            last_items=input_items,
            last_skus=[line["sku"] for line in data["line_items"]],
            last_action="ring_up_order",
        )
    except (ValueError, TypeError, sqlite3.Error) as exc:
        return _failure("ring_up_order", exc)


def _process_return(connection: sqlite3.Connection, **arguments: Any) -> ToolResult:
    try:
        data = service_process_return(connection, **arguments)
        return _success(
            data,
            last_order_id=data["order_id"],
            last_return_id=data["return_id"],
            last_skus=[data["sku"]],
            last_action="process_return",
        )
    except (ValueError, TypeError, sqlite3.Error) as exc:
        return _failure("process_return", exc)


def _create_promotion(
    connection: sqlite3.Connection, **arguments: Any
) -> ToolResult:
    try:
        data = service_create_promotion(connection, **arguments)
        return _success(data, last_action="create_promotion")
    except (ValueError, TypeError, sqlite3.Error) as exc:
        return _failure("create_promotion", exc)


def _reorder_low_stock(
    connection: sqlite3.Connection, **arguments: Any
) -> ToolResult:
    try:
        data = service_reorder_low_stock(connection, **arguments)
        updates: dict[str, Any] = {"last_action": "reorder_low_stock"}
        if data:
            updates["last_purchase_order_id"] = data[-1]["po_id"]
        return _success(data, **updates)
    except (ValueError, TypeError, sqlite3.Error) as exc:
        return _failure("reorder_low_stock", exc)


def _receive_purchase_order(
    connection: sqlite3.Connection, **arguments: Any
) -> ToolResult:
    try:
        data = service_receive_purchase_order(connection, **arguments)
        return _success(
            data,
            last_purchase_order_id=data["po_id"],
            last_skus=[data["sku"]],
            last_action="receive_purchase_order",
        )
    except (ValueError, TypeError, sqlite3.Error) as exc:
        return _failure("receive_purchase_order", exc)


def _top_products_by_profit_margin(
    connection: sqlite3.Connection, **arguments: Any
) -> ToolResult:
    try:
        data = analytics_top_products_by_profit_margin(connection, **arguments)
        return _success(data, last_action="top_products_by_profit_margin")
    except (ValueError, TypeError, sqlite3.Error) as exc:
        return _failure("top_products_by_profit_margin", exc)


def _get_stockout_risk(
    connection: sqlite3.Connection, **arguments: Any
) -> ToolResult:
    try:
        data = analytics_get_stockout_risk(connection, **arguments)
        return _success(data, last_action="get_stockout_risk")
    except (ValueError, TypeError, sqlite3.Error) as exc:
        return _failure("get_stockout_risk", exc)


DATE_SCHEMA = {"type": "string", "format": "date"}

RING_UP_ORDER = Tool(
    name="ring_up_order",
    description=(
        "Create a retail sale, applying deterministic promotions and inventory "
        "checks. Prices and totals are calculated by the service layer."
    ),
    parameters={
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "product_description": {"type": "string"},
                        "quantity": {"type": "integer", "minimum": 1},
                        "color": {"type": "string"},
                        "size": {"type": "string"},
                    },
                    "required": ["product_description", "quantity"],
                    "additionalProperties": False,
                },
            },
            "customer_name": {"type": ["string", "null"]},
            "payment_method": {
                "type": "string",
                "enum": ["cash", "card"],
                "default": "card",
            },
            "order_date": {
                **DATE_SCHEMA,
                "default": "2026-06-19",
            },
            "order_discount_pct": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "default": 0,
            },
        },
        "required": ["items"],
        "additionalProperties": False,
    },
    callable=_ring_up_order,
)

PROCESS_RETURN = Tool(
    name="process_return",
    description=(
        "Return units from an original order at the price actually paid. Good "
        "items are restocked; damaged items are not."
    ),
    parameters={
        "type": "object",
        "properties": {
            "order_id": {"type": "string"},
            "product_description": {"type": ["string", "null"]},
            "sku": {"type": ["string", "null"]},
            "color": {"type": ["string", "null"]},
            "size": {"type": ["string", "null"]},
            "quantity": {"type": "integer", "minimum": 1, "default": 1},
            "condition": {
                "type": "string",
                "enum": ["good", "damaged"],
                "default": "good",
            },
            "return_date": {
                **DATE_SCHEMA,
                "default": "2026-06-19",
            },
        },
        "required": ["order_id"],
        "additionalProperties": False,
    },
    callable=_process_return,
)

CREATE_PROMOTION = Tool(
    name="create_promotion",
    description=(
        "Create a product- or category-scoped percentage promotion with an "
        "inclusive date window."
    ),
    parameters={
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "percent_off": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
            },
            "scope_type": {
                "type": "string",
                "enum": ["product", "category"],
            },
            "scope_ref": {"type": "string"},
            "start_date": DATE_SCHEMA,
            "end_date": DATE_SCHEMA,
        },
        "required": [
            "description",
            "percent_off",
            "scope_type",
            "scope_ref",
            "start_date",
            "end_date",
        ],
        "additionalProperties": False,
    },
    callable=_create_promotion,
)

REORDER_LOW_STOCK = Tool(
    name="reorder_low_stock",
    description=(
        "Create purchase orders for stock at or below reorder points, choosing "
        "the lowest-cost supplier that can deliver within ten days."
    ),
    parameters={
        "type": "object",
        "properties": {
            "created_date": {
                **DATE_SCHEMA,
                "default": "2026-06-19",
            }
        },
        "additionalProperties": False,
    },
    callable=_reorder_low_stock,
)

RECEIVE_PURCHASE_ORDER = Tool(
    name="receive_purchase_order",
    description=(
        "Receive inventory against an open purchase order, or create the "
        "stated open order when none exists."
    ),
    parameters={
        "type": "object",
        "properties": {
            "product_description": {"type": "string"},
            "supplier_name": {"type": "string"},
            "quantity_ordered": {"type": "integer", "minimum": 1},
            "quantity_received": {"type": "integer", "minimum": 0},
            "received_date": {
                **DATE_SCHEMA,
                "default": "2026-06-19",
            },
            "color": {"type": ["string", "null"]},
            "size": {"type": ["string", "null"]},
            "sku": {"type": ["string", "null"]},
        },
        "required": [
            "product_description",
            "supplier_name",
            "quantity_ordered",
            "quantity_received",
        ],
        "additionalProperties": False,
    },
    callable=_receive_purchase_order,
)

TOP_PRODUCTS_BY_PROFIT_MARGIN = Tool(
    name="top_products_by_profit_margin",
    description=(
        "Rank products by deterministic profit margin using paid revenue, "
        "period refunds, retained units, and Northwind costs."
    ),
    parameters={
        "type": "object",
        "properties": {
            "start_date": {
                **DATE_SCHEMA,
                "default": "2026-05-01",
            },
            "end_date": {
                **DATE_SCHEMA,
                "default": "2026-05-31",
            },
            "limit": {"type": "integer", "minimum": 1, "default": 5},
        },
        "additionalProperties": False,
    },
    callable=_top_products_by_profit_margin,
)

GET_STOCKOUT_RISK = Tool(
    name="get_stockout_risk",
    description=(
        "Find products at or below reorder points or with fewer than fourteen "
        "days of cover, using May sales velocity."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    callable=_get_stockout_risk,
)

TOOLS = {
    tool.name: tool
    for tool in (
        RING_UP_ORDER,
        PROCESS_RETURN,
        CREATE_PROMOTION,
        REORDER_LOW_STOCK,
        RECEIVE_PURCHASE_ORDER,
        TOP_PRODUCTS_BY_PROFIT_MARGIN,
        GET_STOCKOUT_RISK,
    )
}


def invoke_tool(
    name: str, connection: sqlite3.Connection, arguments: dict[str, Any] | None = None
) -> ToolResult:
    tool = TOOLS.get(name)
    if tool is None:
        return ToolResult(
            ok=False,
            data=None,
            error=f"unknown tool: {name}",
            session_updates={},
        )
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return ToolResult(
            ok=False,
            data=None,
            error="tool arguments must be an object",
            session_updates={"last_action": name},
        )
    return tool.invoke(connection, **arguments)

