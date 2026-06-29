from __future__ import annotations

import re
import sqlite3
from typing import Mapping

from retail_store.intent_parser import parse_intent_without_llm
from retail_store.llm_client import (
    LLMClientError,
    LLMDecision,
    OpenAICompatibleClient,
)
from retail_store.memory import SessionMemory
from retail_store.tools import TOOLS, Tool, ToolResult

SYSTEM_PROMPT = """You are a retail store operations agent.
Use tools for all store operations.
Never compute prices, refunds, inventory, margins, supplier choice, or stockout risk yourself.
Ask a clarifying question when product, color, size, or customer is ambiguous.
Today is 2026-06-19.
Last month means May 2026.
Keep responses concise and business-like."""


def format_tool_result(tool_name: str, result: ToolResult) -> str:
    if not result.ok:
        error = result.error or "unknown error"
        if "ambiguous" in error.casefold():
            return f"I need clarification: {error}"
        return f"Unable to complete the request: {error}"

    data = result.data
    if tool_name == "ring_up_order":
        lines = "; ".join(
            f"{line['quantity']} × {line['name']} ({line['sku']}) at "
            f"${line['unit_price']}"
            for line in data["line_items"]
        )
        return (
            f"Order {data['order_id']} completed for {data['customer_id']}: "
            f"{lines}. Total paid: ${data['total_paid']}."
        )
    if tool_name == "process_return":
        inventory_note = (
            f" Inventory increased by {data['inventory_increase']}."
            if data["inventory_increase"]
            else " Inventory was not increased."
        )
        return (
            f"Return {data['return_id']} processed for {data['sku']}. "
            f"Refund: ${data['refund_amount']}.{inventory_note}"
        )
    if tool_name == "create_promotion":
        return (
            f"Promotion {data['promo_id']} created: {data['percent_off']}% off "
            f"{data['scope_type']} {data['scope_ref']} from "
            f"{data['start_date']} through {data['end_date']}."
        )
    if tool_name == "reorder_low_stock":
        if not data:
            return "No inventory is currently at or below its reorder point."
        lines = "; ".join(
            f"{po['po_id']}: {po['quantity_ordered']} units of "
            f"{po['product_id']} from {po['supplier_name']}"
            for po in data
        )
        return f"Created {len(data)} purchase order(s): {lines}."
    if tool_name == "receive_purchase_order":
        return (
            f"Purchase order {data['po_id']} is {data['status']}: received "
            f"{data['received_now']} now ({data['quantity_received']} of "
            f"{data['quantity_ordered']} total)."
        )
    if tool_name == "top_products_by_profit_margin":
        if not data:
            return "No product margin data was found for that period."
        lines = "; ".join(
            f"{index}. {row['product_name']} — margin ${row['margin']}"
            for index, row in enumerate(data, start=1)
        )
        return f"Top products by profit margin: {lines}."
    if tool_name == "get_stockout_risk":
        if not data:
            return "No products are currently at risk of stocking out."
        lines = "; ".join(
            f"{row['product_name']} ({row['on_hand_total']} on hand, "
            f"{row['days_of_cover']} days of cover; "
            f"{', '.join(row['reasons'])})"
            for row in data
        )
        return f"Stockout risk: {lines}."
    return "Request completed."


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

    def _select_with_fallback(self, text: str) -> LLMDecision:
        llm_message: str | None = None
        if self.llm_client.available:
            try:
                decision = self.llm_client.select_tool(
                    text,
                    self.tools,
                    SYSTEM_PROMPT,
                    self.memory.get("recent_turns", []),
                )
                if decision.tool_name in self.tools:
                    return decision
                llm_message = decision.message
            except LLMClientError:
                pass

        parsed = parse_intent_without_llm(text, self.memory)
        return LLMDecision(
            tool_name=parsed["tool_name"],
            arguments=parsed["arguments"],
            message=(
                llm_message or parsed["reason"]
                if parsed["tool_name"] is None
                else None
            ),
        )

    def handle_user_message(self, text: str) -> str:
        self.memory.add_turn("user", text)
        compound_followup = re.search(
            r"\bthen\s+((?:ring up|sell|checkout)\b.+)$",
            text,
            flags=re.IGNORECASE,
        )
        compound_intent = (
            parse_intent_without_llm(text, self.memory)
            if compound_followup is not None
            else None
        )
        if (
            compound_intent is not None
            and compound_intent["tool_name"] == "create_promotion"
        ):
            decision = LLMDecision(
                tool_name="create_promotion",
                arguments=compound_intent["arguments"],
            )
        else:
            decision = self._select_with_fallback(text)

        if decision.tool_name is None:
            answer = decision.message or "Please clarify the requested store operation."
        elif decision.tool_name not in self.tools:
            answer = f"Unable to complete the request: unknown tool {decision.tool_name}."
        else:
            result = self.tools[decision.tool_name].invoke(
                self.connection, **decision.arguments
            )
            self.memory.update(result.session_updates)
            if (
                decision.tool_name == "process_return"
                and not result.ok
                and result.error
                and "provide sku or product_description" in result.error
            ):
                order_id = decision.arguments.get("order_id", "that order")
                answer = f"I need the item or SKU to refund from order {order_id}."
            else:
                answer = format_tool_result(decision.tool_name, result)

            if (
                result.ok
                and decision.tool_name == "create_promotion"
                and compound_followup is not None
            ):
                parsed = parse_intent_without_llm(
                    compound_followup.group(1), self.memory
                )
                followup_tool = parsed["tool_name"]
                if followup_tool == "ring_up_order":
                    followup_result = self.tools[followup_tool].invoke(
                        self.connection, **parsed["arguments"]
                    )
                    self.memory.update(followup_result.session_updates)
                    answer = (
                        f"{answer} "
                        f"{format_tool_result(followup_tool, followup_result)}"
                    )

        self.memory.add_turn("assistant", answer)
        return answer
