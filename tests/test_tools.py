from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.database import connect
from retail_store.seed import seed_database
from retail_store.tools import TOOLS, ToolResult, invoke_tool


class ToolLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        seed_database(ROOT / "data", self.database)
        self.connection = connect(self.database)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def test_registry_exposes_complete_tool_metadata(self) -> None:
        self.assertEqual(
            {
                "ring_up_order",
                "process_return",
                "create_promotion",
                "reorder_low_stock",
                "receive_purchase_order",
                "top_products_by_profit_margin",
                "get_stockout_risk",
                "inventory_report",
                "order_details",
                "sales_report",
                "recommend_supplier",
                "cancel_purchase_order",
                "price_quote",
                "purchase_order_report",
            },
            set(TOOLS),
        )
        for name, tool in TOOLS.items():
            self.assertEqual(name, tool.name)
            self.assertTrue(tool.description)
            self.assertEqual("object", tool.parameters["type"])
            self.assertTrue(callable(tool.callable))

    def test_ring_up_order_returns_session_memory(self) -> None:
        result = TOOLS["ring_up_order"].invoke(
            self.connection,
            items=[
                {
                    "product_description": "Classic Tee",
                    "color": "Blue",
                    "size": "Medium",
                    "quantity": 2,
                }
            ],
            customer_name="Sarah Chen",
            payment_method="card",
        )
        self.assertIsInstance(result, ToolResult)
        self.assertTrue(result.ok)
        self.assertEqual("O-1016", result.data["order_id"])
        self.assertEqual("O-1016", result.session_updates["last_order_id"])
        self.assertEqual("Sarah Chen", result.session_updates["last_customer_name"])
        self.assertEqual(["TEE-BLU-M"], result.session_updates["last_skus"])
        self.assertEqual("ring_up_order", result.session_updates["last_action"])

    def test_process_return_handles_good_return(self) -> None:
        result = TOOLS["process_return"].invoke(
            self.connection,
            order_id="O-1006",
            product_description="hoodie",
            color="Navy",
            size="Large",
            condition="good",
        )
        self.assertTrue(result.ok)
        self.assertEqual("54.00", result.data["refund_amount"])
        self.assertEqual("R-2002", result.session_updates["last_return_id"])
        self.assertEqual(["HOOD-NVY-L"], result.session_updates["last_skus"])

    def test_create_promotion_returns_created_promotion(self) -> None:
        result = TOOLS["create_promotion"].invoke(
            self.connection,
            description="Hoodies 20% off",
            percent_off=20,
            scope_type="product",
            scope_ref="P-HOOD",
            start_date="2026-06-20",
            end_date="2026-06-22",
        )
        self.assertTrue(result.ok)
        self.assertEqual("PR-002", result.data["promo_id"])
        self.assertEqual("create_promotion", result.session_updates["last_action"])

    def test_reorder_and_receive_update_purchase_order_memory(self) -> None:
        reorder = TOOLS["reorder_low_stock"].invoke(self.connection)
        self.assertTrue(reorder.ok)
        self.assertEqual("PO-0001", reorder.session_updates["last_purchase_order_id"])
        self.assertEqual("P-TOTE", reorder.data[0]["product_id"])

        receive = TOOLS["receive_purchase_order"].invoke(
            self.connection,
            product_description="Canvas Totes",
            supplier_name="Northwind",
            quantity_ordered=50,
            quantity_received=40,
        )
        self.assertTrue(receive.ok)
        self.assertEqual("partial", receive.data["status"])
        self.assertEqual("PO-0001", receive.session_updates["last_purchase_order_id"])
        self.assertEqual(["TOTE"], receive.session_updates["last_skus"])

    def test_analytics_tools_return_structured_lists(self) -> None:
        margins = TOOLS["top_products_by_profit_margin"].invoke(self.connection)
        risks = TOOLS["get_stockout_risk"].invoke(self.connection)
        self.assertTrue(margins.ok)
        self.assertIsInstance(margins.data, list)
        self.assertEqual(5, len(margins.data))
        self.assertTrue(risks.ok)
        self.assertIsInstance(risks.data, list)
        self.assertEqual("P-TOTE", risks.data[0]["product_id"])

    def test_invalid_input_returns_failure_instead_of_raising(self) -> None:
        result = TOOLS["ring_up_order"].invoke(
            self.connection,
            items=[{"product_description": "Canvas Tote", "quantity": 10}],
        )
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertIn("insufficient inventory", result.error)
        self.assertEqual("ring_up_order", result.session_updates["last_action"])

        missing_argument = invoke_tool("process_return", self.connection, {})
        self.assertFalse(missing_argument.ok)
        self.assertIn("order_id", missing_argument.error)

        unknown = invoke_tool("does_not_exist", self.connection)
        self.assertFalse(unknown.ok)
        self.assertIn("unknown tool", unknown.error)


if __name__ == "__main__":
    unittest.main()
