from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.intent_parser import parse_intent_without_llm
from retail_store.memory import SessionMemory


class IntentParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.memory = SessionMemory()

    def parse(self, text: str) -> dict:
        return parse_intent_without_llm(text, self.memory)

    def test_now_refund_that_uses_session_order_and_sku(self) -> None:
        self.memory.update(
            {"last_order_id": "O-1016", "last_skus": ["TOTE"]}
        )
        parsed = self.parse("now refund that")
        self.assertEqual("process_return", parsed["tool_name"])
        self.assertEqual("O-1016", parsed["arguments"]["order_id"])
        self.assertEqual("TOTE", parsed["arguments"]["sku"])

    def test_same_customer_is_reused_for_sale(self) -> None:
        self.memory.update({"last_customer_name": "Sarah Chen"})
        parsed = self.parse("sell one Canvas Tote to the same customer")
        self.assertEqual("ring_up_order", parsed["tool_name"])
        self.assertEqual("Sarah Chen", parsed["arguments"]["customer_name"])

    def test_public_prompt_tool_mapping_and_core_normalization(self) -> None:
        prompts = [
            (
                "Ring up two Classic Tees, Blue Medium, and one Canvas Tote "
                "for a walk-in paying cash, dated today.",
                "ring_up_order",
            ),
            ("Ring up ten Canvas Totes for a walk-in.", "ring_up_order"),
            ("Ring up a hoodie in medium for Sarah Chen.", "ring_up_order"),
            (
                "Reorder anything that's below its reorder point, from the best "
                "supplier. Date it today.",
                "reorder_low_stock",
            ),
            (
                "A purchase order for 50 Canvas Totes from Northwind is open "
                "and 40 arrived — receive them, dated today.",
                "receive_purchase_order",
            ),
            (
                "Sarah Chen is returning one Navy Large hoodie from order O-1006. "
                "It's in good condition.",
                "process_return",
            ),
            (
                "Return the Canvas Tote from order O-1006 — it came back damaged.",
                "process_return",
            ),
            (
                "Put all hoodies on 20% off from 2026-06-20 to 2026-06-22, "
                "then ring up one Gray Medium hoodie dated 2026-06-21 and tell "
                "me the price.",
                "create_promotion",
            ),
            (
                "What were my top five products by profit margin last month?",
                "top_products_by_profit_margin",
            ),
            ("What's about to stock out?", "get_stockout_risk"),
        ]
        for prompt, expected_tool in prompts:
            with self.subTest(prompt=prompt):
                self.assertEqual(expected_tool, self.parse(prompt)["tool_name"])

        order = self.parse(
            "Ring up two Classic Tees, Blue Medium, and one Canvas Tote "
            "for a walk-in paying cash, dated today."
        )
        self.assertIsNone(order["arguments"]["customer_name"])
        self.assertEqual("cash", order["arguments"]["payment_method"])
        self.assertEqual("2026-06-19", order["arguments"]["order_date"])
        self.assertEqual("M", order["arguments"]["items"][0]["size"])

        analytics = self.parse(
            "What were my top five products by profit margin last month?"
        )
        self.assertEqual("2026-05-01", analytics["arguments"]["start_date"])
        self.assertEqual("2026-05-31", analytics["arguments"]["end_date"])

    def test_ambiguous_medium_hoodie_still_maps_to_order_tool(self) -> None:
        parsed = self.parse("Ring up a hoodie in medium for Sarah Chen.")
        self.assertEqual("ring_up_order", parsed["tool_name"])
        self.assertEqual("M", parsed["arguments"]["items"][0]["size"])
        self.assertNotIn("color", parsed["arguments"]["items"][0])

    def test_condition_normalization(self) -> None:
        damaged = self.parse(
            "Return the Canvas Tote from order O-1006; it came back damaged."
        )
        good = self.parse(
            "Return one Navy Large hoodie from order O-1006 in good condition."
        )
        self.assertEqual("damaged", damaged["arguments"]["condition"])
        self.assertEqual("good", good["arguments"]["condition"])
        self.assertEqual("L", good["arguments"]["size"])

    def test_low_confidence_requests_clarification(self) -> None:
        parsed = self.parse("Can you help me with the shop?")
        self.assertIsNone(parsed["tool_name"])
        self.assertEqual("low", parsed["confidence"])
        self.assertIn("clarify", parsed["reason"].casefold())


if __name__ == "__main__":
    unittest.main()
