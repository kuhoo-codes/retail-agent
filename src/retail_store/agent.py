from __future__ import annotations

import sqlite3
from typing import Mapping

from retail_store.llm_client import LLMClientError, OpenAICompatibleClient
from retail_store.formatters import format_store_metrics, format_tool_result
from retail_store.intent_parser import parse_analytics_intent, parse_offline_tool_plan
from retail_store.memory import SessionMemory
from retail_store.tools import TOOLS, Tool, ToolResult


SYSTEM_PROMPT = """You are an AI agent operating a retail store through tools.
Use tools for every store read or mutation. You may call multiple tools in sequence.
Never calculate or invent prices, refunds, inventory, margins, supplier choices, order details,
promotion effects, or stockout risk. Those values must come from tools.
For flexible analytics and read questions, use query_store_metrics. It supports grouping and
filtering revenue, spend, units, refunds, margin, cost, orders, customers, products, SKUs,
variants, categories, dates, and payment methods. Continue to use get_stockout_risk for
stockout risk. The legacy top-products margin tool remains available for that specific report.
Never write SQL or calculate numbers manually.
Ask a concise clarification question when required information is missing or ambiguous.
Treat tool errors as authoritative and explain them without claiming the operation succeeded.
For any store mutation such as create, ring up, sell, checkout, return, refund, receive,
reorder, cancel, update, delete, clear, or reset: call a tool before saying it happened.
If no available tool can perform the requested mutation, say that it cannot be done.
Never claim a promotion, sale, return, purchase order, inventory change, or cancellation
was created unless a tool result in the current turn confirms it.
Today is 2026-06-19. Last month means 2026-05-01 through 2026-05-31.
Use the structured session state, recent conversation, and tool results to resolve references
such as "that", "last", and "same".
Keep the final response concise and include identifiers and monetary values returned by tools."""


class RetailAgent:
    def __init__(
        self,
        connection: sqlite3.Connection,
        tools: Mapping[str, Tool] | None = None,
        memory: SessionMemory | None = None,
        llm_client: OpenAICompatibleClient | None = None,
    ) -> None:
        self.connection = connection
        self.tools = dict(tools or TOOLS)
        self.memory = memory or SessionMemory()
        self.llm_client = llm_client or OpenAICompatibleClient()

    def _invoke_tool(
        self, tool_name: str, arguments: dict[str, object]
    ) -> ToolResult:
        tool = self.tools.get(tool_name)
        if tool is None:
            return ToolResult(
                ok=False,
                data=None,
                error=f"unknown tool: {tool_name}",
                session_updates={},
            )
        result = tool.invoke(self.connection, **arguments)
        self.memory.update(result.session_updates)
        return result

    def handle_user_message(self, text: str) -> str:
        if not isinstance(text, str) or not text.strip():
            return "Please enter a retail instruction."
        previous_turns = self.memory.get("recent_turns", [])
        session_context = self.memory.snapshot()
        self.memory.add_turn("user", text)
        if not self.llm_client.available:
            plan = parse_offline_tool_plan(text, session_context)
            if plan is not None:
                answers: list[str] = []
                for tool_name, tool_arguments in plan:
                    result = self._invoke_tool(tool_name, tool_arguments)
                    if not result.ok:
                        answer = f"Unable to {tool_name}: {result.error}"
                        self.memory.add_turn("assistant", answer)
                        return answer
                    answers.append(format_tool_result(tool_name, result.data))
                answer = "\n".join(answers)
                self.memory.add_turn("assistant", answer)
                return answer
            if " ".join(text.casefold().split()) in {
                "now refund that",
                "refund that",
                "return that",
            }:
                answer = (
                    "I need the order and item to process that return; "
                    "the session has no single prior item to reference."
                )
                self.memory.add_turn("assistant", answer)
                return answer
            arguments = parse_analytics_intent(text)
            if arguments is not None:
                result = self._invoke_tool("query_store_metrics", arguments)
                answer = (
                    format_store_metrics(result.data)
                    if result.ok
                    else f"Unable to query store metrics: {result.error}"
                )
                self.memory.add_turn("assistant", answer)
                return answer
        try:
            answer = self.llm_client.run_agent(
                text,
                self.tools,
                SYSTEM_PROMPT,
                previous_turns,
                self._invoke_tool,
                session_context=session_context,
            )
        except LLMClientError as exc:
            answer = f"Unable to run the retail agent: {exc}"
        self.memory.add_turn("assistant", answer)
        return answer
