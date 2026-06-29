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
from retail_store.seed import seed_database


class AnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        seed_database(ROOT / "data", self.database)
        self.connection = connect(self.database)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def test_top_products_by_profit_margin_for_may(self) -> None:
        results = top_products_by_profit_margin(self.connection)
        self.assertEqual(
            ["P-TEE", "P-HOOD", "P-SOCK", "P-TOTE", "P-MUG"],
            [row["product_id"] for row in results],
        )
        self.assertEqual(
            {
                "product_id": "P-TEE",
                "product_name": "Classic Tee",
                "units_sold_kept": 30,
                "revenue_kept": "720.00",
                "cost": "300.00",
                "margin": "420.00",
            },
            results[0],
        )
        hoodie = next(row for row in results if row["product_id"] == "P-HOOD")
        self.assertEqual(9, hoodie["units_sold_kept"])
        self.assertEqual("534.00", hoodie["revenue_kept"])
        self.assertEqual("252.00", hoodie["cost"])
        self.assertEqual("282.00", hoodie["margin"])

    def test_stockout_risk_uses_product_velocity_and_variant_thresholds(self) -> None:
        results = get_stockout_risk(self.connection)
        self.assertEqual(1, len(results))
        tote = results[0]
        self.assertEqual("P-TOTE", tote["product_id"])
        self.assertEqual(4, tote["on_hand_total"])
        self.assertEqual(10, tote["monthly_units"])
        self.assertEqual(12.0, tote["days_of_cover"])
        self.assertEqual(
            [
                "at_or_below_reorder_point",
                "fewer_than_14_days_of_cover",
            ],
            tote["reasons"],
        )

    def test_period_return_from_earlier_sale_does_not_create_negative_cost(self) -> None:
        self.connection.execute(
            "UPDATE returns SET return_date = '2026-06-01' WHERE return_id = 'R-2001'"
        )
        results = top_products_by_profit_margin(
            self.connection, "2026-06-01", "2026-06-30"
        )
        hoodie = next(row for row in results if row["product_id"] == "P-HOOD")
        self.assertEqual(0, hoodie["units_sold_kept"])
        self.assertEqual("-54.00", hoodie["revenue_kept"])
        self.assertEqual("0.00", hoodie["cost"])
        self.assertEqual("-54.00", hoodie["margin"])


if __name__ == "__main__":
    unittest.main()
