from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.agent import RetailAgent
from retail_store.cli import run_cli
from retail_store.composable_query import query_store_metrics
from retail_store.database import connect
from retail_store.seed import seed_database
from retail_store.tools import TOOLS


MAY = {"start_date": "2026-05-01", "end_date": "2026-05-31"}


class FinalAssignmentAndFeedbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        seed_database(ROOT / "data", self.database)
        self.connection = connect(self.database)
        self.env_patch = patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()
        self.agent = RetailAgent(self.connection)

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.connection.close()
        self.temp_dir.cleanup()

    def inventory(self, sku: str) -> int:
        return self.connection.execute(
            "SELECT on_hand_qty FROM inventory WHERE sku=?", (sku,)
        ).fetchone()[0]

    def test_01_walk_in_cash_sale_end_to_end(self) -> None:
        tee_before, tote_before = self.inventory("TEE-BLU-M"), self.inventory("TOTE")
        response = self.agent.handle_user_message(
            "Ring up two Classic Tees, Blue Medium, and one Canvas Tote "
            "for a walk-in paying cash, dated today."
        )
        self.assertTrue(response)
        self.assertIn("$68.00", response)
        order = self.connection.execute(
            "SELECT * FROM orders WHERE order_id='O-1016'"
        ).fetchone()
        self.assertIsNone(order["customer_id"])
        self.assertEqual("cash", order["payment_method"])
        self.assertEqual(tee_before - 2, self.inventory("TEE-BLU-M"))
        self.assertEqual(tote_before - 1, self.inventory("TOTE"))

    def test_02_insufficient_sale_is_atomic(self) -> None:
        orders_before = self.connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        tote_before = self.inventory("TOTE")
        response = self.agent.handle_user_message(
            "Ring up ten Canvas Totes for a walk-in."
        )
        self.assertIn("insufficient inventory", response)
        self.assertNotIn("Traceback", response)
        self.assertEqual(
            orders_before,
            self.connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        )
        self.assertEqual(tote_before, self.inventory("TOTE"))

    def test_03_ambiguous_hoodie_does_not_guess(self) -> None:
        response = self.agent.handle_user_message(
            "Ring up a hoodie in medium for Sarah Chen."
        )
        self.assertIn("ambiguous", response)
        self.assertIn("HOOD-GRY-M", response)
        self.assertIn("HOOD-NVY-M", response)
        self.assertIsNone(
            self.connection.execute(
                "SELECT 1 FROM orders WHERE order_id='O-1016'"
            ).fetchone()
        )

    def test_04_reorder_uses_eligible_lowest_cost_supplier(self) -> None:
        response = self.agent.handle_user_message(
            "Reorder anything that's below its reorder point, from the best "
            "supplier. Date it today."
        )
        self.assertTrue(response)
        po = self.connection.execute(
            """SELECT po.*, sc.unit_cost_cents, sc.lead_time_days
               FROM purchase_orders po
               JOIN supplier_catalog sc
                 ON sc.supplier_id=po.supplier_id AND sc.product_id=po.product_id"""
        ).fetchone()
        self.assertEqual("P-TOTE", po["product_id"])
        self.assertLessEqual(po["lead_time_days"], 10)
        eligible_min = self.connection.execute(
            """SELECT MIN(unit_cost_cents) FROM supplier_catalog
               WHERE product_id=? AND lead_time_days <= 10""",
            (po["product_id"],),
        ).fetchone()[0]
        self.assertEqual(eligible_min, po["unit_cost_cents"])

    def test_05_receive_partial_purchase_order(self) -> None:
        before = self.inventory("TOTE")
        response = self.agent.handle_user_message(
            "A purchase order for 50 Canvas Totes from Northwind is open and "
            "40 arrived — receive them, dated today."
        )
        self.assertTrue(response)
        po = self.connection.execute("SELECT * FROM purchase_orders").fetchone()
        self.assertEqual(40, po["quantity_received"])
        self.assertEqual("partial", po["status"])
        self.assertEqual(before + 40, self.inventory("TOTE"))

    def test_06_good_return_uses_paid_price_and_stores_line(self) -> None:
        before = self.inventory("HOOD-NVY-L")
        response = self.agent.handle_user_message(
            "Sarah Chen is returning one Navy Large hoodie from order O-1006. "
            "It's in good condition."
        )
        self.assertIn("$54.00", response)
        row = self.connection.execute(
            "SELECT * FROM returns WHERE return_id='R-2002'"
        ).fetchone()
        self.assertEqual("HOOD-NVY-L", row["sku"])
        self.assertEqual(1, row["order_line_no"])
        self.assertEqual(5400, row["refund_amount_cents"])
        self.assertEqual(before + 1, self.inventory("HOOD-NVY-L"))

    def test_07_damaged_return_does_not_restock(self) -> None:
        before = self.inventory("TOTE")
        response = self.agent.handle_user_message(
            "Return the Canvas Tote from order O-1006 — it came back damaged."
        )
        self.assertIn("$16.20", response)
        row = self.connection.execute(
            "SELECT * FROM returns WHERE return_id='R-2002'"
        ).fetchone()
        self.assertEqual(1620, row["refund_amount_cents"])
        self.assertEqual("damaged", row["condition"])
        self.assertEqual(before, self.inventory("TOTE"))

    def test_08_promotion_then_sale_uses_best_single_price(self) -> None:
        response = self.agent.handle_user_message(
            "Put all hoodies on 20% off from 2026-06-20 to 2026-06-22, then "
            "ring up one Gray Medium hoodie dated 2026-06-21 and tell me the price."
        )
        self.assertIn("$48.00", response)
        promo = self.connection.execute(
            "SELECT * FROM promotions WHERE promo_id='PR-002'"
        ).fetchone()
        self.assertEqual(("2026-06-20", "2026-06-22"), (promo["start_date"], promo["end_date"]))
        line = self.connection.execute(
            "SELECT * FROM order_lines WHERE order_id='O-1016'"
        ).fetchone()
        self.assertEqual(4800, line["unit_price_cents"])

    def test_09_legacy_margin_report_is_deterministic(self) -> None:
        response = self.agent.handle_user_message(
            "What were my top five products by profit margin last month?"
        )
        self.assertIn("$420.00", response)
        result = TOOLS["top_products_by_profit_margin"].invoke(self.connection)
        self.assertTrue(result.ok)
        self.assertEqual("P-TEE", result.data[0]["product_id"])

    def test_10_stockout_risk_is_deterministic(self) -> None:
        response = self.agent.handle_user_message("What's about to stock out?")
        self.assertIn("Canvas Tote", response)
        result = TOOLS["get_stockout_risk"].invoke(self.connection)
        self.assertTrue(result.ok)
        self.assertEqual(["P-TOTE"], [row["product_id"] for row in result.data])

    def test_11_to_18_composable_queries(self) -> None:
        cases = (
            ("How much did Sarah Chen spend last month?", "Sarah Chen", "$410.20"),
            ("Show sales by variant last month.", "Variant", "Units Sold"),
            ("Revenue by customer in May.", "Walk-in", "Net Revenue"),
            ("Top customers by spend in May.", "Walk-in", "$652.00"),
            ("Card vs cash sales last month.", "card", "cash"),
            ("Sales for apparel by variant in May.", "Classic Tee", "Pullover Hoodie"),
            ("Units sold by SKU.", "TEE-BLU-M", "Units Sold"),
            ("Margin by category last month.", "apparel", "$702.00"),
        )
        for prompt, expected_a, expected_b in cases:
            with self.subTest(prompt=prompt):
                response = self.agent.handle_user_message(prompt)
                self.assertIn(expected_a, response)
                self.assertIn(expected_b, response)
                self.assertNotIn("OPENAI_API_KEY", response)

    def test_19_invalid_metric_is_safe(self) -> None:
        result = TOOLS["query_store_metrics"].invoke(
            self.connection, metrics=["revenue; DROP TABLE orders"]
        )
        self.assertFalse(result.ok)
        self.assertIn("unknown metric", result.error)
        self.assertIsNotNone(
            self.connection.execute(
                "SELECT name FROM sqlite_master WHERE name='orders'"
            ).fetchone()
        )

    def test_20_invalid_dimensions_and_filters_are_safe(self) -> None:
        for arguments, message in (
            ({"metrics": ["revenue_net"], "group_by": ["secret"]}, "unknown dimension"),
            (
                {
                    "metrics": ["revenue_net"],
                    "filters": {"1=1; DROP TABLE orders": "x"},
                },
                "unknown filter",
            ),
        ):
            with self.subTest(arguments=arguments):
                result = TOOLS["query_store_metrics"].invoke(
                    self.connection, **arguments
                )
                self.assertFalse(result.ok)
                self.assertIn(message, result.error)

    def test_21_no_api_key_handles_public_prompts(self) -> None:
        self.assertFalse(self.agent.llm_client.available)
        response = self.agent.handle_user_message("What's about to stock out?")
        self.assertIn("Stockout risk", response)
        self.assertNotIn("Unable to run", response)

    def test_22_session_memory_refunds_last_single_item(self) -> None:
        sale = self.agent.handle_user_message(
            "Ring up one Navy Medium hoodie for Sarah Chen."
        )
        self.assertIn("O-1016", sale)
        returned = self.agent.handle_user_message("now refund that")
        self.assertIn("Return R-2002", returned)
        row = self.connection.execute(
            "SELECT order_id, sku FROM returns WHERE return_id='R-2002'"
        ).fetchone()
        self.assertEqual(("O-1016", "HOOD-NVY-M"), tuple(row))

    def test_23_cli_reset_reseeds_and_clears_session(self) -> None:
        self.connection.close()
        commands = iter(
            [
                "Ring up one Navy Medium hoodie for Sarah Chen.",
                "reset",
                "now refund that",
                "exit",
            ]
        )
        output: list[str] = []
        with patch("retail_store.cli.load_dotenv"):
            code = run_cli(
                database_path=self.database,
                data_dir=ROOT / "data",
                input_fn=lambda _prompt: next(commands),
                output_fn=output.append,
            )
        self.connection = connect(self.database)
        self.assertEqual(0, code)
        self.assertIn("Store data and session memory reset.", output)
        self.assertTrue(any("need the order and item" in line for line in output))
        self.assertIsNone(
            self.connection.execute(
                "SELECT 1 FROM orders WHERE order_id='O-1016'"
            ).fetchone()
        )

    def test_24_documentation_states_tool_and_sql_boundaries(self) -> None:
        documentation = "\n".join(
            (ROOT / name).read_text(encoding="utf-8")
            for name in ("README.md", "WRITEUP.md", "docs/TOOLS.md")
        ).casefold()
        self.assertIn("tool/action layer", documentation)
        self.assertIn("query_store_metrics", documentation)
        self.assertIn("no model- or user-authored sql", documentation)
        self.assertIn("never calculates", documentation)

    def test_25_submission_hygiene(self) -> None:
        for path in (
            "var/retail_store.db",
            ".env",
            "src/retail_store/__pycache__/agent.pyc",
            ".pytest_cache/example",
        ):
            result = subprocess.run(
                ["git", "check-ignore", "-q", path],
                cwd=ROOT,
                check=False,
            )
            self.assertEqual(0, result.returncode, path)
        tracked_env = subprocess.run(
            ["git", "ls-files", "--error-unmatch", ".env"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(0, tracked_env.returncode)
        data_diff = subprocess.run(
            ["git", "diff", "--quiet", "--", "data"],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(0, data_diff.returncode)

    def test_query_function_revenue_matches_tool(self) -> None:
        direct = query_store_metrics(
            self.connection,
            ["revenue_net"],
            group_by=["customer"],
            date_range=MAY,
        )
        tool = TOOLS["query_store_metrics"].invoke(
            self.connection,
            metrics=["revenue_net"],
            group_by=["customer"],
            date_range=MAY,
        )
        self.assertTrue(tool.ok)
        self.assertEqual(direct, tool.data)


if __name__ == "__main__":
    unittest.main()
