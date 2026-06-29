from __future__ import annotations

import sqlite3
from typing import Mapping

from retail_store.llm_client import LLMClientError, OpenAICompatibleClient
from retail_store.memory import SessionMemory
from retail_store.tools import TOOLS, Tool, ToolResult


SYSTEM_PROMPT = """You are an AI agent operating a retail store through tools.
Use tools for every store read or mutation. You may call multiple tools in sequence.
Never calculate or invent prices, refunds, inventory, margins, supplier choices, order details,
promotion effects, or stockout risk. Those values must come from tools.
Ask a concise clarification question when required information is missing or ambiguous.
Treat tool errors as authoritative and explain them without claiming the operation succeeded.
Today is 2026-06-19. Last month means 2026-05-01 through 2026-05-31.
Use session context and tool results to resolve references such as "that", "last", and "same".
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
        self.memory.add_turn("user", text)
        try:
            answer = self.llm_client.run_agent(
                text,
                self.tools,
                SYSTEM_PROMPT,
                previous_turns,
                self._invoke_tool,
            )
        except LLMClientError as exc:
            answer = f"Unable to run the retail agent: {exc}"
        self.memory.add_turn("assistant", answer)
        return answer
