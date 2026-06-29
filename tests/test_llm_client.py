from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.llm_client import OpenAICompatibleClient
from retail_store.tools import TOOLS, ToolResult


class ScriptedCompletionClient(OpenAICompatibleClient):
    def __init__(self, responses):
        super().__init__(api_key="test-key")
        self.responses = iter(responses)
        self.message_snapshots = []

    def _completion(self, messages, tools):
        self.message_snapshots.append([dict(message) for message in messages])
        return next(self.responses)


class LLMToolLoopTests(unittest.TestCase):
    def test_tool_result_is_returned_to_model_before_final_answer(self) -> None:
        client = ScriptedCompletionClient(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "price_quote",
                                "arguments": (
                                    '{"product_description":"Canvas Tote",'
                                    '"price_date":"2026-06-19"}'
                                ),
                            },
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": "The Canvas Tote costs $18.00.",
                },
            ]
        )
        invocations = []

        def invoke(name, arguments):
            invocations.append((name, arguments))
            return ToolResult(
                ok=True,
                data={"unit_price": "18.00"},
                error=None,
                session_updates={"last_action": "price_quote"},
            )

        answer = client.run_agent(
            "What does a tote cost?",
            TOOLS,
            "Use tools.",
            [],
            invoke,
        )

        self.assertEqual("The Canvas Tote costs $18.00.", answer)
        self.assertEqual("price_quote", invocations[0][0])
        second_round = client.message_snapshots[1]
        tool_message = second_round[-1]
        self.assertEqual("tool", tool_message["role"])
        self.assertEqual("call-1", tool_message["tool_call_id"])
        self.assertIn('"unit_price": "18.00"', tool_message["content"])


if __name__ == "__main__":
    unittest.main()
