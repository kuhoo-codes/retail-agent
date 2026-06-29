from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.agent import RetailAgent, SYSTEM_PROMPT
from retail_store.database import connect
from retail_store.llm_client import LLMClientError, LLMDecision
from retail_store.seed import seed_database


class FailingLLMClient:
    available = True

    def select_tool(self, *args, **kwargs):
        raise LLMClientError("simulated provider failure")


class UnknownToolLLMClient:
    available = True

    def select_tool(self, *args, **kwargs):
        return LLMDecision("invented_store_math", {})


class RetailAgentFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        seed_database(ROOT / "data", self.database)
        self.connection = connect(self.database)
        self.key_patch = patch.dict(os.environ, {}, clear=True)
        self.key_patch.start()
        self.agent = RetailAgent(self.connection)

    def tearDown(self) -> None:
        self.key_patch.stop()
        self.connection.close()
        self.temp_dir.cleanup()

    def test_system_prompt_contains_business_rule_boundaries(self) -> None:
        self.assertIn("Use tools for all store operations", SYSTEM_PROMPT)
        self.assertIn("Never compute prices", SYSTEM_PROMPT)
        self.assertIn("Today is 2026-06-19", SYSTEM_PROMPT)
        self.assertIn("Last month means May 2026", SYSTEM_PROMPT)

    def test_agent_without_api_key_rings_up_public_prompt_one(self) -> None:
        answer = self.agent.handle_user_message(
            "Ring up two Classic Tees, Blue Medium, and one Canvas Tote "
            "for a walk-in paying cash, dated today."
        )
        self.assertIn("Order O-1016 completed", answer)
        self.assertIn("Total paid: $68.00", answer)
        self.assertEqual("O-1016", self.agent.memory.last_order_id)
        self.assertEqual("ring_up_order", self.agent.memory.last_action)

    def test_agent_remembers_single_item_order_for_refund_followup(self) -> None:
        order_answer = self.agent.handle_user_message(
            "Ring up one Canvas Tote for a walk-in paying card today."
        )
        self.assertIn("Order O-1016 completed", order_answer)

        return_answer = self.agent.handle_user_message("now refund that")
        self.assertIn("Return R-2002 processed", return_answer)
        self.assertIn("Refund: $18.00", return_answer)
        self.assertEqual("R-2002", self.agent.memory.last_return_id)

    def test_agent_surfaces_medium_hoodie_ambiguity(self) -> None:
        answer = self.agent.handle_user_message(
            "Ring up a hoodie in medium for Sarah Chen."
        )
        self.assertIn("clarification", answer.casefold())
        self.assertIn("ambiguous", answer.casefold())
        self.assertIn("HOOD-GRY-M", answer)
        self.assertNotIn("O-1016", answer)

    def test_agent_creates_promotion_then_sells_promoted_hoodie(self) -> None:
        promotion = self.agent.handle_user_message(
            "Put all hoodies on 20% off from 2026-06-20 to 2026-06-22."
        )
        self.assertIn("Promotion PR-002 created", promotion)

        sale = self.agent.handle_user_message(
            "Ring up one Gray Medium hoodie dated 2026-06-21."
        )
        self.assertIn("at $48.00", sale)
        self.assertIn("Total paid: $48.00", sale)

    def test_agent_executes_compound_public_promotion_prompt(self) -> None:
        answer = self.agent.handle_user_message(
            "Put all hoodies on 20% off from 2026-06-20 to 2026-06-22, "
            "then ring up one Gray Medium hoodie dated 2026-06-21 and tell "
            "me the price."
        )
        self.assertIn("Promotion PR-002 created", answer)
        self.assertIn("Order O-1016 completed", answer)
        self.assertIn("at $48.00", answer)
        self.assertEqual("ring_up_order", self.agent.memory.last_action)

    def test_agent_formats_margin_and_stockout_analytics(self) -> None:
        margins = self.agent.handle_user_message(
            "What were my top five products by profit margin last month?"
        )
        self.assertIn("Top products by profit margin", margins)
        self.assertIn("Classic Tee", margins)
        self.assertIn("$420.00", margins)

        risks = self.agent.handle_user_message("What's about to stock out?")
        self.assertIn("Stockout risk", risks)
        self.assertIn("Canvas Tote", risks)
        self.assertIn("12.0 days of cover", risks)

    def test_tool_errors_do_not_crash_agent(self) -> None:
        answer = self.agent.handle_user_message(
            "Ring up ten Canvas Totes for a walk-in."
        )
        self.assertIn("Unable to complete", answer)
        self.assertIn("insufficient inventory", answer)
        self.assertEqual("ring_up_order", self.agent.memory.last_action)

    def test_low_confidence_message_returns_clarification(self) -> None:
        answer = self.agent.handle_user_message("Can you help with the shop?")
        self.assertIn("clarify", answer.casefold())
        self.assertEqual(2, len(self.agent.memory.recent_turns))

    def test_llm_failure_uses_deterministic_fallback(self) -> None:
        agent = RetailAgent(self.connection, llm_client=FailingLLMClient())
        answer = agent.handle_user_message(
            "Ring up one Canvas Tote for a walk-in paying cash today."
        )
        self.assertIn("Order O-1016 completed", answer)
        self.assertIn("Total paid: $18.00", answer)

    def test_unknown_llm_tool_uses_deterministic_fallback(self) -> None:
        agent = RetailAgent(self.connection, llm_client=UnknownToolLLMClient())
        answer = agent.handle_user_message("What's about to stock out?")
        self.assertIn("Stockout risk", answer)
        self.assertIn("Canvas Tote", answer)


if __name__ == "__main__":
    unittest.main()
