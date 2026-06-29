from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.analytics import (
    get_stockout_risk,
    top_products_by_profit_margin,
)
from retail_store.database import connect
from retail_store.matching import SkuAmbiguityError
from retail_store.seed import seed_database
from retail_store.services import (
    InsufficientInventoryError,
    create_order,
    create_promotion,
    process_return,
    receive_purchase_order,
    reorder_low_stock,
)


class PublicPromptLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        seed_database(ROOT / "data", self.database)
        self.connection = connect(self.database)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def test_prompt_1_ring_up_tees_and_tote(self) -> None:
        result = create_order(
            self.connection,
            [
                {
                    "product_description": "Classic Tees",
                    "color": "Blue",
                    "size": "Medium",
                    "quantity": 2,
                },
                {"product_description": "Canvas Tote", "quantity": 1},
            ],
            customer_name="walk-in",
            payment_method="cash",
        )
        self.assertEqual("68.00", result["total_paid"])

    def test_prompt_2_reject_ten_totes(self) -> None:
        with self.assertRaises(InsufficientInventoryError):
            create_order(
                self.connection,
                [{"product_description": "Canvas Totes", "quantity": 10}],
            )

    def test_prompt_3_medium_hoodie_is_ambiguous(self) -> None:
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

    def test_prompt_4_reorder_low_stock(self) -> None:
        results = reorder_low_stock(self.connection)
        self.assertEqual(["P-TOTE"], [row["product_id"] for row in results])
        self.assertEqual("SUP-NW", results[0]["supplier_id"])

    def test_prompt_5_receive_tote_purchase_order(self) -> None:
        result = receive_purchase_order(
            self.connection,
            "Canvas Totes",
            "Northwind",
            50,
            40,
        )
        self.assertEqual("partial", result["status"])
        self.assertEqual(44, result["remaining_inventory"])

    def test_prompt_6_good_hoodie_return(self) -> None:
        result = process_return(
            self.connection,
            "O-1006",
            product_description="hoodie",
            color="Navy",
            size="Large",
            condition="good",
        )
        self.assertEqual("54.00", result["refund_amount"])
        self.assertEqual(1, result["inventory_increase"])

    def test_prompt_7_damaged_tote_return(self) -> None:
        result = process_return(
            self.connection,
            "O-1006",
            product_description="Canvas Tote",
            condition="damaged",
        )
        self.assertEqual("16.20", result["refund_amount"])
        self.assertEqual(0, result["inventory_increase"])

    def test_prompt_8_promotion_then_hoodie_sale(self) -> None:
        create_promotion(
            self.connection,
            "Hoodies 20% off",
            20,
            "product",
            "P-HOOD",
            "2026-06-20",
            "2026-06-22",
        )
        order = create_order(
            self.connection,
            [
                {
                    "product_description": "hoodie",
                    "color": "Gray",
                    "size": "Medium",
                    "quantity": 1,
                }
            ],
            order_date="2026-06-21",
        )
        self.assertEqual("48.00", order["line_items"][0]["unit_price"])

    def test_prompt_9_top_five_products_by_margin(self) -> None:
        results = top_products_by_profit_margin(self.connection)
        self.assertEqual(5, len(results))
        self.assertEqual("P-TEE", results[0]["product_id"])
        self.assertGreater(
            float(results[0]["margin"]), float(results[1]["margin"])
        )

    def test_prompt_10_stockout_risk(self) -> None:
        results = get_stockout_risk(self.connection)
        self.assertEqual(["P-TOTE"], [row["product_id"] for row in results])


if __name__ == "__main__":
    unittest.main()
