from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from retail_store.money import apply_percent_discount_cents, cents_to_usd


MONEY_METRICS = {
    "revenue_gross",
    "revenue_net",
    "refunds",
    "cost",
    "margin",
    "avg_order_value",
}
COUNT_METRICS = {
    "units_sold",
    "units_kept",
    "refund_quantity",
    "order_count",
}
SUPPORTED_METRICS = MONEY_METRICS | COUNT_METRICS
SUPPORTED_DIMENSIONS = {
    "product",
    "product_id",
    "product_name",
    "category",
    "sku",
    "variant",
    "color",
    "size",
    "customer",
    "customer_id",
    "customer_name",
    "customer_type",
    "payment_method",
    "date",
    "month",
    "order_id",
}

FILTER_SQL = {
    "product_id": "pv.product_id = ?",
    "product_name": "lower(p.name) = lower(?)",
    "category": "lower(p.category) = lower(?)",
    "sku": "lower(pv.sku) = lower(?)",
    "color": "lower(COALESCE(pv.color, '')) = lower(?)",
    "size": "lower(COALESCE(pv.size, '')) = lower(?)",
    "customer_id": "o.customer_id = ?",
    "customer_name": "lower(COALESCE(c.name, 'Walk-in')) = lower(?)",
    "customer_type": (
        "CASE WHEN o.customer_id IS NULL THEN 'walk-in' ELSE 'customer' END = ?"
    ),
    "payment_method": "lower(o.payment_method) = lower(?)",
    "order_id": "o.order_id = ?",
}


def _validate_names(values: Iterable[str], allowed: set[str], label: str) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise ValueError(f"{label} must be a list")
    result = list(values)
    if not result:
        raise ValueError(f"{label} must not be empty")
    for value in result:
        if not isinstance(value, str) or value not in allowed:
            raise ValueError(f"unknown {label[:-1] if label.endswith('s') else label}: {value!r}")
    if len(set(result)) != len(result):
        raise ValueError(f"{label} must not contain duplicates")
    return result


def _normalize_date_range(
    date_range: dict[str, str] | tuple[str, str] | list[str] | None,
) -> tuple[str | None, str | None, dict[str, str] | None]:
    if date_range is None:
        return None, None, None
    if isinstance(date_range, dict):
        if set(date_range) != {"start_date", "end_date"}:
            raise ValueError("date_range must contain start_date and end_date")
        start_date = date_range["start_date"]
        end_date = date_range["end_date"]
    elif isinstance(date_range, (tuple, list)) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        raise ValueError("date_range must be a dict or two-item tuple")
    if not isinstance(start_date, str) or not isinstance(end_date, str):
        raise ValueError("date_range dates must use YYYY-MM-DD")
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("date_range dates must use YYYY-MM-DD") from exc
    if start.isoformat() != start_date or end.isoformat() != end_date:
        raise ValueError("date_range dates must use YYYY-MM-DD")
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    return start_date, end_date, {
        "start_date": start_date,
        "end_date": end_date,
    }


def _dimension_value(row: sqlite3.Row, dimension: str, event_date: str) -> Any:
    if dimension in {"product", "product_name"}:
        return row["product_name"]
    if dimension == "customer":
        return row["customer_name"] or "Walk-in"
    if dimension == "customer_name":
        return row["customer_name"] or "Walk-in"
    if dimension == "customer_type":
        return "walk-in" if row["customer_id"] is None else "customer"
    if dimension == "variant":
        parts = [row["product_name"]]
        parts.extend(
            value for value in (row["color"], row["size"]) if value is not None
        )
        return " / ".join(parts)
    if dimension == "date":
        return event_date
    if dimension == "month":
        return event_date[:7]
    return row[dimension]


