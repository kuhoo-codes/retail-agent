from __future__ import annotations

import sqlite3
import re
from difflib import SequenceMatcher
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Iterator

from retail_store.matching import PRODUCT_ALIASES, SkuAmbiguityError, resolve_sku
from retail_store.money import apply_percent_discount_cents, cents_to_usd


class OrderError(ValueError):
    """Base class for deterministic order creation failures."""


class CustomerNotFoundError(OrderError):
    """Raised when a supplied customer name does not exist."""


class CustomerAmbiguityError(OrderError):
    """Raised when a customer name identifies multiple customers."""


class InsufficientInventoryError(OrderError):
    """Raised when an order requests more stock than is available."""


class ReturnError(ValueError):
    """Raised when a return cannot be processed."""


class PromotionError(ValueError):
    """Raised when a promotion definition is invalid."""


class RestockError(ValueError):
    """Raised when a purchase-order operation cannot be completed."""


@dataclass(frozen=True)
class ActivePromotion:
    promo_id: str
    description: str
    value_pct: int
    scope_type: str
    scope_ref: str
    start_date: str
    end_date: str


def _iso_date(value: str | date) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise TypeError("sale_date must be a date or YYYY-MM-DD string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid sale date: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"sale_date must use YYYY-MM-DD: {value!r}")
    return value


def get_active_promotions(
    connection: sqlite3.Connection, sku: str, sale_date: str | date
) -> list[ActivePromotion]:
    """Return product/category promotions active for a SKU on a sale date."""
    sale_date_iso = _iso_date(sale_date)
    variant = connection.execute(
        """SELECT p.product_id, p.category
           FROM product_variants AS pv
           JOIN products AS p ON p.product_id = pv.product_id
           WHERE pv.sku = ?""",
        (sku,),
    ).fetchone()
    if variant is None:
        raise ValueError(f"unknown SKU: {sku!r}")

    rows = connection.execute(
        """SELECT promo_id, description, value_pct, scope_type, scope_ref,
                  start_date, end_date
           FROM promotions
           WHERE start_date <= ?
             AND end_date >= ?
             AND (
                 (scope_type = 'product' AND scope_ref = ?)
                 OR (scope_type = 'category' AND scope_ref = ?)
             )
           ORDER BY promo_id""",
        (
            sale_date_iso,
            sale_date_iso,
            variant["product_id"],
            variant["category"],
        ),
    ).fetchall()
    return [
        ActivePromotion(
            promo_id=row["promo_id"],
            description=row["description"],
            value_pct=row["value_pct"],
            scope_type=row["scope_type"],
            scope_ref=row["scope_ref"],
            start_date=row["start_date"],
            end_date=row["end_date"],
        )
        for row in rows
    ]


def get_effective_unit_price_cents(
    connection: sqlite3.Connection, sku: str, sale_date: str | date
) -> int:
    """Return list price or the lowest single-promotion price for a SKU."""
    variant = connection.execute(
        "SELECT retail_price_cents FROM product_variants WHERE sku = ?",
        (sku,),
    ).fetchone()
    if variant is None:
        raise ValueError(f"unknown SKU: {sku!r}")

    list_price = variant["retail_price_cents"]
    promotion_prices = [
        apply_percent_discount_cents(list_price, promotion.value_pct)
        for promotion in get_active_promotions(connection, sku, sale_date)
    ]
    return min([list_price, *promotion_prices])


@contextmanager
def _atomic(connection: sqlite3.Connection) -> Iterator[None]:
    if connection.in_transaction:
        connection.execute("SAVEPOINT create_order")
        try:
            yield
        except BaseException:
            connection.execute("ROLLBACK TO SAVEPOINT create_order")
            connection.execute("RELEASE SAVEPOINT create_order")
            raise
        else:
            connection.execute("RELEASE SAVEPOINT create_order")
    else:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()


def _next_order_id(connection: sqlite3.Connection) -> str:
    highest = 0
    width = 4
    for row in connection.execute("SELECT order_id FROM orders"):
        match = re.fullmatch(r"O-(\d+)", row["order_id"])
        if match:
            number_text = match.group(1)
            highest = max(highest, int(number_text))
            width = max(width, len(number_text))
    return f"O-{highest + 1:0{width}d}"


def _next_prefixed_id(
    connection: sqlite3.Connection, table: str, column: str, prefix: str, width: int
) -> str:
    highest = 0
    for row in connection.execute(f"SELECT {column} FROM {table}"):
        match = re.fullmatch(rf"{re.escape(prefix)}(\d+)", row[column])
        if match:
            highest = max(highest, int(match.group(1)))
            width = max(width, len(match.group(1)))
    return f"{prefix}{highest + 1:0{width}d}"


def _resolve_customer_id(
    connection: sqlite3.Connection, customer_name: str | None
) -> str | None:
    if customer_name is None or customer_name.strip().casefold() in {
        "",
        "walk-in",
        "walk in",
        "walkin",
    }:
        return None
    rows = connection.execute(
        "SELECT customer_id FROM customers WHERE lower(name) = lower(?)",
        (customer_name.strip(),),
    ).fetchall()
    if not rows:
        candidates = connection.execute(
            "SELECT customer_id, name FROM customers ORDER BY customer_id"
        ).fetchall()
        normalized = customer_name.strip().casefold()
        close = [
            row for row in candidates
            if row["name"].casefold().startswith(normalized)
            or SequenceMatcher(None, normalized, row["name"].casefold()).ratio() >= 0.8
        ]
        if len(close) == 1:
            return close[0]["customer_id"]
        raise CustomerNotFoundError(f"customer not found: {customer_name!r}")
    if len(rows) > 1:
        raise CustomerAmbiguityError(f"customer name is ambiguous: {customer_name!r}")
    return rows[0]["customer_id"]


def create_order(
    connection: sqlite3.Connection,
    items: list[dict[str, object]],
    customer_name: str | None = None,
    payment_method: str = "card",
    order_date: str = "2026-06-19",
    order_discount_pct: int = 0,
) -> dict[str, object]:
    """Create a fully validated sale and decrement inventory atomically."""
    if payment_method not in {"cash", "card"}:
        raise OrderError("payment_method must be 'cash' or 'card'")
    _iso_date(order_date)
    if (
        isinstance(order_discount_pct, bool)
        or not isinstance(order_discount_pct, int)
        or not 0 <= order_discount_pct <= 100
    ):
        raise OrderError("order_discount_pct must be an integer between 0 and 100")
    if not isinstance(items, list) or not items:
        raise OrderError("items must be a non-empty list")

    with _atomic(connection):
        customer_id = _resolve_customer_id(connection, customer_name)
        resolved_lines: list[dict[str, object]] = []
        requested_by_sku: dict[str, int] = {}

        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise OrderError(f"item {index} must be a mapping")
            description = item.get("product_description")
            if not isinstance(description, str) or not description.strip():
                raise OrderError(f"item {index} requires product_description")
            quantity = item.get("quantity")
            if (
                isinstance(quantity, bool)
                or not isinstance(quantity, int)
                or quantity <= 0
            ):
                raise OrderError(f"item {index} quantity must be a positive integer")
            color = item.get("color")
            size = item.get("size")
            if color is not None and not isinstance(color, str):
                raise OrderError(f"item {index} color must be text")
            if size is not None and not isinstance(size, str):
                raise OrderError(f"item {index} size must be text")

            sku = resolve_sku(connection, description, color=color, size=size)
            product = connection.execute(
                """SELECT p.name
                   FROM product_variants AS pv
                   JOIN products AS p ON p.product_id = pv.product_id
                   WHERE pv.sku = ?""",
                (sku,),
            ).fetchone()
            unit_price_cents = get_effective_unit_price_cents(
                connection, sku, order_date
            )
            requested_by_sku[sku] = requested_by_sku.get(sku, 0) + quantity
            resolved_lines.append(
                {
                    "sku": sku,
                    "name": product["name"],
                    "quantity": quantity,
                    "unit_price_cents": unit_price_cents,
                }
            )

        remaining_by_sku: dict[str, int] = {}
        for sku, requested in requested_by_sku.items():
            inventory = connection.execute(
                "SELECT on_hand_qty FROM inventory WHERE sku = ?", (sku,)
            ).fetchone()
            if inventory is None:
                raise InsufficientInventoryError(f"no inventory record for SKU {sku}")
            available = inventory["on_hand_qty"]
            if requested > available:
                raise InsufficientInventoryError(
                    f"insufficient inventory for {sku}: "
                    f"requested {requested}, available {available}"
                )
            remaining_by_sku[sku] = available - requested

        order_id = _next_order_id(connection)
        connection.execute(
            """INSERT INTO orders
               (order_id, order_date, customer_id, order_discount_pct, payment_method)
               VALUES (?, ?, ?, ?, ?)""",
            (
                order_id,
                order_date,
                customer_id,
                order_discount_pct,
                payment_method,
            ),
        )
        for line_no, line in enumerate(resolved_lines, start=1):
            connection.execute(
                """INSERT INTO order_lines
                   (order_id, line_no, sku, quantity, unit_price_cents)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    order_id,
                    line_no,
                    line["sku"],
                    line["quantity"],
                    line["unit_price_cents"],
                ),
            )
        for sku, requested in requested_by_sku.items():
            connection.execute(
                "UPDATE inventory SET on_hand_qty = on_hand_qty - ? WHERE sku = ?",
                (requested, sku),
            )

        subtotal_cents = sum(
            int(line["unit_price_cents"]) * int(line["quantity"])
            for line in resolved_lines
        )
        response_lines = []
        for line in resolved_lines:
            discounted_unit_cents = apply_percent_discount_cents(
                int(line["unit_price_cents"]), order_discount_pct
            )
            line_total_cents = discounted_unit_cents * int(line["quantity"])
            response_lines.append(
                {
                    "sku": line["sku"],
                    "name": line["name"],
                    "quantity": line["quantity"],
                    "unit_price": cents_to_usd(int(line["unit_price_cents"])),
                    "line_total_after_order_discount": cents_to_usd(
                        line_total_cents
                    ),
                }
            )
        total_paid_cents = sum(
            apply_percent_discount_cents(
                int(line["unit_price_cents"]), order_discount_pct
            )
            * int(line["quantity"])
            for line in resolved_lines
        )

        return {
            "order_id": order_id,
            "customer_id": customer_id if customer_id is not None else "walk-in",
            "payment_method": payment_method,
            "order_date": order_date,
            "line_items": response_lines,
            "subtotal_before_order_discount": cents_to_usd(subtotal_cents),
            "order_discount_pct": order_discount_pct,
            "total_paid": cents_to_usd(total_paid_cents),
            "remaining_inventory": remaining_by_sku,
        }


def process_return(
    connection: sqlite3.Connection,
    order_id: str,
    product_description: str | None = None,
    sku: str | None = None,
    color: str | None = None,
    size: str | None = None,
    quantity: int = 1,
    condition: str = "good",
    return_date: str = "2026-06-19",
) -> dict[str, object]:
    """Refund units from one original order line and update sellable stock."""
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity <= 0
    ):
        raise ReturnError("quantity must be a positive integer")
    if condition not in {"good", "damaged"}:
        raise ReturnError("condition must be 'good' or 'damaged'")
    _iso_date(return_date)

    with _atomic(connection):
        order = connection.execute(
            "SELECT order_discount_pct FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if order is None:
            raise ReturnError(f"order not found: {order_id!r}")

        if sku is None:
            if not product_description:
                raise ReturnError("provide sku or product_description")
            try:
                sku = resolve_sku(
                    connection, product_description, color=color, size=size
                )
            except SkuAmbiguityError:
                normalized = " ".join(
                    re.findall(r"[a-z0-9]+", product_description.casefold())
                )
                product_name = next(
                    (
                        canonical
                        for alias, canonical in sorted(
                            PRODUCT_ALIASES.items(),
                            key=lambda item: len(item[0]),
                            reverse=True,
                        )
                        if f" {alias} " in f" {normalized} "
                    ),
                    None,
                )
                candidates = connection.execute(
                    """SELECT DISTINCT ol.sku
                       FROM order_lines ol
                       JOIN product_variants pv ON pv.sku=ol.sku
                       JOIN products p ON p.product_id=pv.product_id
                       WHERE ol.order_id=? AND lower(p.name)=lower(?)""",
                    (order_id, product_name),
                ).fetchall()
                if len(candidates) != 1:
                    raise
                sku = candidates[0]["sku"]
        else:
            variant = connection.execute(
                "SELECT 1 FROM product_variants WHERE sku = ?", (sku,)
            ).fetchone()
            if variant is None:
                raise ReturnError(f"unknown SKU: {sku!r}")

        lines = connection.execute(
            """SELECT line_no, quantity, unit_price_cents
               FROM order_lines
               WHERE order_id = ? AND sku = ?
               ORDER BY line_no""",
            (order_id, sku),
        ).fetchall()
        if not lines:
            raise ReturnError(f"SKU {sku} was not sold on order {order_id}")
        if len(lines) > 1:
            raise ReturnError(
                f"SKU {sku} appears on multiple lines of order {order_id}"
            )
        line = lines[0]
        already_returned = connection.execute(
            """SELECT COALESCE(SUM(quantity), 0)
               FROM returns
               WHERE order_id = ? AND order_line_no = ?""",
            (order_id, line["line_no"]),
        ).fetchone()[0]
        available_to_return = line["quantity"] - already_returned
        if quantity > available_to_return:
            raise ReturnError(
                f"return quantity exceeds remaining sold quantity for {sku}: "
                f"requested {quantity}, available {available_to_return}"
            )

        refund_per_unit_cents = apply_percent_discount_cents(
            line["unit_price_cents"], order["order_discount_pct"]
        )
        refund_cents = refund_per_unit_cents * quantity
        return_id = _next_prefixed_id(
            connection, "returns", "return_id", "R-", 4
        )
        connection.execute(
            """INSERT INTO returns
               (return_id, return_date, order_id, order_line_no, sku, quantity,
                condition, refund_amount_cents)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                return_id,
                return_date,
                order_id,
                line["line_no"],
                sku,
                quantity,
                condition,
                refund_cents,
            ),
        )
        inventory_change = quantity if condition == "good" else 0
        if inventory_change:
            updated = connection.execute(
                "UPDATE inventory SET on_hand_qty = on_hand_qty + ? WHERE sku = ?",
                (inventory_change, sku),
            )
            if updated.rowcount != 1:
                raise ReturnError(f"no inventory record for SKU {sku}")
        remaining_inventory = connection.execute(
            "SELECT on_hand_qty FROM inventory WHERE sku = ?", (sku,)
        ).fetchone()

        return {
            "return_id": return_id,
            "order_id": order_id,
            "order_line_no": line["line_no"],
            "sku": sku,
            "quantity": quantity,
            "condition": condition,
            "refund_amount": cents_to_usd(refund_cents),
            "inventory_increase": inventory_change,
            "remaining_inventory": (
                remaining_inventory["on_hand_qty"]
                if remaining_inventory is not None
                else None
            ),
        }


