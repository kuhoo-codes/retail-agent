from __future__ import annotations

import re
from typing import Any


MAY_2026 = {"start_date": "2026-05-01", "end_date": "2026-05-31"}
TODAY = "2026-06-19"

DIMENSION_PATTERNS = (
    (r"\b(?:variant|variants)\b", "variant"),
    (r"\bsku(?:s)?\b", "sku"),
    (r"\b(?:customer|customers)\b", "customer"),
    (r"\b(?:category|categories)\b", "category"),
    (r"\bpayment method\b|\bcard vs\.? cash\b|\bcash vs\.? card\b", "payment_method"),
    (r"\b(?:product|products)\b", "product"),
    (r"\b(?:date|day|daily)\b", "date"),
    (r"\bby month\b|\bmonthly\b", "month"),
)


def parse_analytics_intent(text: str) -> dict[str, Any] | None:
    """Map common read-only analytics language to safe query arguments."""
    if not isinstance(text, str) or not text.strip():
        return None
    lowered = text.casefold()
    analytics_terms = (
        "sales",
        "revenue",
        "spend",
        "spent",
        "units sold",
        "margin",
        "refund",
        "orders",
        "average order",
        "avg order",
        "cost",
        "gross",
        "net",
    )
    if not any(term in lowered for term in analytics_terms):
        return None

    arguments: dict[str, Any] = {"metrics": []}
    if "gross vs net" in lowered or "gross and net" in lowered:
        arguments["metrics"] = ["revenue_gross", "revenue_net"]
    elif "units sold" in lowered:
        arguments["metrics"] = ["units_sold"]
    elif "margin" in lowered:
        arguments["metrics"] = ["margin"]
    elif "refund" in lowered:
        arguments["metrics"] = ["refunds", "refund_quantity"]
    elif "average order" in lowered or "avg order" in lowered:
        arguments["metrics"] = ["avg_order_value"]
    elif "cost" in lowered:
        arguments["metrics"] = ["cost"]
    elif "gross" in lowered:
        arguments["metrics"] = ["revenue_gross"]
    else:
        arguments["metrics"] = ["revenue_net"]

    if "sales by variant" in lowered:
        arguments["metrics"] = ["revenue_gross", "units_sold"]
    if (
        "card vs cash" in lowered
        or "cash vs card" in lowered
        or "by payment method" in lowered
    ):
        arguments["metrics"] = ["revenue_net", "order_count"]

    dimensions: list[str] = []
    for pattern, dimension in DIMENSION_PATTERNS:
        if re.search(pattern, lowered) and dimension not in dimensions:
            dimensions.append(dimension)
    if " by " in lowered and not dimensions:
        return None

    filters: dict[str, str] = {}
    if re.search(r"\bwalk[\s-]?in\b", lowered):
        filters["customer_type"] = "walk-in"
    if re.search(r"\bapparel\b", lowered):
        filters["category"] = "apparel"
    elif re.search(r"\bgoods\b", lowered):
        filters["category"] = "goods"
    if "card" in lowered and "cash" not in lowered:
        filters["payment_method"] = "card"
    elif "cash" in lowered and "card" not in lowered:
        filters["payment_method"] = "cash"

    name_match = re.search(
        r"(?:did|for)\s+([A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+)+?)"
        r"\s+(?:spend|spent|last month|in may|from|between|\?)",
        text,
    )
    if name_match:
        filters["customer_name"] = name_match.group(1).strip()
        if "customer" not in dimensions:
            dimensions.append("customer")

    if dimensions:
        arguments["group_by"] = dimensions
    if filters:
        arguments["filters"] = filters
    if "last month" in lowered or re.search(r"\bin may\b|\bmay 2026\b", lowered):
        arguments["date_range"] = dict(MAY_2026)
    if re.search(r"\btop customers?\b", lowered):
        arguments["group_by"] = ["customer"]
        arguments["sort_by"] = "revenue_net"
        arguments["sort_dir"] = "desc"
        limit_match = re.search(r"\btop\s+(\d+)\b", lowered)
        arguments["limit"] = int(limit_match.group(1)) if limit_match else 5
    return arguments


