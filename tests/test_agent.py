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
from retail_store.llm_client import LLMClientError
from retail_store.seed import seed_database


class ScriptedAgentClient:
    available = True

    def __init__(self, calls, answer):
        self.calls = calls
        self.answer = answer
        self.results = []

    def run_agent(
        self, user_text, tools, system_prompt, recent_turns, invoke_tool
    ):
        for name, arguments in self.calls:
            self.results.append(invoke_tool(name, arguments))
        return self.answer


class FailingAgentClient:
    available = True

    def run_agent(self, *args, **kwargs):
        raise LLMClientError("simulated provider failure")


class RetailAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        seed_database(ROOT / "data", self.database)
        self.connection = connect(self.database)
        self.key_patch = patch.dict(os.environ, {}, clear=True)
        self.key_patch.start()

    def tearDown(self) -> None:
        self.key_patch.stop()
        self.connection.close()
        self.temp_dir.cleanup()

    def test_system_prompt_enforces_tool_boundaries(self) -> None:
        self.assertIn("Use tools for every store read or mutation", SYSTEM_PROMPT)
        self.assertIn("Never calculate or invent prices", SYSTEM_PROMPT)
        self.assertIn("Today is 2026-06-19", SYSTEM_PROMPT)
        self.assertIn("Last month means 2026-05-01", SYSTEM_PROMPT)

    def test_agent_executes_model_selected_tool(self) -> None:
        client = ScriptedAgentClient(
            [
                (
                    "ring_up_order",
                    {
                        "items": [
                            {
                                "product_description": "Canvas Tote",
                                "quantity": 1,
                            }
                        ],
                        "customer_name": None,
                        "payment_method": "cash",
                        "order_date": "2026-06-19",
                        "order_discount_pct": 0,
                    },
                )
            ],
            "Order O-1016 completed. Total paid: $18.00.",
        )
        agent = RetailAgent(self.connection, llm_client=client)
        answer = agent.handle_user_message("Process a cash sale for one tote.")
        self.assertEqual("Order O-1016 completed. Total paid: $18.00.", answer)
        self.assertTrue(client.results[0].ok)
        self.assertEqual("O-1016", agent.memory.last_order_id)

    def test_agent_supports_multiple_tool_calls(self) -> None:
        client = ScriptedAgentClient(
            [
                (
                    "create_promotion",
                    {
                        "description": "Hoodies 20% off",
                        "percent_off": 20,
                        "scope_type": "product",
                        "scope_ref": "P-HOOD",
                        "start_date": "2026-06-20",
                        "end_date": "2026-06-22",
                    },
                ),
                (
                    "ring_up_order",
                    {
                        "items": [
                            {
                                "product_description": "hoodie",
                                "color": "Gray",
                                "size": "Medium",
                                "quantity": 1,
                            }
                        ],
                        "order_date": "2026-06-21",
                    },
                ),
            ],
            "Promotion created and hoodie sold for $48.00.",
        )
        agent = RetailAgent(self.connection, llm_client=client)
        answer = agent.handle_user_message("Create the promotion, then sell it.")
        self.assertEqual("Promotion created and hoodie sold for $48.00.", answer)
        self.assertEqual(["create_promotion", "ring_up_order"], [
            result.session_updates["last_action"] for result in client.results
        ])

    def test_provider_failure_is_explicit_without_fallback(self) -> None:
        agent = RetailAgent(self.connection, llm_client=FailingAgentClient())
        answer = agent.handle_user_message("Sell one tote.")
        self.assertIn("Unable to run the retail agent", answer)
        self.assertIn("simulated provider failure", answer)
        self.assertEqual(0, self.connection.execute(
            "SELECT COUNT(*) FROM orders WHERE order_id='O-1016'"
        ).fetchone()[0])

    def test_missing_api_key_is_explicit(self) -> None:
        agent = RetailAgent(self.connection)
        answer = agent.handle_user_message("Sell one tote.")
        self.assertIn("OPENAI_API_KEY is required", answer)


if __name__ == "__main__":
    unittest.main()