def _base_sql(table: str, date_column: str) -> str:
    return f"""
        SELECT o.order_id, o.order_date, o.customer_id, c.name AS customer_name,
               o.payment_method, ol.line_no, ol.quantity AS sold_quantity,
               ol.unit_price_cents, o.order_discount_pct,
               pv.sku, pv.product_id, pv.color, pv.size,
               p.name AS product_name, p.category,
               sc.unit_cost_cents,
               {date_column} AS event_date
               {", r.quantity AS return_quantity, r.condition, r.refund_amount_cents" if table == "returns" else ""}
        FROM {table} AS {"r" if table == "returns" else "ol"}
        {"JOIN order_lines AS ol ON ol.order_id = r.order_id AND ol.line_no = r.order_line_no AND ol.sku = r.sku" if table == "returns" else ""}
        JOIN orders AS o ON o.order_id = ol.order_id
        JOIN product_variants AS pv ON pv.sku = ol.sku
        JOIN products AS p ON p.product_id = pv.product_id
        LEFT JOIN customers AS c ON c.customer_id = o.customer_id
        LEFT JOIN supplier_catalog AS sc
          ON sc.product_id = p.product_id
         AND sc.supplier_id = (
             SELECT supplier_id FROM suppliers WHERE name = 'Northwind Supply'
         )
    """


def _fetch_events(
    connection: sqlite3.Connection,
    table: str,
    filters: dict[str, Any],
    start_date: str | None,
    end_date: str | None,
) -> list[sqlite3.Row]:
    date_column = "r.return_date" if table == "returns" else "o.order_date"
    clauses: list[str] = []
    parameters: list[Any] = []
    if start_date is not None:
        clauses.append(f"{date_column} BETWEEN ? AND ?")
        parameters.extend((start_date, end_date))
    for name, value in filters.items():
        clauses.append(FILTER_SQL[name])
        parameters.append(value)
    sql = _base_sql(table, date_column)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY event_date, o.order_id, ol.line_no"
    return connection.execute(sql, parameters).fetchall()


