from __future__ import annotations

import csv
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.seed import seed_database
from retail_store.database import connect
from retail_store.validation import ValidationError


class SeedDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data = self.root / "data"
        shutil.copytree(ROOT / "data", self.data)
        self.database = self.root / "retail.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def mutate_csv(self, name: str, mutate) -> None:
        path = self.data / name
        with path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            fieldnames = reader.fieldnames
            rows = list(reader)
        mutate(rows)
        with path.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_seeds_expected_entities_and_enforces_foreign_keys(self) -> None:
        seed_database(self.data, self.database)
        connection = connect(self.database)
        try:
            expected_counts = {
                "products": 5,
                "product_variants": 13,
                "inventory": 13,
                "customers": 4,
                "suppliers": 2,
                "supplier_catalog": 7,
                "purchase_orders": 0,
                "orders": 15,
                "order_lines": 22,
                "returns": 1,
                "promotions": 1,
            }
            for table, expected in expected_counts.items():
                actual = connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                self.assertEqual(expected, actual, table)
            expected_tables = set(expected_counts)
            actual_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertEqual(expected_tables, actual_tables)
            returned_line = connection.execute(
                """SELECT r.order_id, r.order_line_no, r.sku, ol.sku
                   FROM returns AS r
                   JOIN order_lines AS ol
                     ON ol.order_id = r.order_id
                    AND ol.line_no = r.order_line_no
                   WHERE r.return_id = 'R-2001'"""
            ).fetchone()
            self.assertEqual(("O-1006", 1, "HOOD-NVY-L", "HOOD-NVY-L"), tuple(returned_line))
            self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            connection.close()

    def test_database_rejects_order_line_with_unknown_sku(self) -> None:
        seed_database(self.data, self.database)
        connection = connect(self.database)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO order_lines
                       (order_id, line_no, sku, quantity, unit_price_cents)
                       VALUES ('O-1001', 99, 'UNKNOWN', 1, 100)"""
                )
        finally:
            connection.close()

    def test_rejects_orphan_order_line_sku(self) -> None:
        self.mutate_csv(
            "order_lines.csv", lambda rows: rows[0].update(sku="UNKNOWN")
        )
        with self.assertRaisesRegex(ValidationError, "orphan row"):
            seed_database(self.data, self.database)

    def test_rejects_inconsistent_product_metadata(self) -> None:
        self.mutate_csv(
            "products.csv", lambda rows: rows[1].update(product_name="Different Tee")
        )
        with self.assertRaisesRegex(ValidationError, "inconsistent product metadata"):
            seed_database(self.data, self.database)

    def test_rejects_invalid_promotion_window(self) -> None:
        self.mutate_csv(
            "promotions.csv", lambda rows: rows[0].update(end_date="2026-04-30")
        )
        with self.assertRaisesRegex(ValidationError, "start_date"):
            seed_database(self.data, self.database)

    def test_rejects_incorrect_refund(self) -> None:
        self.mutate_csv(
            "returns.csv", lambda rows: rows[0].update(refund_amount="60.00")
        )
        with self.assertRaisesRegex(ValidationError, "expected 5400"):
            seed_database(self.data, self.database)


if __name__ == "__main__":
    unittest.main()