def create_promotion(
    connection: sqlite3.Connection,
    description: str,
    percent_off: int,
    scope_type: str,
    scope_ref: str,
    start_date: str,
    end_date: str,
) -> dict[str, object]:
    """Create a validated product- or category-scoped percentage promotion."""
    if not isinstance(description, str) or not description.strip():
        raise PromotionError("description cannot be blank")
    if (
        isinstance(percent_off, bool)
        or not isinstance(percent_off, int)
        or not 0 <= percent_off <= 100
    ):
        raise PromotionError("percent_off must be an integer between 0 and 100")
    if scope_type not in {"product", "category"}:
        raise PromotionError("scope_type must be 'product' or 'category'")
    normalized_scope = scope_ref.strip().casefold().replace(" ", "_").replace("-", "_")
    product_scopes = {
        "p_hood": "P-HOOD",
        "pullover_hoodie": "P-HOOD",
        "hoodie": "P-HOOD",
        "hoodies": "P-HOOD",
        "p_sock": "P-SOCK",
        "wool_sock": "P-SOCK",
        "wool_socks": "P-SOCK",
        "sock": "P-SOCK",
        "socks": "P-SOCK",
        "p_mug": "P-MUG",
        "ceramic_mug": "P-MUG",
        "mug": "P-MUG",
        "mugs": "P-MUG",
        "p_tote": "P-TOTE",
        "canvas_tote": "P-TOTE",
        "canvas_totes": "P-TOTE",
        "tote": "P-TOTE",
        "totes": "P-TOTE",
        "bag": "P-TOTE",
        "canvas_bag": "P-TOTE",
        "p_tee": "P-TEE",
        "classic_tee": "P-TEE",
        "classic_tees": "P-TEE",
        "tee": "P-TEE",
        "tees": "P-TEE",
        "t_shirt": "P-TEE",
        "t_shirts": "P-TEE",
    }
    description_text = " ".join(re.findall(r"[a-z0-9]+", description.casefold()))
    description_scope = next(
        (
            product_id
            for alias, product_id in sorted(
                product_scopes.items(), key=lambda item: len(item[0]), reverse=True
            )
            if f" {alias.replace('_', ' ')} " in f" {description_text} "
        ),
        None,
    )
    if scope_type == "category":
        if description_scope is not None and normalized_scope in {
            "all",
            "all_goods",
            "general_goods",
            "all_apparel",
            "goods",
            "apparel",
        }:
            scope_type, scope_ref = "product", description_scope
            normalized_scope = scope_ref.casefold()
        if normalized_scope in product_scopes:
            scope_type, scope_ref = "product", product_scopes[normalized_scope]
            normalized_scope = scope_ref.casefold()
        scope_ref = {
            "all": "goods",
            "all_goods": "goods",
            "general_goods": "goods",
            "all_apparel": "apparel",
        }.get(normalized_scope, scope_ref if scope_type == "product" else normalized_scope)
    else:
        scope_ref = product_scopes.get(normalized_scope, scope_ref)
    start = _iso_date(start_date)
    end = _iso_date(end_date)
    if start > end:
        raise PromotionError("start_date must be on or before end_date")

    with _atomic(connection):
        if scope_type == "product":
            valid_scope = connection.execute(
                "SELECT 1 FROM products WHERE product_id = ?", (scope_ref,)
            ).fetchone()
        else:
            valid_scope = connection.execute(
                "SELECT 1 FROM products WHERE category = ? LIMIT 1", (scope_ref,)
            ).fetchone()
        if valid_scope is None:
            raise PromotionError(
                f"invalid {scope_type} promotion scope: {scope_ref!r}"
            )
        promo_id = _next_prefixed_id(
            connection, "promotions", "promo_id", "PR-", 3
        )
        connection.execute(
            """INSERT INTO promotions
               (promo_id, description, type, value_pct, scope_type, scope_ref,
                start_date, end_date)
               VALUES (?, ?, 'percent_off', ?, ?, ?, ?, ?)""",
            (
                promo_id,
                description.strip(),
                percent_off,
                scope_type,
                scope_ref,
                start,
                end,
            ),
        )
        return {
            "promo_id": promo_id,
            "description": description.strip(),
            "percent_off": percent_off,
            "scope_type": scope_type,
            "scope_ref": scope_ref,
            "start_date": start,
            "end_date": end,
        }


