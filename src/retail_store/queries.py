from __future__ import annotations

import sqlite3
from collections import defaultdict

from retail_store.matching import resolve_sku
from retail_store.money import apply_percent_discount_cents, cents_to_usd
from retail_store.services import get_effective_unit_price_cents
from retail_store.analytics import top_products_by_profit_margin


def _order_total_expression() -> str:
    return (
        "CAST(ROUND(SUM(ol.quantity * ol.unit_price_cents) * "
        "(100 - o.order_discount_pct) / 100.0) AS INTEGER)"
    )


def inventory_report(
    connection: sqlite3.Connection,
    product_description: str | None = None,
    sku: str | None = None,
) -> list[dict[str, object]]:
    target_sku = sku
    if product_description and not sku:
        try:
            target_sku = resolve_sku(connection, product_description)
        except ValueError:
            target_sku = None
    clauses, parameters = [], []
    if target_sku:
        clauses.append("pv.sku = ?")
        parameters.append(target_sku)
    elif product_description:
        clauses.append(
            "(lower(p.name) = lower(?) OR instr(lower(p.name), lower(?)) > 0)"
        )
        parameters.extend([product_description, product_description])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"""SELECT p.product_id, p.name product_name, p.category, pv.sku,
                   pv.color, pv.size, i.on_hand_qty, i.reorder_point,
                   i.reorder_qty
            FROM inventory i
            JOIN product_variants pv ON pv.sku=i.sku
            JOIN products p ON p.product_id=pv.product_id
            {where}
            ORDER BY p.product_id, pv.sku""",
        parameters,
    ).fetchall()
    if product_description and not rows:
        raise ValueError(f"product not found: {product_description!r}")
    sales = dict(
        connection.execute(
            """SELECT pv.product_id, SUM(ol.quantity)
               FROM order_lines ol JOIN orders o ON o.order_id=ol.order_id
               JOIN product_variants pv ON pv.sku=ol.sku
               WHERE o.order_date BETWEEN '2026-05-01' AND '2026-05-31'
               GROUP BY pv.product_id"""
        ).fetchall()
    )
    totals: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        totals[row["product_id"]] += row["on_hand_qty"]
    return [
        {
            **dict(row),
            "product_on_hand_total": totals[row["product_id"]],
            "days_of_cover": (
                round(totals[row["product_id"]] * 30 / sales[row["product_id"]], 2)
                if sales.get(row["product_id"])
                else None
            ),
        }
        for row in rows
    ]


def order_details(connection: sqlite3.Connection, order_id: str) -> dict[str, object]:
    order = connection.execute(
        """SELECT o.*, c.name customer_name FROM orders o
           LEFT JOIN customers c ON c.customer_id=o.customer_id
           WHERE o.order_id=?""",
        (order_id,),
    ).fetchone()
    if order is None:
        raise ValueError(f"order not found: {order_id!r}")
    lines = connection.execute(
        """SELECT ol.line_no, ol.sku, p.name product_name, ol.quantity,
                  ol.unit_price_cents
           FROM order_lines ol JOIN product_variants pv ON pv.sku=ol.sku
           JOIN products p ON p.product_id=pv.product_id
           WHERE ol.order_id=? ORDER BY ol.line_no""",
        (order_id,),
    ).fetchall()
    total = sum(r["quantity"] * r["unit_price_cents"] for r in lines)
    total = round(total * (100 - order["order_discount_pct"]) / 100)
    return {
        "order_id": order_id,
        "customer": order["customer_name"] or "walk-in",
        "order_date": order["order_date"],
        "payment_method": order["payment_method"],
        "total_paid": cents_to_usd(total),
        "lines": [
            {
                **dict(row),
                "unit_price": cents_to_usd(
                    apply_percent_discount_cents(
                        row["unit_price_cents"], order["order_discount_pct"]
                    )
                ),
            }
            for row in lines
        ],
    }


