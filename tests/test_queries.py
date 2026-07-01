from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from retail_store.database import connect
from retail_store.queries import (
    cancel_purchase_order,
    customer_report,
    inventory_report,
    order_report,
    order_details,
    recommend_supplier,
    sales_report,
)
from retail_store.seed import seed_database
from retail_store.services import reorder_low_stock
from retail_store.services import create_order


ROOT = Path(__file__).resolve().parents[1]


class QueryCapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "retail.db"
        seed_database(ROOT / "data", self.db)
        self.connection = connect(self.db)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp.cleanup()

    def test_inventory_by_product_and_all_skus(self) -> None:
        tote = inventory_report(self.connection, product_description="Canvas Tote")
        self.assertEqual(4, tote[0]["on_hand_qty"])
        self.assertEqual(12.0, tote[0]["days_of_cover"])
        self.assertGreater(len(inventory_report(self.connection)), 1)

    def test_order_details_include_customer_price_and_total(self) -> None:
        order = order_details(self.connection, "O-1006")
        self.assertEqual("Sarah Chen", order["customer"])
        self.assertEqual("54.00", order["lines"][0]["unit_price"])

    def test_sales_report_and_supplier_recommendation(self) -> None:
        report = sales_report(self.connection, product_description="Classic Tee")
        self.assertEqual("Classic Tee", report[0]["product_name"])
        suppliers = recommend_supplier(self.connection, "Ceramic Mug")
        self.assertTrue(suppliers)
        self.assertIn("lead_time_days", suppliers[0])

    def test_customer_and_order_reports_cover_common_questions(self) -> None:
        customers = customer_report(self.connection)
        self.assertEqual(
            ["Marcus Reed", "Priya Patel", "Sarah Chen", "Tom Becker"],
            [row["name"] for row in customers],
        )

        sarah = customer_report(
            self.connection,
            start_date="2026-05-01",
            end_date="2026-05-31",
            customer_name="Sarah Chen",
        )
        self.assertEqual("464.20", sarah[0]["total_spent"])

        walk_ins = order_report(
            self.connection,
            start_date="2026-05-01",
            end_date="2026-05-31",
            walk_in=True,
        )
        self.assertEqual(5, len(walk_ins))

        discounted = order_report(
            self.connection,
            start_date="2026-05-01",
            end_date="2026-05-31",
            order_discount_only=True,
        )
        self.assertEqual(["O-1006"], [row["order_id"] for row in discounted])

        cash = order_report(
            self.connection,
            start_date="2026-05-01",
            end_date="2026-05-31",
            payment_method="cash",
        )
        self.assertEqual("328.00", f"{sum(float(row['total_paid']) for row in cash):.2f}")

        payment_summary = order_report(
            self.connection,
            start_date="2026-05-01",
            end_date="2026-05-31",
            group_by="payment_method",
        )
        self.assertEqual(
            {"card": "1458.20", "cash": "328.00"},
            {row["payment_method"]: row["total_revenue"] for row in payment_summary},
        )

    def test_cancel_open_purchase_order(self) -> None:
        po = reorder_low_stock(self.connection)[0]
        result = cancel_purchase_order(self.connection, po["po_id"])
        self.assertEqual("cancelled", result["status"])

    def test_reorder_does_not_duplicate_open_po(self) -> None:
        self.assertEqual(1, len(reorder_low_stock(self.connection)))
        self.assertEqual([], reorder_low_stock(self.connection))

    def test_customer_names_allow_unique_typo_and_prefix(self) -> None:
        for name in ("Sara Chen", "Sarah"):
            result = create_order(
                self.connection,
                [{"product_description": "Navy Large hoodie", "quantity": 1}],
                customer_name=name,
            )
            self.assertEqual("C-001", result["customer_id"])


if __name__ == "__main__":
    unittest.main()
