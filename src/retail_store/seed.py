from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from pathlib import Path

from retail_store.config import DEFAULT_DATABASE_PATH, DEFAULT_DATA_DIR
from retail_store.database import connect, create_schema
from retail_store.validation import SeedData, load_and_validate, parse_cents


def _nullable(value: str) -> str | None:
    return value or None


def _insert_seed_data(connection: sqlite3.Connection, seed: SeedData) -> None:
    tables = seed.tables
    product_rows: dict[str, tuple[str, str]] = {}
    for row in tables["products"]:
        product_rows[row["product_id"]] = (row["product_name"], row["category"])
    connection.executemany(
        "INSERT INTO products(product_id, name, category) VALUES (?, ?, ?)",
        [(product_id, *values) for product_id, values in product_rows.items()],
    )
    connection.executemany(
        """INSERT INTO product_variants
           (sku, product_id, color, size, retail_price_cents)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (
                row["sku"], row["product_id"], _nullable(row["color"]),
                _nullable(row["size"]), parse_cents(row["retail_price"], "retail_price"),
            )
            for row in tables["products"]
        ],
    )
    connection.executemany(
        """INSERT INTO inventory
           (sku, on_hand_qty, reorder_point, reorder_qty) VALUES (?, ?, ?, ?)""",
        [
            (
                row["sku"], int(row["on_hand_qty"]), int(row["reorder_point"]),
                int(row["reorder_qty"]),
            )
            for row in tables["inventory"]
        ],
    )
    connection.executemany(
        """INSERT INTO customers
           (customer_id, name, email, joined_date) VALUES (?, ?, ?, ?)""",
        [
            (row["customer_id"], row["name"], row["email"], row["joined_date"])
            for row in tables["customers"]
        ],
    )
    connection.executemany(
        "INSERT INTO suppliers(supplier_id, name) VALUES (?, ?)",
        [(row["supplier_id"], row["supplier_name"]) for row in tables["suppliers"]],
    )
    connection.executemany(
        """INSERT INTO supplier_catalog
           (supplier_id, product_id, unit_cost_cents, lead_time_days)
           VALUES (?, ?, ?, ?)""",
        [
            (
                row["supplier_id"], row["product_id"],
                parse_cents(row["unit_cost"], "unit_cost"),
                int(row["lead_time_days"]),
            )
            for row in tables["supplier_catalog"]
        ],
    )
    connection.executemany(
        """INSERT INTO orders
           (order_id, order_date, customer_id, order_discount_pct, payment_method)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (
                row["order_id"], row["order_date"], _nullable(row["customer_id"]),
                int(row["order_discount_pct"]), row["payment_method"],
            )
            for row in tables["orders"]
        ],
    )
    connection.executemany(
        """INSERT INTO order_lines
           (order_id, line_no, sku, quantity, unit_price_cents)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (
                row["order_id"], int(row["line_no"]), row["sku"],
                int(row["quantity"]), parse_cents(row["unit_price"], "unit_price"),
            )
            for row in tables["order_lines"]
        ],
    )
    connection.executemany(
        """INSERT INTO returns
           (return_id, return_date, order_id, order_line_no, sku, quantity,
            condition, refund_amount_cents)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                row["return_id"], row["return_date"], row["order_id"],
                seed.return_line_numbers[row["return_id"]], row["sku"],
                int(row["quantity"]), row["condition"],
                parse_cents(row["refund_amount"], "refund_amount"),
            )
            for row in tables["returns"]
        ],
    )
    connection.executemany(
        """INSERT INTO promotions
           (promo_id, description, type, value_pct, scope_type, scope_ref,
            start_date, end_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                row["promo_id"], row["description"], row["type"], int(row["value"]),
                row["scope_type"], row["scope_ref"], row["start_date"], row["end_date"],
            )
            for row in tables["promotions"]
        ],
    )


def seed_database(data_dir: Path, database_path: Path) -> None:
    seed = load_and_validate(data_dir)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_name = tempfile.mkstemp(
        prefix=f".{database_path.name}.", suffix=".tmp", dir=database_path.parent
    )
    os.close(temp_fd)
    temp_path = Path(temp_name)
    try:
        connection = connect(temp_path)
        try:
            create_schema(connection)
            with connection:
                _insert_seed_data(connection, seed)
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if foreign_keys or integrity != "ok":
                raise sqlite3.IntegrityError(
                    f"database checks failed: foreign_keys={foreign_keys}, "
                    f"integrity={integrity}"
                )
        finally:
            connection.close()
        temp_path.replace(database_path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed the retail store SQLite database")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    seed_database(args.data_dir.resolve(), args.database.resolve())
    print(f"Seeded database: {args.database.resolve()}")


if __name__ == "__main__":
    main()
