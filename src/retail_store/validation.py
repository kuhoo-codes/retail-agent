from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable


class ValidationError(ValueError):
    """Raised when seed data violates the import contract."""


FILES_AND_COLUMNS = {
    "products": (
        "sku", "product_id", "product_name", "category", "color", "size",
        "retail_price",
    ),
    "customers": ("customer_id", "name", "email", "joined_date"),
    "suppliers": ("supplier_id", "supplier_name"),
    "supplier_catalog": (
        "supplier_id", "product_id", "unit_cost", "lead_time_days",
    ),
    "inventory": ("sku", "on_hand_qty", "reorder_point", "reorder_qty"),
    "orders": (
        "order_id", "order_date", "customer_id", "order_discount_pct",
        "payment_method",
    ),
    "order_lines": ("order_id", "line_no", "sku", "quantity", "unit_price"),
    "returns": (
        "return_id", "return_date", "order_id", "sku", "quantity",
        "condition", "refund_amount",
    ),
    "promotions": (
        "promo_id", "description", "type", "value", "scope_type",
        "scope_ref", "start_date", "end_date",
    ),
}


@dataclass(frozen=True)
class SeedData:
    tables: dict[str, list[dict[str, str]]]
    return_line_numbers: dict[str, int]


def parse_date(value: str, field: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{field}: invalid YYYY-MM-DD date {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValidationError(f"{field}: date must use YYYY-MM-DD: {value!r}")
    return value


def parse_int(
    value: str, field: str, *, minimum: int = 0, maximum: int | None = None
) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValidationError(f"{field}: invalid integer {value!r}") from exc
    if str(parsed) != value:
        raise ValidationError(f"{field}: integer must be canonical: {value!r}")
    if parsed < minimum or (maximum is not None and parsed > maximum):
        bounds = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise ValidationError(f"{field}: expected {bounds}, got {parsed}")
    return parsed


def parse_cents(value: str, field: str) -> int:
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationError(f"{field}: invalid money amount {value!r}") from exc
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise ValidationError(f"{field}: expected non-negative USD cents, got {value!r}")
    return int((amount * 100).to_integral_exact())


def _require_unique(
    rows: Iterable[dict[str, str]], columns: tuple[str, ...], table: str
) -> None:
    values = [tuple(row[column] for column in columns) for row in rows]
    duplicates = [value for value, count in Counter(values).items() if count > 1]
    if duplicates:
        raise ValidationError(
            f"{table}: duplicate key {columns}: {duplicates[0]!r}"
        )


def _read_tables(data_dir: Path) -> dict[str, list[dict[str, str]]]:
    tables: dict[str, list[dict[str, str]]] = {}
    for table, columns in FILES_AND_COLUMNS.items():
        path = data_dir / f"{table}.csv"
        if not path.is_file():
            raise ValidationError(f"missing seed file: {path}")
        with path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            if tuple(reader.fieldnames or ()) != columns:
                raise ValidationError(
                    f"{path.name}: expected columns {columns}, got "
                    f"{tuple(reader.fieldnames or ())}"
                )
            tables[table] = list(reader)
    return tables


def load_and_validate(data_dir: Path) -> SeedData:
    tables = _read_tables(data_dir)
    products = tables["products"]

    unique_keys = {
        "products": ("sku",),
        "customers": ("customer_id",),
        "suppliers": ("supplier_id",),
        "supplier_catalog": ("supplier_id", "product_id"),
        "inventory": ("sku",),
        "orders": ("order_id",),
        "order_lines": ("order_id", "line_no"),
        "returns": ("return_id",),
        "promotions": ("promo_id",),
    }
    for table, columns in unique_keys.items():
        _require_unique(tables[table], columns, table)

    product_ids = {row["product_id"] for row in products}
    skus = {row["sku"] for row in products}
    customers = {row["customer_id"] for row in tables["customers"]}
    suppliers = {row["supplier_id"] for row in tables["suppliers"]}
    orders = {row["order_id"] for row in tables["orders"]}

    for row in products:
        if not row["sku"] or not row["product_id"] or not row["product_name"]:
            raise ValidationError("products: identifiers and name cannot be blank")
        if row["category"] not in {"apparel", "goods"}:
            raise ValidationError(f"products: invalid category {row['category']!r}")
        parse_cents(row["retail_price"], f"products[{row['sku']}].retail_price")

    grouped: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in products:
        grouped[row["product_id"]].add((row["product_name"], row["category"]))
    inconsistent = [key for key, values in grouped.items() if len(values) != 1]
    if inconsistent:
        raise ValidationError(
            f"products: inconsistent product metadata for {inconsistent[0]}"
        )

    variant_keys = [
        (row["product_id"], row["color"] or None, row["size"] or None)
        for row in products
    ]
    if len(variant_keys) != len(set(variant_keys)):
        raise ValidationError("products: duplicate product/color/size variant")

    for row in tables["customers"]:
        parse_date(row["joined_date"], f"customers[{row['customer_id']}].joined_date")
        if not row["name"] or not row["email"]:
            raise ValidationError("customers: name and email cannot be blank")
    _require_unique(tables["customers"], ("email",), "customers")

    for row in tables["supplier_catalog"]:
        if row["supplier_id"] not in suppliers or row["product_id"] not in product_ids:
            raise ValidationError(f"supplier_catalog: orphan row {row!r}")
        parse_cents(row["unit_cost"], "supplier_catalog.unit_cost")
        parse_int(row["lead_time_days"], "supplier_catalog.lead_time_days")

    inventory_skus = {row["sku"] for row in tables["inventory"]}
    if inventory_skus != skus:
        missing = sorted(skus - inventory_skus)
        extra = sorted(inventory_skus - skus)
        raise ValidationError(
            f"inventory: must cover every SKU; missing={missing}, extra={extra}"
        )
    for row in tables["inventory"]:
        parse_int(row["on_hand_qty"], f"inventory[{row['sku']}].on_hand_qty")
        parse_int(row["reorder_point"], f"inventory[{row['sku']}].reorder_point")
        parse_int(
            row["reorder_qty"], f"inventory[{row['sku']}].reorder_qty", minimum=1
        )

    order_discounts: dict[str, int] = {}
    for row in tables["orders"]:
        if row["customer_id"] and row["customer_id"] not in customers:
            raise ValidationError(f"orders: unknown customer {row['customer_id']!r}")
        parse_date(row["order_date"], f"orders[{row['order_id']}].order_date")
        order_discounts[row["order_id"]] = parse_int(
            row["order_discount_pct"],
            f"orders[{row['order_id']}].order_discount_pct",
            maximum=100,
        )
        if row["payment_method"] not in {"cash", "card"}:
            raise ValidationError(
                f"orders: invalid payment method {row['payment_method']!r}"
            )

    lines_by_order_sku: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in tables["order_lines"]:
        if row["order_id"] not in orders or row["sku"] not in skus:
            raise ValidationError(f"order_lines: orphan row {row!r}")
        parse_int(row["line_no"], "order_lines.line_no", minimum=1)
        parse_int(row["quantity"], "order_lines.quantity", minimum=1)
        parse_cents(row["unit_price"], "order_lines.unit_price")
        lines_by_order_sku[(row["order_id"], row["sku"])].append(row)

    return_line_numbers: dict[str, int] = {}
    returned_quantities: Counter[tuple[str, str]] = Counter()
    for row in tables["returns"]:
        parse_date(row["return_date"], f"returns[{row['return_id']}].return_date")
        quantity = parse_int(row["quantity"], "returns.quantity", minimum=1)
        if row["condition"] not in {"good", "damaged"}:
            raise ValidationError(f"returns: invalid condition {row['condition']!r}")
        candidates = lines_by_order_sku[(row["order_id"], row["sku"])]
        if len(candidates) != 1:
            raise ValidationError(
                f"returns[{row['return_id']}]: expected exactly one original "
                f"order line, found {len(candidates)}"
            )
        line = candidates[0]
        returned_quantities[(row["order_id"], row["sku"])] += quantity
        if returned_quantities[(row["order_id"], row["sku"])] > int(line["quantity"]):
            raise ValidationError(f"returns[{row['return_id']}]: quantity exceeds sale")
        unit_price = Decimal(line["unit_price"])
        discount = Decimal(order_discounts[row["order_id"]])
        paid_per_unit = (
            unit_price * (Decimal(1) - discount / Decimal(100))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        expected_refund = int(paid_per_unit * quantity * 100)
        actual_refund = parse_cents(row["refund_amount"], "returns.refund_amount")
        if actual_refund != expected_refund:
            raise ValidationError(
                f"returns[{row['return_id']}]: refund is {actual_refund} cents; "
                f"expected {expected_refund}"
            )
        return_line_numbers[row["return_id"]] = int(line["line_no"])

    categories = {row["category"] for row in products}
    for row in tables["promotions"]:
        if row["type"] != "percent_off":
            raise ValidationError(f"promotions: unsupported type {row['type']!r}")
        parse_int(row["value"], "promotions.value", maximum=100)
        start = parse_date(row["start_date"], "promotions.start_date")
        end = parse_date(row["end_date"], "promotions.end_date")
        if start > end:
            raise ValidationError("promotions: start_date must be on or before end_date")
        scope_type = row["scope_type"]
        valid_refs = product_ids if scope_type == "product" else categories
        if scope_type not in {"product", "category"} or row["scope_ref"] not in valid_refs:
            raise ValidationError(f"promotions: invalid scope {scope_type!r}/{row['scope_ref']!r}")

    return SeedData(tables=tables, return_line_numbers=return_line_numbers)

