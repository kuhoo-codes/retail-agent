from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.agent import RetailAgent
from retail_store.database import connect
from retail_store.seed import seed_database


class PublicPromptEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        seed_database(ROOT / "data", self.database)
        self.connection = connect(self.database)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.agent = RetailAgent(self.connection)

    def tearDown(self) -> None:
        self.env.stop()
        self.connection.close()
        self.temp_dir.cleanup()

    def ask(self, prompt: str) -> str:
        response = self.agent.handle_user_message(prompt)
        self.assertTrue(response.strip())
        self.assertNotIn("Traceback", response)
        return response

    def scalar(self, sql: str, parameters: tuple = ()) -> int:
        return self.connection.execute(sql, parameters).fetchone()[0]

    def test_prompt_1_sale_updates_order_and_inventory(self) -> None:
        response = self.ask(
            "Ring up two Classic Tees, Blue Medium, and one Canvas Tote "
            "for a walk-in paying cash, dated today."
        )
        self.assertIn("Order O-1016", response)
        self.assertIn("$68.00", response)
        self.assertEqual("ring_up_order", self.agent.memory.last_action)
        self.assertEqual(
            20,
            self.scalar("SELECT on_hand_qty FROM inventory WHERE sku='TEE-BLU-M'"),
        )
        self.assertEqual(
            3, self.scalar("SELECT on_hand_qty FROM inventory WHERE sku='TOTE'")
        )
        self.assertIsNone(
            self.connection.execute(
                "SELECT customer_id FROM orders WHERE order_id='O-1016'"
            ).fetchone()[0]
        )

    def test_prompt_2_insufficient_sale_is_rejected_without_writes(self) -> None:
        response = self.ask("Ring up ten Canvas Totes for a walk-in.")
        self.assertIn("insufficient inventory", response)
        self.assertEqual("ring_up_order", self.agent.memory.last_action)
        self.assertEqual(15, self.scalar("SELECT COUNT(*) FROM orders"))
        self.assertEqual(
            4, self.scalar("SELECT on_hand_qty FROM inventory WHERE sku='TOTE'")
        )

    def test_prompt_3_ambiguous_hoodie_requests_color(self) -> None:
        response = self.ask("Ring up a hoodie in medium for Sarah Chen.")
        self.assertIn("clarification", response.casefold())
        self.assertIn("ambiguous", response.casefold())
        self.assertIn("HOOD-GRY-M", response)
        self.assertIn("HOOD-NVY-M", response)
        self.assertEqual(15, self.scalar("SELECT COUNT(*) FROM orders"))

    def test_prompt_4_reorder_creates_eligible_purchase_order(self) -> None:
        response = self.ask(
            "Reorder anything that's below its reorder point, from the best "
            "supplier. Date it today."
        )
        self.assertIn("PO-0001", response)
        self.assertIn("Northwind Supply", response)
        po = self.connection.execute(
            """SELECT supplier_id, product_id, quantity_ordered, status
               FROM purchase_orders WHERE po_id='PO-0001'"""
        ).fetchone()
        self.assertEqual(("SUP-NW", "P-TOTE", 50, "open"), tuple(po))

    def test_prompt_5_receive_creates_partial_po_and_inventory(self) -> None:
        response = self.ask(
            "A purchase order for 50 Canvas Totes from Northwind is open and "
            "40 arrived — receive them, dated today."
        )
        self.assertIn("PO-0001", response)
        self.assertIn("partial", response)
        self.assertEqual(
            44, self.scalar("SELECT on_hand_qty FROM inventory WHERE sku='TOTE'")
        )
        self.assertEqual(
            40,
            self.scalar(
                "SELECT quantity_received FROM purchase_orders WHERE po_id='PO-0001'"
            ),
        )

    def test_prompt_6_good_return_refunds_and_restocks(self) -> None:
        response = self.ask(
            "Sarah Chen is returning one Navy Large hoodie from order O-1006. "
            "It's in good condition."
        )
        self.assertIn("Refund: $54.00", response)
        self.assertIn("increased by 1", response)
        self.assertEqual(
            7,
            self.scalar(
                "SELECT on_hand_qty FROM inventory WHERE sku='HOOD-NVY-L'"
            ),
        )
        self.assertEqual(2, self.scalar("SELECT COUNT(*) FROM returns"))

    def test_prompt_7_damaged_return_does_not_restock(self) -> None:
        response = self.ask(
            "Return the Canvas Tote from order O-1006 — it came back damaged."
        )
        self.assertIn("Refund: $16.20", response)
        self.assertIn("not increased", response)
        self.assertEqual(
            4, self.scalar("SELECT on_hand_qty FROM inventory WHERE sku='TOTE'")
        )

    def test_prompt_8_compound_promotion_and_sale(self) -> None:
        response = self.ask(
            "Put all hoodies on 20% off from 2026-06-20 to 2026-06-22, "
            "then ring up one Gray Medium hoodie dated 2026-06-21 and tell me "
            "the price."
        )
        self.assertIn("Promotion PR-002", response)
        self.assertIn("Order O-1016", response)
        self.assertIn("$48.00", response)
        self.assertEqual(2, self.scalar("SELECT COUNT(*) FROM promotions"))
        self.assertEqual(
            4_800,
            self.scalar(
                """SELECT unit_price_cents FROM order_lines
                   WHERE order_id='O-1016' AND sku='HOOD-GRY-M'"""
            ),
        )

    def test_prompt_9_margin_answer_uses_analytics_tool(self) -> None:
        response = self.ask(
            "What were my top five products by profit margin last month?"
        )
        self.assertIn("Top products by profit margin", response)
        self.assertIn("Classic Tee", response)
        self.assertIn("$420.00", response)
        self.assertEqual(
            "top_products_by_profit_margin", self.agent.memory.last_action
        )

    def test_prompt_10_stockout_answer_uses_analytics_tool(self) -> None:
        response = self.ask("What's about to stock out?")
        self.assertIn("Stockout risk", response)
        self.assertIn("Canvas Tote", response)
        self.assertIn("12.0 days of cover", response)
        self.assertEqual("get_stockout_risk", self.agent.memory.last_action)


if __name__ == "__main__":
    unittest.main()

