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
from retail_store.composable_query import (
    SUPPORTED_DIMENSIONS,
    SUPPORTED_METRICS,
    query_store_metrics as analytics_query_store_metrics,
)
from retail_store.services import (
    create_order,
    create_promotion as service_create_promotion,
    process_return as service_process_return,
    receive_purchase_order as service_receive_purchase_order,
    reorder_low_stock as service_reorder_low_stock,
)
from retail_store.queries import (
    cancel_purchase_order,
    customer_report,
    inventory_report,
    order_report,
    order_details,
    purchase_order_report,
    recommend_supplier,
    sales_report,
    price_quote,
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
            last_payment_method=data["payment_method"],
            last_order_date=data["order_date"],
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
        return _success(
            data,
            last_promotion_id=data["promo_id"],
            last_action="create_promotion",
        )
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
            updates["last_purchase_order_supplier"] = data[-1]["supplier_name"]
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
            last_purchase_order_supplier=data["supplier_name"],
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


def _query_store_metrics(
    connection: sqlite3.Connection, **arguments: Any
) -> ToolResult:
    try:
        data = analytics_query_store_metrics(connection, **arguments)
        return _success(data, last_action="query_store_metrics")
    except (ValueError, TypeError, sqlite3.Error) as exc:
        return _failure("query_store_metrics", exc)


def _query(connection: sqlite3.Connection, action: str, function: Callable[..., Any], **arguments: Any) -> ToolResult:
    try:
        return _success(function(connection, **arguments), last_action=action)
    except (ValueError, TypeError, sqlite3.Error) as exc:
        return _failure(action, exc)


def _inventory_report(connection: sqlite3.Connection, **arguments: Any) -> ToolResult:
    return _query(connection, "inventory_report", inventory_report, **arguments)


def _order_details(connection: sqlite3.Connection, **arguments: Any) -> ToolResult:
    return _query(connection, "order_details", order_details, **arguments)


def _sales_report(connection: sqlite3.Connection, **arguments: Any) -> ToolResult:
    return _query(connection, "sales_report", sales_report, **arguments)


def _customer_report(connection: sqlite3.Connection, **arguments: Any) -> ToolResult:
    return _query(connection, "customer_report", customer_report, **arguments)


def _order_report(connection: sqlite3.Connection, **arguments: Any) -> ToolResult:
    return _query(connection, "order_report", order_report, **arguments)


def _recommend_supplier(connection: sqlite3.Connection, **arguments: Any) -> ToolResult:
    return _query(connection, "recommend_supplier", recommend_supplier, **arguments)


def _cancel_purchase_order(connection: sqlite3.Connection, **arguments: Any) -> ToolResult:
    return _query(connection, "cancel_purchase_order", cancel_purchase_order, **arguments)


def _price_quote(connection: sqlite3.Connection, **arguments: Any) -> ToolResult:
    return _query(connection, "price_quote", price_quote, **arguments)


def _purchase_order_report(
    connection: sqlite3.Connection, **arguments: Any
) -> ToolResult:
    return _query(
        connection, "purchase_order_report", purchase_order_report, **arguments
    )


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
        "inclusive date window. Product scope_ref values are P-TEE "
        "(Classic Tee), P-HOOD (Pullover Hoodie), P-TOTE (Canvas Tote), "
        "P-MUG (Ceramic Mug), or P-SOCK (Wool Socks). Category scope_ref "
        "values are apparel or goods. Ask for missing dates or percent; do "
        "not invent 0% or same-day promotions for underspecified requests."
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

QUERY_STORE_METRICS = Tool(
    name="query_store_metrics",
    description=(
        "Composable sales and store metrics query. Use this for flexible "
        "questions about revenue, net revenue, spend, units, refunds, margin, "
        "cost, orders, customers, products, SKUs, variants, categories, dates, "
        "and payment methods."
    ),
    parameters={
        "type": "object",
        "properties": {
            "metrics": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "enum": sorted(SUPPORTED_METRICS)},
            },
            "group_by": {
                "type": ["array", "null"],
                "items": {"type": "string", "enum": sorted(SUPPORTED_DIMENSIONS)},
            },
            "filters": {
                "type": ["object", "null"],
                "properties": {
                    name: {"type": ["string", "integer"]}
                    for name in (
                        "product_id",
                        "product_name",
                        "category",
                        "sku",
                        "color",
                        "size",
                        "customer_id",
                        "customer_name",
                        "customer_type",
                        "payment_method",
                        "order_id",
                    )
                },
                "additionalProperties": False,
            },
            "date_range": {
                "type": ["object", "null"],
                "properties": {
                    "start_date": DATE_SCHEMA,
                    "end_date": DATE_SCHEMA,
                },
                "required": ["start_date", "end_date"],
                "additionalProperties": False,
            },
            "sort_by": {"type": ["string", "null"]},
            "sort_dir": {
                "type": "string",
                "enum": ["asc", "desc"],
                "default": "desc",
            },
            "limit": {"type": ["integer", "null"], "minimum": 1},
            "include_totals": {"type": "boolean", "default": False},
        },
        "required": ["metrics"],
        "additionalProperties": False,
    },
    callable=_query_store_metrics,
)