def query_store_metrics(
    connection: sqlite3.Connection,
    metrics: list[str],
    group_by: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    date_range: dict[str, str] | tuple[str, str] | None = None,
    sort_by: str | None = None,
    sort_dir: str = "desc",
    limit: int | None = None,
    include_totals: bool = False,
) -> dict[str, Any]:
    """Run a safe, composable store-metrics query over whitelisted fields."""
    metric_names = _validate_names(metrics, SUPPORTED_METRICS, "metrics")
    dimensions = (
        [] if group_by is None
        else _validate_names(group_by, SUPPORTED_DIMENSIONS, "dimensions")
    )
    if filters is None:
        filter_values: dict[str, Any] = {}
    elif not isinstance(filters, dict):
        raise ValueError("filters must be an object")
    else:
        filter_values = dict(filters)
    for name, value in filter_values.items():
        if name not in FILTER_SQL:
            raise ValueError(f"unknown filter: {name!r}")
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise ValueError(f"filter {name!r} must be a string or integer")
    if "customer_type" in filter_values:
        customer_type = str(filter_values["customer_type"]).casefold()
        if customer_type not in {"customer", "walk-in"}:
            raise ValueError("customer_type must be 'customer' or 'walk-in'")
        filter_values["customer_type"] = customer_type
    start_date, end_date, normalized_dates = _normalize_date_range(date_range)
    if sort_by is not None and sort_by not in set(metric_names) | set(dimensions):
        raise ValueError(f"invalid sort_by: {sort_by!r}")
    if sort_dir not in {"asc", "desc"}:
        raise ValueError("sort_dir must be 'asc' or 'desc'")
    if limit is not None and (
        isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0
    ):
        raise ValueError("limit must be a positive integer")
    if not isinstance(include_totals, bool):
        raise ValueError("include_totals must be a boolean")

    groups: dict[tuple[Any, ...], dict[str, Any]] = defaultdict(
        lambda: {
            "revenue_gross_cents": 0,
            "refunds_cents": 0,
            "units_sold": 0,
            "good_units_returned": 0,
            "refund_quantity": 0,
            "cost_cents": 0,
            "order_ids": set(),
        }
    )
    sales = _fetch_events(
        connection, "order_lines", filter_values, start_date, end_date
    )
    for sale in sales:
        if sale["unit_cost_cents"] is None:
            raise ValueError(
                f"Northwind Supply cost missing for {sale['product_id']}"
            )
        key = tuple(
            _dimension_value(sale, dimension, sale["event_date"])
            for dimension in dimensions
        )
        group = groups[key]
        paid_per_unit = apply_percent_discount_cents(
            sale["unit_price_cents"], sale["order_discount_pct"]
        )
        group["revenue_gross_cents"] += paid_per_unit * sale["sold_quantity"]
        group["units_sold"] += sale["sold_quantity"]
        group["cost_cents"] += sale["unit_cost_cents"] * sale["sold_quantity"]
        group["order_ids"].add(sale["order_id"])

    returned_rows = _fetch_events(
        connection, "returns", filter_values, start_date, end_date
    )
    for returned in returned_rows:
        key = tuple(
            _dimension_value(returned, dimension, returned["event_date"])
            for dimension in dimensions
        )
        group = groups[key]
        group["refunds_cents"] += returned["refund_amount_cents"]
        group["refund_quantity"] += returned["return_quantity"]
        sale_in_period = (
            start_date is None
            or start_date <= returned["order_date"] <= end_date
        )
        if returned["condition"] == "good" and sale_in_period:
            group["good_units_returned"] += returned["return_quantity"]
            if returned["unit_cost_cents"] is None:
                raise ValueError(
                    f"Northwind Supply cost missing for {returned['product_id']}"
                )
            group["cost_cents"] -= (
                returned["unit_cost_cents"] * returned["return_quantity"]
            )

    def materialize(
        key: tuple[Any, ...], group: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, int]]:
        raw = {
            "revenue_gross": group["revenue_gross_cents"],
            "revenue_net": group["revenue_gross_cents"] - group["refunds_cents"],
            "units_sold": group["units_sold"],
            "units_kept": group["units_sold"] - group["good_units_returned"],
            "refunds": group["refunds_cents"],
            "refund_quantity": group["refund_quantity"],
            "cost": group["cost_cents"],
            "margin": (
                group["revenue_gross_cents"]
                - group["refunds_cents"]
                - group["cost_cents"]
            ),
            "order_count": len(group["order_ids"]),
            "avg_order_value": (
                0
                if not group["order_ids"]
                else int(
                    (
                        Decimal(
                            group["revenue_gross_cents"] - group["refunds_cents"]
                        )
                        / Decimal(len(group["order_ids"]))
                    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                )
            ),
        }
        row = dict(zip(dimensions, key))
        for metric in metric_names:
            row[metric] = (
                cents_to_usd(raw[metric])
                if metric in MONEY_METRICS
                else raw[metric]
            )
        return row, raw

    materialized = [materialize(key, value) for key, value in groups.items()]
    if sort_by is not None:
        index = dimensions.index(sort_by) if sort_by in dimensions else None

        def sort_value(item: tuple[dict[str, Any], dict[str, int]]) -> Any:
            row, raw = item
            if sort_by in raw:
                return raw[sort_by]
            value = item[0][dimensions[index]] if index is not None else ""
            return "" if value is None else str(value).casefold()

        materialized.sort(key=sort_value, reverse=sort_dir == "desc")
    else:
        materialized.sort(
            key=lambda item: tuple(
                "" if item[0][dimension] is None else str(item[0][dimension])
                for dimension in dimensions
            )
        )
    if limit is not None:
        materialized = materialized[:limit]

    result: dict[str, Any] = {
        "metrics": metric_names,
        "group_by": dimensions,
        "filters": filter_values,
        "date_range": normalized_dates,
        "rows": [row for row, _raw in materialized],
        "row_count": len(materialized),
    }
    if include_totals:
        total_group = {
            field: 0
            for field in (
                "revenue_gross_cents",
                "refunds_cents",
                "units_sold",
                "good_units_returned",
                "refund_quantity",
                "cost_cents",
            )
        }
        total_group["order_ids"] = set()
        for sale in sales:
            paid = apply_percent_discount_cents(
                sale["unit_price_cents"], sale["order_discount_pct"]
            )
            total_group["revenue_gross_cents"] += paid * sale["sold_quantity"]
            total_group["units_sold"] += sale["sold_quantity"]
            total_group["cost_cents"] += sale["unit_cost_cents"] * sale["sold_quantity"]
            total_group["order_ids"].add(sale["order_id"])
        for returned in returned_rows:
            total_group["refunds_cents"] += returned["refund_amount_cents"]
            total_group["refund_quantity"] += returned["return_quantity"]
            if returned["condition"] == "good" and (
                start_date is None
                or start_date <= returned["order_date"] <= end_date
            ):
                total_group["good_units_returned"] += returned["return_quantity"]
                total_group["cost_cents"] -= (
                    returned["unit_cost_cents"] * returned["return_quantity"]
                )
        result["totals"] = materialize((), total_group)[0]
    return result
