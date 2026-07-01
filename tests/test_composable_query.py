from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.analytics import top_products_by_profit_margin
from retail_store.composable_query import query_store_metrics
from retail_store.database import connect
from retail_store.seed import seed_database


MAY = {"start_date": "2026-05-01", "end_date": "2026-05-31"}


class ComposableQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        seed_database(ROOT / "data", self.database)
        self.connection = connect(self.database)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def query(self, metrics, **kwargs):
        return query_store_metrics(self.connection, metrics, **kwargs)

    def row(self, result, field, value):
        return next(row for row in result["rows"] if row[field] == value)

    def test_revenue_net_by_customer_for_may(self) -> None:
        result = self.query(["revenue_net"], group_by=["customer"], date_range=MAY)
        self.assertEqual("410.20", self.row(result, "customer", "Sarah Chen")["revenue_net"])
        self.assertEqual(5, result["row_count"])

    def test_gross_revenue_and_units_by_variant_for_may(self) -> None:
        result = self.query(
            ["revenue_gross", "units_sold"], group_by=["variant"], date_range=MAY
        )
        blue_medium = self.row(result, "variant", "Classic Tee / Blue / M")
        self.assertEqual("115.00", blue_medium["revenue_gross"])
        self.assertEqual(5, blue_medium["units_sold"])

    def test_margin_by_category_for_may(self) -> None:
        result = self.query(["margin"], group_by=["category"], date_range=MAY)
        self.assertEqual("702.00", self.row(result, "category", "apparel")["margin"])
        self.assertEqual("298.20", self.row(result, "category", "goods")["margin"])

    def test_units_sold_by_sku(self) -> None:
        result = self.query(["units_sold"], group_by=["sku"])
        self.assertEqual(5, self.row(result, "sku", "TEE-BLU-M")["units_sold"])

    def test_filter_customer_name(self) -> None:
        result = self.query(
            ["revenue_net"],
            filters={"customer_name": "Sarah Chen"},
            date_range=MAY,
        )
        self.assertEqual("410.20", result["rows"][0]["revenue_net"])

    def test_filter_walk_in(self) -> None:
        result = self.query(
            ["revenue_net"],
            filters={"customer_type": "walk-in"},
            date_range=MAY,
        )
        self.assertEqual("652.00", result["rows"][0]["revenue_net"])

    def test_filter_payment_method_card(self) -> None:
        result = self.query(
            ["revenue_net"], filters={"payment_method": "card"}, date_range=MAY
        )
        self.assertEqual("1404.20", result["rows"][0]["revenue_net"])

    def test_filter_apparel_grouped_by_product(self) -> None:
        result = self.query(
            ["revenue_net"],
            group_by=["product"],
            filters={"category": "apparel"},
            date_range=MAY,
        )
        self.assertEqual(
            ["Classic Tee", "Pullover Hoodie"],
            [row["product"] for row in result["rows"]],
        )

    def test_top_customers_sort_and_limit(self) -> None:
        result = self.query(
            ["revenue_net"],
            group_by=["customer"],
            date_range=MAY,
            sort_by="revenue_net",
            limit=2,
        )
        self.assertEqual(["Walk-in", "Sarah Chen"], [row["customer"] for row in result["rows"]])

    def test_sales_by_date_for_may(self) -> None:
        result = self.query(["revenue_net"], group_by=["date"], date_range=MAY)
        self.assertEqual("30.00", self.row(result, "date", "2026-05-03")["revenue_net"])

    def test_order_count_by_payment_method(self) -> None:
        result = self.query(
            ["order_count"], group_by=["payment_method"], date_range=MAY
        )
        self.assertEqual(10, self.row(result, "payment_method", "card")["order_count"])
        self.assertEqual(5, self.row(result, "payment_method", "cash")["order_count"])

    def test_average_order_value_by_customer(self) -> None:
        result = self.query(
            ["avg_order_value"], group_by=["customer"], date_range=MAY
        )
        self.assertEqual(
            "136.73",
            self.row(result, "customer", "Sarah Chen")["avg_order_value"],
        )

    def test_unknown_metric_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown metric"):
            self.query(["made_up"])

    def test_unknown_dimension_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown dimension"):
            self.query(["revenue_net"], group_by=["warehouse"])

    def test_unknown_filter_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown filter"):
            self.query(["revenue_net"], filters={"warehouse": "west"})

    def test_invalid_sort_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid sort_by"):
            self.query(["revenue_net"], sort_by="margin")

    def test_legacy_margin_report_is_unchanged(self) -> None:
        legacy = top_products_by_profit_margin(self.connection)
        self.assertEqual("420.00", legacy[0]["margin"])
        self.assertEqual("P-TEE", legacy[0]["product_id"])

    def test_composable_margin_ranking_matches_legacy(self) -> None:
        legacy = top_products_by_profit_margin(self.connection)
        result = self.query(
            ["margin"],
            group_by=["product_id", "product_name"],
            date_range=MAY,
            sort_by="margin",
            limit=5,
        )
        self.assertEqual(
            [row["product_id"] for row in legacy],
            [row["product_id"] for row in result["rows"]],
        )
        self.assertEqual(
            [row["margin"] for row in legacy],
            [row["margin"] for row in result["rows"]],
        )

    def test_include_totals_ignores_limit(self) -> None:
        result = self.query(
            ["revenue_net"],
            group_by=["customer"],
            date_range=MAY,
            sort_by="revenue_net",
            limit=1,
            include_totals=True,
        )
        self.assertEqual("1732.20", result["totals"]["revenue_net"])


if __name__ == "__main__":
    unittest.main()
