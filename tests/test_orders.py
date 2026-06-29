from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.database import connect
from retail_store.matching import SkuAmbiguityError
from retail_store.seed import seed_database
from retail_store.services import InsufficientInventoryError, create_order


class CreateOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        seed_database(ROOT / "data", self.database)
        self.connection = connect(self.database)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def inventory(self, sku: str) -> int:
        return self.connection.execute(
            "SELECT on_hand_qty FROM inventory WHERE sku = ?", (sku,)
        ).fetchone()["on_hand_qty"]

    def order_count(self) -> int:
        return self.connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

    def test_walk_in_cash_order_creates_lines_and_decrements_inventory(self) -> None:
        result = create_order(
            self.connection,
            [
                {
                    "product_description": "Classic Tee",
                    "color": "Blue",
                    "size": "M",
                    "quantity": 2,
                },
                {"product_description": "Canvas Tote", "quantity": 1},
            ],
            customer_name="walk-in",
            payment_method="cash",
            order_date="2026-06-19",
        )

        self.assertEqual("O-1016", result["order_id"])
        self.assertEqual("walk-in", result["customer_id"])
        self.assertEqual("cash", result["payment_method"])
        self.assertEqual("68.00", result["subtotal_before_order_discount"])
        self.assertEqual("68.00", result["total_paid"])
        self.assertEqual(
            [
                {
                    "sku": "TEE-BLU-M",
                    "name": "Classic Tee",
                    "quantity": 2,
                    "unit_price": "25.00",
                    "line_total_after_order_discount": "50.00",
                },
                {
                    "sku": "TOTE",
                    "name": "Canvas Tote",
                    "quantity": 1,
                    "unit_price": "18.00",
                    "line_total_after_order_discount": "18.00",
                },
            ],
            result["line_items"],
        )
        self.assertEqual({"TEE-BLU-M": 20, "TOTE": 3}, result["remaining_inventory"])
        self.assertEqual(20, self.inventory("TEE-BLU-M"))
        self.assertEqual(3, self.inventory("TOTE"))

        order = self.connection.execute(
            "SELECT customer_id FROM orders WHERE order_id = 'O-1016'"
        ).fetchone()
        self.assertIsNone(order["customer_id"])

    def test_insufficient_canvas_totes_rejects_order(self) -> None:
        before_count = self.order_count()
        with self.assertRaisesRegex(
            InsufficientInventoryError, "requested 10, available 4"
        ):
            create_order(
                self.connection,
                [{"product_description": "Canvas Tote", "quantity": 10}],
            )
        self.assertEqual(before_count, self.order_count())
        self.assertEqual(4, self.inventory("TOTE"))

    def test_medium_hoodie_for_sarah_is_ambiguous_without_color(self) -> None:
        with self.assertRaises(SkuAmbiguityError):
            create_order(
                self.connection,
                [
                    {
                        "product_description": "hoodie",
                        "size": "medium",
                        "quantity": 1,
                    }
                ],
                customer_name="Sarah Chen",
            )
        self.assertEqual(15, self.order_count())

    def test_navy_medium_hoodie_for_sarah_succeeds(self) -> None:
        result = create_order(
            self.connection,
            [
                {
                    "product_description": "hoodie",
                    "color": "navy",
                    "size": "medium",
                    "quantity": 1,
                }
            ],
            customer_name="sArAh ChEn",
        )
        self.assertEqual("C-001", result["customer_id"])
        self.assertEqual("HOOD-NVY-M", result["line_items"][0]["sku"])
        self.assertEqual(7, self.inventory("HOOD-NVY-M"))

    def test_active_promotion_price_is_stored_before_order_discount(self) -> None:
        result = create_order(
            self.connection,
            [
                {
                    "product_description": "tee",
                    "color": "blue",
                    "size": "small",
                    "quantity": 1,
                }
            ],
            order_date="2026-05-07",
            order_discount_pct=10,
        )
        stored_price = self.connection.execute(
            """SELECT unit_price_cents
               FROM order_lines
               WHERE order_id = ? AND line_no = 1""",
            (result["order_id"],),
        ).fetchone()["unit_price_cents"]
        self.assertEqual(2_000, stored_price)
        self.assertEqual("20.00", result["line_items"][0]["unit_price"])
        self.assertEqual("18.00", result["line_items"][0]["line_total_after_order_discount"])
        self.assertEqual("18.00", result["total_paid"])

    def test_whole_order_rolls_back_when_one_line_lacks_stock(self) -> None:
        before_tee = self.inventory("TEE-BLU-M")
        before_tote = self.inventory("TOTE")
        before_count = self.order_count()
        with self.assertRaises(InsufficientInventoryError):
            create_order(
                self.connection,
                [
                    {
                        "product_description": "Classic Tee",
                        "color": "Blue",
                        "size": "M",
                        "quantity": 1,
                    },
                    {"product_description": "Canvas Tote", "quantity": 10},
                ],
            )
        self.assertEqual(before_count, self.order_count())
        self.assertEqual(before_tee, self.inventory("TEE-BLU-M"))
        self.assertEqual(before_tote, self.inventory("TOTE"))


if __name__ == "__main__":
    unittest.main()