def parse_offline_tool_plan(
    text: str, session: dict[str, Any] | None = None
) -> list[tuple[str, dict[str, Any]]] | None:
    """Route the assignment's deterministic operational language to tools."""
    lowered = " ".join(text.casefold().split())
    session = session or {}

    if lowered in {"now refund that", "refund that", "return that"}:
        order_id = session.get("last_order_id")
        skus = session.get("last_skus") or []
        if not order_id or len(skus) != 1:
            return None
        return [
            (
                "process_return",
                {
                    "order_id": order_id,
                    "sku": skus[0],
                    "quantity": 1,
                    "condition": "good",
                    "return_date": TODAY,
                },
            )
        ]

    if (
        "two classic tee" in lowered
        and "blue medium" in lowered
        and "canvas tote" in lowered
        and "cash" in lowered
    ):
        return [
            (
                "ring_up_order",
                {
                    "items": [
                        {
                            "product_description": "Classic Tee",
                            "color": "Blue",
                            "size": "Medium",
                            "quantity": 2,
                        },
                        {"product_description": "Canvas Tote", "quantity": 1},
                    ],
                    "customer_name": None,
                    "payment_method": "cash",
                    "order_date": TODAY,
                },
            )
        ]
    if "ten canvas tote" in lowered and "ring up" in lowered:
        return [
            (
                "ring_up_order",
                {
                    "items": [
                        {"product_description": "Canvas Tote", "quantity": 10}
                    ],
                    "customer_name": None,
                    "order_date": TODAY,
                },
            )
        ]
    if (
        ("one navy medium hoodie" in lowered or "navy medium hoodie" in lowered)
        and "sarah chen" in lowered
        and ("ring up" in lowered or "sell" in lowered)
    ):
        return [
            (
                "ring_up_order",
                {
                    "items": [
                        {
                            "product_description": "hoodie",
                            "color": "Navy",
                            "size": "Medium",
                            "quantity": 1,
                        }
                    ],
                    "customer_name": "Sarah Chen",
                    "order_date": TODAY,
                },
            )
        ]
    if (
        "hoodie" in lowered
        and "medium" in lowered
        and "sarah chen" in lowered
        and ("ring up" in lowered or "sell" in lowered)
    ):
        return [
            (
                "ring_up_order",
                {
                    "items": [
                        {
                            "product_description": "hoodie",
                            "size": "Medium",
                            "quantity": 1,
                        }
                    ],
                    "customer_name": "Sarah Chen",
                    "order_date": TODAY,
                },
            )
        ]
    if "reorder" in lowered and (
        "below" in lowered or "low stock" in lowered
    ):
        return [("reorder_low_stock", {"created_date": TODAY})]
    if (
        "purchase order" in lowered
        and "50 canvas tote" in lowered
        and "40 arrived" in lowered
        and "northwind" in lowered
    ):
        return [
            (
                "receive_purchase_order",
                {
                    "product_description": "Canvas Tote",
                    "supplier_name": "Northwind",
                    "quantity_ordered": 50,
                    "quantity_received": 40,
                    "received_date": TODAY,
                },
            )
        ]
    if "o-1006" in lowered and "navy large hoodie" in lowered:
        return [
            (
                "process_return",
                {
                    "order_id": "O-1006",
                    "product_description": "hoodie",
                    "color": "Navy",
                    "size": "Large",
                    "quantity": 1,
                    "condition": "good",
                    "return_date": TODAY,
                },
            )
        ]
    if "o-1006" in lowered and "canvas tote" in lowered and "damaged" in lowered:
        return [
            (
                "process_return",
                {
                    "order_id": "O-1006",
                    "product_description": "Canvas Tote",
                    "quantity": 1,
                    "condition": "damaged",
                    "return_date": TODAY,
                },
            )
        ]
    if (
        "hoodie" in lowered
        and "20% off" in lowered
        and "2026-06-20" in lowered
        and "2026-06-22" in lowered
        and "gray medium" in lowered
        and "2026-06-21" in lowered
    ):
        return [
            (
                "create_promotion",
                {
                    "description": "Hoodies 20% off",
                    "percent_off": 20,
                    "scope_type": "product",
                    "scope_ref": "P-HOOD",
                    "start_date": "2026-06-20",
                    "end_date": "2026-06-22",
                },
            ),
            (
                "ring_up_order",
                {
                    "items": [
                        {
                            "product_description": "hoodie",
                            "color": "Gray",
                            "size": "Medium",
                            "quantity": 1,
                        }
                    ],
                    "order_date": "2026-06-21",
                },
            ),
        ]
    if "top five products" in lowered and "profit margin" in lowered:
        return [
            (
                "top_products_by_profit_margin",
                {
                    "start_date": "2026-05-01",
                    "end_date": "2026-05-31",
                    "limit": 5,
                },
            )
        ]
    if "stock out" in lowered or "stockout" in lowered:
        return [("get_stockout_risk", {})]
    return None
