from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date

from retail_store.money import apply_percent_discount_cents, cents_to_usd


def _validate_date_range(start_date: str, end_date: str) -> None:
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("dates must use YYYY-MM-DD") from exc
    if start.isoformat() != start_date or end.isoformat() != end_date:
        raise ValueError("dates must use YYYY-MM-DD")
    if start > end:
        raise ValueError("start_date must be on or before end_date")


def top_products_by_profit_margin(
    connection: sqlite3.Connection,
    start_date: str = "2026-05-01",
    end_date: str = "2026-05-31",
    limit: int = 5,
) -> list[dict[str, object]]:
    """Rank products by net margin for a period using the frozen cost rules."""
    _validate_date_range(start_date, end_date)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")

    products = connection.execute(
        "SELECT product_id, name FROM products ORDER BY product_id"
    ).fetchall()
    metrics: dict[str, dict[str, int]] = {
        row["product_id"]: {
            "units_sold": 0,
            "good_units_returned": 0,
            "revenue_cents": 0,
            "refund_cents": 0,
        }
        for row in products
    }

    sales = connection.execute(
        """SELECT pv.product_id, ol.quantity, ol.unit_price_cents,
                  o.order_discount_pct
           FROM order_lines AS ol
           JOIN orders AS o ON o.order_id = ol.order_id
           JOIN product_variants AS pv ON pv.sku = ol.sku
           WHERE o.order_date BETWEEN ? AND ?""",
        (start_date, end_date),
    ).fetchall()
    for sale in sales:
        paid_per_unit = apply_percent_discount_cents(
            sale["unit_price_cents"], sale["order_discount_pct"]
        )
        product = metrics[sale["product_id"]]
        product["units_sold"] += sale["quantity"]
        product["revenue_cents"] += paid_per_unit * sale["quantity"]

    returns = connection.execute(
        """SELECT pv.product_id, r.quantity, r.condition, r.refund_amount_cents,
                  o.order_date
           FROM returns AS r
           JOIN product_variants AS pv ON pv.sku = r.sku
           JOIN orders AS o ON o.order_id = r.order_id
           WHERE r.return_date BETWEEN ? AND ?""",
        (start_date, end_date),
    ).fetchall()
    for returned in returns:
        product = metrics[returned["product_id"]]
        product["refund_cents"] += returned["refund_amount_cents"]
        if (
            returned["condition"] == "good"
            and start_date <= returned["order_date"] <= end_date
        ):
            product["good_units_returned"] += returned["quantity"]

    northwind_costs = {
        row["product_id"]: row["unit_cost_cents"]
        for row in connection.execute(
            """SELECT sc.product_id, sc.unit_cost_cents
               FROM supplier_catalog AS sc
               JOIN suppliers AS s ON s.supplier_id = sc.supplier_id
               WHERE s.name = 'Northwind Supply'"""
        )
    }

    results: list[dict[str, object]] = []
    names = {row["product_id"]: row["name"] for row in products}
    for product_id, product in metrics.items():
        if product_id not in northwind_costs:
            raise ValueError(f"Northwind Supply cost missing for {product_id}")
        units_sold_kept = (
            product["units_sold"] - product["good_units_returned"]
        )
        revenue_kept_cents = (
            product["revenue_cents"] - product["refund_cents"]
        )
        cost_cents = units_sold_kept * northwind_costs[product_id]
        margin_cents = revenue_kept_cents - cost_cents
        results.append(
            {
                "product_id": product_id,
                "product_name": names[product_id],
                "units_sold_kept": units_sold_kept,
                "revenue_kept": cents_to_usd(revenue_kept_cents),
                "cost": cents_to_usd(cost_cents),
                "margin": cents_to_usd(margin_cents),
                "_margin_cents": margin_cents,
            }
        )

    results.sort(key=lambda row: (-int(row["_margin_cents"]), str(row["product_id"])))
    for row in results:
        del row["_margin_cents"]
    return results[:limit]


def get_stockout_risk(
    connection: sqlite3.Connection,
) -> list[dict[str, object]]:
    """Return products below reorder thresholds or under 14 days of cover."""
    monthly_sales: defaultdict[str, int] = defaultdict(int)
    for row in connection.execute(
        """SELECT pv.product_id, SUM(ol.quantity) AS units
           FROM order_lines AS ol
           JOIN orders AS o ON o.order_id = ol.order_id
           JOIN product_variants AS pv ON pv.sku = ol.sku
           WHERE o.order_date BETWEEN '2026-05-01' AND '2026-05-31'
           GROUP BY pv.product_id"""
    ):
        monthly_sales[row["product_id"]] = row["units"]

    inventory = connection.execute(
        """SELECT p.product_id, p.name,
                  SUM(i.on_hand_qty) AS on_hand_total,
                  MAX(CASE WHEN i.on_hand_qty <= i.reorder_point THEN 1 ELSE 0 END)
                      AS any_below_reorder
           FROM products AS p
           JOIN product_variants AS pv ON pv.product_id = p.product_id
           JOIN inventory AS i ON i.sku = pv.sku
           GROUP BY p.product_id, p.name
           ORDER BY p.product_id"""
    ).fetchall()

    results: list[dict[str, object]] = []
    for row in inventory:
        monthly_units = monthly_sales[row["product_id"]]
        days_of_cover = (
            None
            if monthly_units == 0
            else round(row["on_hand_total"] * 30 / monthly_units, 2)
        )
        reasons: list[str] = []
        if row["any_below_reorder"]:
            reasons.append("at_or_below_reorder_point")
        if days_of_cover is not None and days_of_cover < 14:
            reasons.append("fewer_than_14_days_of_cover")
        if reasons:
            results.append(
                {
                    "product_id": row["product_id"],
                    "product_name": row["name"],
                    "on_hand_total": row["on_hand_total"],
                    "monthly_units": monthly_units,
                    "days_of_cover": days_of_cover,
                    "reasons": reasons,
                }
            )
    return results