def reorder_low_stock(
    connection: sqlite3.Connection, created_date: str = "2026-06-19"
) -> list[dict[str, object]]:
    """Create one PO per product for variants at or below their reorder points."""
    created = _iso_date(created_date)
    with _atomic(connection):
        needs = connection.execute(
            """SELECT pv.product_id, SUM(i.reorder_qty) AS quantity_ordered
               FROM inventory AS i
               JOIN product_variants AS pv ON pv.sku = i.sku
               WHERE i.on_hand_qty <= i.reorder_point
               GROUP BY pv.product_id
               ORDER BY pv.product_id"""
        ).fetchall()
        results: list[dict[str, object]] = []
        for need in needs:
            existing = connection.execute(
                """SELECT 1 FROM purchase_orders
                   WHERE product_id=? AND status IN ('open', 'partial') LIMIT 1""",
                (need["product_id"],),
            ).fetchone()
            if existing is not None:
                continue
            supplier = connection.execute(
                """SELECT sc.supplier_id, s.name, sc.unit_cost_cents,
                          sc.lead_time_days
                   FROM supplier_catalog AS sc
                   JOIN suppliers AS s ON s.supplier_id = sc.supplier_id
                   WHERE sc.product_id = ? AND sc.lead_time_days <= 10
                   ORDER BY sc.unit_cost_cents, sc.lead_time_days, sc.supplier_id
                   LIMIT 1""",
                (need["product_id"],),
            ).fetchone()
            if supplier is None:
                raise RestockError(
                    f"no eligible supplier for product {need['product_id']}"
                )
            po_id = _next_prefixed_id(
                connection, "purchase_orders", "po_id", "PO-", 4
            )
            connection.execute(
                """INSERT INTO purchase_orders
                   (po_id, supplier_id, product_id, quantity_ordered,
                    quantity_received, status, created_date)
                   VALUES (?, ?, ?, ?, 0, 'open', ?)""",
                (
                    po_id,
                    supplier["supplier_id"],
                    need["product_id"],
                    need["quantity_ordered"],
                    created,
                ),
            )
            results.append(
                {
                    "po_id": po_id,
                    "supplier_id": supplier["supplier_id"],
                    "supplier_name": supplier["name"],
                    "product_id": need["product_id"],
                    "quantity_ordered": need["quantity_ordered"],
                    "unit_cost": cents_to_usd(supplier["unit_cost_cents"]),
                    "lead_time_days": supplier["lead_time_days"],
                    "status": "open",
                    "created_date": created,
                }
            )
        return results