def customer_report(
    connection: sqlite3.Connection,
    start_date: str | None = None,
    end_date: str | None = None,
    customer_name: str | None = None,
    include_walk_ins: bool = False,
    sort_by_revenue: bool = False,
    limit: int | None = None,
) -> list[dict[str, object]]:
    """Read customers, optionally with order counts and revenue for a period."""
    clauses: list[str] = []
    parameters: list[object] = []
    if customer_name:
        clauses.append("lower(c.name) = lower(?)")
        parameters.append(customer_name)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    customers = [
        dict(row)
        for row in connection.execute(
            f"""SELECT c.customer_id, c.name, c.email, c.joined_date
                FROM customers c
                {where}
                ORDER BY c.name""",
            parameters,
        )
    ]
    if customer_name and not customers:
        raise ValueError(f"customer not found: {customer_name!r}")
    if start_date is None and end_date is None:
        return customers
    if start_date is None or end_date is None:
        raise ValueError("start_date and end_date must be provided together")

    totals = {
        row["customer_id"]: dict(row)
        for row in connection.execute(
            f"""SELECT c.customer_id, COUNT(*) order_count,
                       SUM(order_total_cents) total_spent_cents
                FROM (
                    SELECT o.order_id, o.customer_id,
                           {_order_total_expression()} AS order_total_cents
                    FROM orders o
                    JOIN order_lines ol ON ol.order_id=o.order_id
                    WHERE o.order_date BETWEEN ? AND ?
                    GROUP BY o.order_id
                ) order_totals
                JOIN customers c ON c.customer_id=order_totals.customer_id
                GROUP BY c.customer_id""",
            (start_date, end_date),
        )
    }
    results = []
    for customer in customers:
        total = totals.get(customer["customer_id"], {})
        results.append(
            {
                **customer,
                "order_count": total.get("order_count", 0),
                "total_spent": cents_to_usd(total.get("total_spent_cents", 0) or 0),
            }
        )
    if include_walk_ins:
        walk_in = connection.execute(
            f"""SELECT COUNT(*) order_count, SUM(order_total_cents) total_spent_cents
                FROM (
                    SELECT o.order_id,
                           {_order_total_expression()} AS order_total_cents
                    FROM orders o
                    JOIN order_lines ol ON ol.order_id=o.order_id
                    WHERE o.customer_id IS NULL
                      AND o.order_date BETWEEN ? AND ?
                    GROUP BY o.order_id
                ) order_totals""",
            (start_date, end_date),
        ).fetchone()
        results.append(
            {
                "customer_id": None,
                "name": "walk-in",
                "email": None,
                "joined_date": None,
                "order_count": walk_in["order_count"] or 0,
                "total_spent": cents_to_usd(walk_in["total_spent_cents"] or 0),
            }
        )
    if sort_by_revenue:
        results.sort(key=lambda row: float(row["total_spent"]), reverse=True)
    if limit is not None:
        results = results[:limit]
    return results


