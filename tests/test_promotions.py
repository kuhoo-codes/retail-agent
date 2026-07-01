from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.database import connect
from retail_store.seed import seed_database
from retail_store.services import create_order, create_promotion


class PromotionCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        seed_database(ROOT / "data", self.database)
        self.connection = connect(self.database)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def test_created_category_promotion_prices_future_sale(self) -> None:
        promotion = create_promotion(
            self.connection,
            "Apparel weekend sale",
            20,
            "category",
            "apparel",
            "2026-06-20",
            "2026-06-22",
        )
        self.assertEqual("PR-002", promotion["promo_id"])

        result = create_order(
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
        self.assertEqual("48.00", result["line_items"][0]["unit_price"])
        self.assertEqual("48.00", result["total_paid"])

        historical = self.connection.execute(
            """SELECT unit_price_cents FROM order_lines
               WHERE order_id = 'O-1004' AND line_no = 1"""
        ).fetchone()[0]
        self.assertEqual(6_000, historical)

    def test_product_name_promotion_scope_aliases_to_product_id(self) -> None:
        promotion = create_promotion(
            self.connection,
            "Hoodie sale",
            20,
            "product",
            "Pullover Hoodie",
            "2026-06-20",
            "2026-06-22",
        )

        self.assertEqual("product", promotion["scope_type"])
        self.assertEqual("P-HOOD", promotion["scope_ref"])

    def test_bare_tote_promotion_scope_aliases_to_product_id(self) -> None:
        promotion = create_promotion(
            self.connection,
            "Tote sale",
            15,
            "product",
            "tote",
            "2026-06-19",
            "2026-06-21",
        )

        self.assertEqual("product", promotion["scope_type"])
        self.assertEqual("P-TOTE", promotion["scope_ref"])

    def test_product_specific_description_overrides_broad_category_scope(self) -> None:
        promotion = create_promotion(
            self.connection,
            "20% off all hoodies",
            20,
            "category",
            "apparel",
            "2026-06-20",
            "2026-06-22",
        )

        self.assertEqual("product", promotion["scope_type"])
        self.assertEqual("P-HOOD", promotion["scope_ref"])


if __name__ == "__main__":
    unittest.main()