def receive_purchase_order(
    connection: sqlite3.Connection,
    product_description: str,
    supplier_name: str,
    quantity_ordered: int,
    quantity_received: int,
    received_date: str = "2026-06-19",
    *,
    sku: str | None = None,
    color: str | None = None,
    size: str | None = None,
) -> dict[str, object]:
    """Receive units against an open PO, creating that PO when absent."""
    for value, label, allow_zero in (
        (quantity_ordered, "quantity_ordered", False),
        (quantity_received, "quantity_received", True),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < (0 if allow_zero else 1)
        ):
            qualifier = "non-negative" if allow_zero else "positive"
            raise RestockError(f"{label} must be a {qualifier} integer")
    if quantity_received > quantity_ordered:
        raise RestockError("quantity_received cannot exceed quantity_ordered")
    received = _iso_date(received_date)

    with _atomic(connection):
        suppliers = connection.execute(
            "SELECT supplier_id, name FROM suppliers WHERE lower(name) = lower(?)",
            (supplier_name.strip(),),
        ).fetchall()
        if not suppliers:
            suppliers = connection.execute(
                """SELECT supplier_id, name
                   FROM suppliers
                   WHERE instr(lower(name), lower(?)) > 0
                   ORDER BY supplier_id""",
                (supplier_name.strip(),),
            ).fetchall()
        if not suppliers:
            raise RestockError(f"supplier not found: {supplier_name!r}")
        if len(suppliers) > 1:
            raise RestockError(f"supplier name is ambiguous: {supplier_name!r}")
        supplier = suppliers[0]

        product_names = connection.execute(
            "SELECT product_id, name FROM products WHERE lower(name) = lower(?)",
            (product_description.strip(),),
        ).fetchall()
        if not product_names:
            try:
                resolved = resolve_sku(
                    connection,
                    product_description,
                    color=color,
                    size=size,
                )
            except ValueError as exc:
                raise RestockError(str(exc)) from exc
            product = connection.execute(
                """SELECT p.product_id, p.name
                   FROM product_variants AS pv
                   JOIN products AS p ON p.product_id = pv.product_id
                   WHERE pv.sku = ?""",
                (resolved,),
            ).fetchone()
        elif len(product_names) > 1:
            raise RestockError(
                f"product description is ambiguous: {product_description!r}"
            )
        else:
            product = product_names[0]

        if sku is not None:
            target = connection.execute(
                """SELECT pv.sku
                   FROM product_variants AS pv
                   WHERE pv.sku = ? AND pv.product_id = ?""",
                (sku, product["product_id"]),
            ).fetchone()
            if target is None:
                raise RestockError(
                    f"SKU {sku!r} does not belong to {product['name']}"
                )
            target_sku = target["sku"]
        else:
            variants = connection.execute(
                "SELECT sku FROM product_variants WHERE product_id = ? ORDER BY sku",
                (product["product_id"],),
            ).fetchall()
            if len(variants) == 1:
                target_sku = variants[0]["sku"]
            else:
                try:
                    target_sku = resolve_sku(
                        connection, product["name"], color=color, size=size
                    )
                except ValueError as exc:
                    raise RestockError(
                        "multi-variant products require sku, color, and/or size: "
                        f"{exc}"
                    ) from exc

        po = connection.execute(
            """SELECT po_id, quantity_ordered, quantity_received
               FROM purchase_orders
               WHERE supplier_id = ? AND product_id = ?
                 AND status IN ('open', 'partial')
               ORDER BY po_id
               LIMIT 1""",
            (supplier["supplier_id"], product["product_id"]),
        ).fetchone()
        created_po = po is None
        if po is None:
            po_id = _next_prefixed_id(
                connection, "purchase_orders", "po_id", "PO-", 4
            )
            connection.execute(
                """INSERT INTO purchase_orders
                   (po_id, supplier_id, product_id, quantity_ordered,
                    quantity_received, status, created_date)
                   VALUES (?, ?, ?, ?, 0, 'open', ?)""",
                (
                    po_id,
                    supplier["supplier_id"],
                    product["product_id"],
                    quantity_ordered,
                    received,
                ),
            )
            prior_received = 0
        else:
            po_id = po["po_id"]
            if po["quantity_ordered"] != quantity_ordered:
                raise RestockError(
                    f"open PO {po_id} ordered {po['quantity_ordered']}, "
                    f"not {quantity_ordered}"
                )
            prior_received = po["quantity_received"]

        total_received = prior_received + quantity_received
        if total_received > quantity_ordered:
            raise RestockError(
                f"receiving {quantity_received} would exceed ordered quantity "
                f"{quantity_ordered}"
            )
        status = (
            "open"
            if total_received == 0
            else "received"
            if total_received == quantity_ordered
            else "partial"
        )
        connection.execute(
            """UPDATE purchase_orders
               SET quantity_received = ?, status = ?
               WHERE po_id = ?""",
            (total_received, status, po_id),
        )
        connection.execute(
            "UPDATE inventory SET on_hand_qty = on_hand_qty + ? WHERE sku = ?",
            (quantity_received, target_sku),
        )
        on_hand = connection.execute(
            "SELECT on_hand_qty FROM inventory WHERE sku = ?", (target_sku,)
        ).fetchone()["on_hand_qty"]

        return {
            "po_id": po_id,
            "created_po": created_po,
            "supplier_id": supplier["supplier_id"],
            "supplier_name": supplier["name"],
            "product_id": product["product_id"],
            "sku": target_sku,
            "quantity_ordered": quantity_ordered,
            "quantity_received": total_received,
            "received_now": quantity_received,
            "status": status,
            "remaining_inventory": on_hand,
        }