def order_report(
    connection: sqlite3.Connection,
    start_date: str = "2026-05-01",
    end_date: str = "2026-05-31",
    customer_name: str | None = None,
    walk_in: bool | None = None,
    payment_method: str | None = None,
    order_discount_only: bool = False,
    group_by: str = "order",
) -> list[dict[str, object]]:
    """Read orders with totals, customer, payment method, and discounts."""
    clauses = ["o.order_date BETWEEN ? AND ?"]
    parameters: list[object] = [start_date, end_date]
    if customer_name:
        clauses.append("lower(c.name) = lower(?)")
        parameters.append(customer_name)
    if walk_in is not None:
        clauses.append("o.customer_id IS NULL" if walk_in else "o.customer_id IS NOT NULL")
    if payment_method:
        clauses.append("o.payment_method = ?")
        parameters.append(payment_method)
    if order_discount_only:
        clauses.append("o.order_discount_pct > 0")
    where = " AND ".join(clauses)
    if group_by == "payment_method":
        rows = connection.execute(
            f"""SELECT payment_method, COUNT(*) order_count,
                       SUM(total_paid_cents) total_revenue_cents
                FROM (
                    SELECT o.order_id, o.payment_method,
                           {_order_total_expression()} AS total_paid_cents
                    FROM orders o
                    LEFT JOIN customers c ON c.customer_id=o.customer_id
                    JOIN order_lines ol ON ol.order_id=o.order_id
                    WHERE {where}
                    GROUP BY o.order_id
                ) order_totals
                GROUP BY payment_method
                ORDER BY payment_method""",
            parameters,
        ).fetchall()
        return [
            {
                **dict(row),
                "total_revenue": cents_to_usd(row["total_revenue_cents"]),
            }
            for row in rows
        ]
    if group_by != "order":
        raise ValueError("group_by must be 'order' or 'payment_method'")
    rows = connection.execute(
        f"""SELECT o.order_id, o.order_date, COALESCE(c.name, 'walk-in') customer,
                   o.payment_method, o.order_discount_pct,
                   {_order_total_expression()} AS total_paid_cents
            FROM orders o
            LEFT JOIN customers c ON c.customer_id=o.customer_id
            JOIN order_lines ol ON ol.order_id=o.order_id
            WHERE {where}
            GROUP BY o.order_id
            ORDER BY o.order_date, o.order_id""",
        parameters,
    ).fetchall()
    if customer_name and not rows:
        known = connection.execute(
            "SELECT 1 FROM customers WHERE lower(name) = lower(?)",
            (customer_name,),
        ).fetchone()
        if known is None:
            raise ValueError(f"customer not found: {customer_name!r}")
    return [
        {
            **dict(row),
            "total_paid": cents_to_usd(row["total_paid_cents"]),
        }
        for row in rows
    ]


def sales_report(
    connection: sqlite3.Connection,
    start_date: str = "2026-05-01",
    end_date: str = "2026-05-31",
    product_description: str | None = None,
    group_by: str = "product",
    only_with_refunds: bool = False,
    only_with_returns: bool = False,
) -> list[dict[str, object]]:
    rows = connection.execute(
        """SELECT p.product_id, p.name product_name, p.category,
                  SUM(ol.quantity) units_sold,
                  SUM(ol.quantity * ol.unit_price_cents *
                      (100-o.order_discount_pct) / 100) gross_revenue_cents
           FROM order_lines ol JOIN orders o ON o.order_id=ol.order_id
           JOIN product_variants pv ON pv.sku=ol.sku
           JOIN products p ON p.product_id=pv.product_id
           WHERE o.order_date BETWEEN ? AND ?
           GROUP BY p.product_id, p.name, p.category ORDER BY p.product_id""",
        (start_date, end_date),
    ).fetchall()
    refunds = dict(
        connection.execute(
            """SELECT pv.product_id, SUM(r.refund_amount_cents)
               FROM returns r JOIN product_variants pv ON pv.sku=r.sku
               WHERE r.return_date BETWEEN ? AND ? GROUP BY pv.product_id""",
            (start_date, end_date),
        ).fetchall()
    )
    returned_units = dict(
        connection.execute(
            """SELECT pv.product_id, SUM(r.quantity)
               FROM returns r JOIN product_variants pv ON pv.sku=r.sku
               WHERE r.return_date BETWEEN ? AND ? GROUP BY pv.product_id""",
            (start_date, end_date),
        ).fetchall()
    )
    margins = {
        row["product_id"]: row
        for row in top_products_by_profit_margin(
            connection, start_date=start_date, end_date=end_date, limit=1000
        )
    }
    results = []
    for row in rows:
        if product_description and product_description.casefold() not in row["product_name"].casefold():
            continue
        refund = refunds.get(row["product_id"], 0)
        results.append(
            {
                **dict(row),
                "gross_revenue": cents_to_usd(row["gross_revenue_cents"]),
                "refunds": cents_to_usd(refund),
                "net_revenue": cents_to_usd(row["gross_revenue_cents"] - refund),
                "units_returned": returned_units.get(row["product_id"], 0),
                "cost_of_goods_sold": margins[row["product_id"]]["cost"],
                "margin": margins[row["product_id"]]["margin"],
            }
        )
    if only_with_refunds:
        results = [row for row in results if float(row["refunds"]) > 0]
    if only_with_returns:
        results = [row for row in results if int(row["units_returned"]) > 0]
    if group_by == "category":
        grouped: dict[str, dict[str, object]] = {}
        for row in results:
            item = grouped.setdefault(
                str(row["category"]),
                {"category": row["category"], "units_sold": 0, "units_returned": 0,
                 "gross_cents": 0, "refund_cents": 0, "cost_cents": 0, "margin_cents": 0},
            )
            item["units_sold"] += row["units_sold"]
            item["units_returned"] += row["units_returned"]
            item["gross_cents"] += int(round(float(row["gross_revenue"]) * 100))
            item["refund_cents"] += int(round(float(row["refunds"]) * 100))
            item["cost_cents"] += int(round(float(row["cost_of_goods_sold"]) * 100))
            item["margin_cents"] += int(round(float(row["margin"]) * 100))
        return [
            {
                "product_name": row["category"], "category": row["category"],
                "units_sold": row["units_sold"], "units_returned": row["units_returned"],
                "gross_revenue": cents_to_usd(row["gross_cents"]),
                "refunds": cents_to_usd(row["refund_cents"]),
                "net_revenue": cents_to_usd(row["gross_cents"] - row["refund_cents"]),
                "cost_of_goods_sold": cents_to_usd(row["cost_cents"]),
                "margin": cents_to_usd(row["margin_cents"]),
            }
            for row in grouped.values()
        ]
    return results