INVENTORY_REPORT = Tool(
    name="inventory_report",
    description="Read inventory levels by product or SKU, including reorder points and days of cover. Never use a mutating tool for an inventory question.",
    parameters={"type": "object", "properties": {
        "product_description": {"type": ["string", "null"]},
        "sku": {"type": ["string", "null"]},
    }, "additionalProperties": False},
    callable=_inventory_report,
)

ORDER_DETAILS = Tool(
    name="order_details",
    description="Read an existing order, customer, receipt lines, quantities, paid unit prices, and total. This tool never returns merchandise.",
    parameters={"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"], "additionalProperties": False},
    callable=_order_details,
)

SALES_REPORT = Tool(
    name="sales_report",
    description="Read revenue, refunds, net revenue, and units sold by product for a period, optionally filtered to one product.",
    parameters={"type": "object", "properties": {
        "start_date": {**DATE_SCHEMA, "default": "2026-05-01"},
        "end_date": {**DATE_SCHEMA, "default": "2026-05-31"},
        "product_description": {"type": ["string", "null"]},
        "group_by": {"type": "string", "enum": ["product", "category"], "default": "product"},
        "only_with_refunds": {"type": "boolean", "default": False},
        "only_with_returns": {"type": "boolean", "default": False},
    }, "additionalProperties": False},
    callable=_sales_report,
)

CUSTOMER_REPORT = Tool(
    name="customer_report",
    description=(
        "Read customers and customer revenue/order counts. Use this for all "
        "customers, customer spend, and top customers by revenue. Set "
        "start_date/end_date for period spend; include_walk_ins adds walk-in "
        "as a pseudo-customer."
    ),
    parameters={
        "type": "object",
        "properties": {
            "start_date": {**DATE_SCHEMA, "default": "2026-05-01"},
            "end_date": {**DATE_SCHEMA, "default": "2026-05-31"},
            "customer_name": {"type": ["string", "null"]},
            "include_walk_ins": {"type": "boolean", "default": False},
            "sort_by_revenue": {"type": "boolean", "default": False},
            "limit": {"type": ["integer", "null"], "minimum": 1},
        },
        "additionalProperties": False,
    },
    callable=_customer_report,
)

ORDER_REPORT = Tool(
    name="order_report",
    description=(
        "Read orders with customer/walk-in status, payment method, discount, "
        "and total paid. Use this for walk-in order counts, cash versus card "
        "revenue, and sales with order-level discounts. For cash versus card "
        "revenue, set group_by to payment_method so the tool returns the "
        "aggregate totals."
    ),
    parameters={
        "type": "object",
        "properties": {
            "start_date": {**DATE_SCHEMA, "default": "2026-05-01"},
            "end_date": {**DATE_SCHEMA, "default": "2026-05-31"},
            "customer_name": {"type": ["string", "null"]},
            "walk_in": {"type": ["boolean", "null"]},
            "payment_method": {"type": ["string", "null"], "enum": ["cash", "card", None]},
            "order_discount_only": {"type": "boolean", "default": False},
            "group_by": {"type": "string", "enum": ["order", "payment_method"], "default": "order"},
        },
        "additionalProperties": False,
    },
    callable=_order_report,
)

RECOMMEND_SUPPLIER = Tool(
    name="recommend_supplier",
    description="Read and rank suppliers for a product without creating a purchase order.",
    parameters={"type": "object", "properties": {"product_description": {"type": "string"}}, "required": ["product_description"], "additionalProperties": False},
    callable=_recommend_supplier,
)

CANCEL_PURCHASE_ORDER = Tool(
    name="cancel_purchase_order",
    description="Cancel an open or partially received purchase order.",
    parameters={"type": "object", "properties": {"po_id": {"type": "string"}}, "required": ["po_id"], "additionalProperties": False},
    callable=_cancel_purchase_order,
)

PRICE_QUOTE = Tool(
    name="price_quote",
    description="Read the effective unit price for a product on a date without creating a sale.",
    parameters={"type": "object", "properties": {
        "product_description": {"type": "string"},
        "price_date": {**DATE_SCHEMA, "default": "2026-06-19"},
        "color": {"type": ["string", "null"]},
        "size": {"type": ["string", "null"]},
    }, "required": ["product_description"], "additionalProperties": False},
    callable=_price_quote,
)

PURCHASE_ORDER_REPORT = Tool(
    name="purchase_order_report",
    description=(
        "Read purchase orders with product, supplier, quantities, status, "
        "creation date, and lead time."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    callable=_purchase_order_report,
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
        QUERY_STORE_METRICS,
        INVENTORY_REPORT,
        ORDER_DETAILS,
        SALES_REPORT,
        CUSTOMER_REPORT,
        ORDER_REPORT,
        RECOMMEND_SUPPLIER,
        CANCEL_PURCHASE_ORDER,
        PRICE_QUOTE,
        PURCHASE_ORDER_REPORT,
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
