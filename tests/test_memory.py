from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.memory import SessionMemory


class SessionMemoryTests(unittest.TestCase):
    def test_update_get_and_turn_history(self) -> None:
        memory = SessionMemory()
        memory.update(
            {
                "last_order_id": "O-1016",
                "last_customer_name": "Sarah Chen",
                "last_items": [{"product_description": "Canvas Tote", "quantity": 1}],
                "last_skus": ["TOTE"],
                "last_action": "ring_up_order",
            }
        )
        memory.add_turn("user", "Ring up a tote")
        memory.add_turn("assistant", "Order O-1016 created")

        self.assertEqual("O-1016", memory.get("last_order_id"))
        self.assertEqual(2, len(memory.recent_turns))
        copied_items = memory.get("last_items")
        copied_items[0]["quantity"] = 99
        self.assertEqual(1, memory.last_items[0]["quantity"])

if __name__ == "__main__":
    unittest.main()