def recommend_supplier(
    connection: sqlite3.Connection, product_description: str
) -> list[dict[str, object]]:
    sku = resolve_sku(connection, product_description)
    return [
        {
            **dict(row),
            "unit_cost": cents_to_usd(row["unit_cost_cents"]),
        }
        for row in connection.execute(
            """SELECT s.supplier_id, s.name supplier_name, sc.unit_cost_cents,
                      sc.lead_time_days
               FROM supplier_catalog sc JOIN suppliers s
                 ON s.supplier_id=sc.supplier_id
               JOIN product_variants pv ON pv.product_id=sc.product_id
               WHERE pv.sku=? ORDER BY sc.unit_cost_cents, sc.lead_time_days""",
            (sku,),
        )
    ]


def cancel_purchase_order(
    connection: sqlite3.Connection, po_id: str
) -> dict[str, object]:
    row = connection.execute(
        "SELECT status FROM purchase_orders WHERE po_id=?", (po_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"purchase order not found: {po_id}")
    if row["status"] not in {"open", "partial"}:
        raise ValueError(f"purchase order {po_id} cannot be cancelled from {row['status']}")
    connection.execute(
        "UPDATE purchase_orders SET status='cancelled' WHERE po_id=?", (po_id,)
    )
    connection.commit()
    return {"po_id": po_id, "status": "cancelled"}


def purchase_order_report(
    connection: sqlite3.Connection,
) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in connection.execute(
            """SELECT po.po_id, p.name product_name, s.name supplier_name,
                      po.quantity_ordered, po.quantity_received, po.status,
                      po.created_date, sc.lead_time_days
               FROM purchase_orders po
               JOIN products p ON p.product_id=po.product_id
               JOIN suppliers s ON s.supplier_id=po.supplier_id
               LEFT JOIN supplier_catalog sc
                 ON sc.product_id=po.product_id AND sc.supplier_id=po.supplier_id
               ORDER BY po.po_id"""
        )
    ]


def price_quote(
    connection: sqlite3.Connection,
    product_description: str,
    price_date: str = "2026-06-19",
    color: str | None = None,
    size: str | None = None,
) -> dict[str, object]:
    sku = resolve_sku(connection, product_description, color=color, size=size)
    row = connection.execute(
        """SELECT p.name FROM product_variants pv JOIN products p
           ON p.product_id=pv.product_id WHERE pv.sku=?""",
        (sku,),
    ).fetchone()
    return {
        "product_name": row["name"],
        "sku": sku,
        "price_date": price_date,
        "unit_price": cents_to_usd(
            get_effective_unit_price_cents(connection, sku, price_date)
        ),
    }
