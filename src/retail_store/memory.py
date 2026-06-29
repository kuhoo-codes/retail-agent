from __future__ import annotations

from copy import deepcopy
from typing import Any


class SessionMemory:
    """Small, inspectable session state used for conversational references."""

    FIELDS = {
        "last_order_id",
        "last_return_id",
        "last_purchase_order_id",
        "last_customer_name",
        "last_items",
        "last_skus",
        "last_action",
        "conversation_summary",
        "recent_turns",
    }

    def __init__(self) -> None:
        self.last_order_id: str | None = None
        self.last_return_id: str | None = None
        self.last_purchase_order_id: str | None = None
        self.last_customer_name: str | None = None
        self.last_items: list[dict[str, Any]] = []
        self.last_skus: list[str] = []
        self.last_action: str | None = None
        self.conversation_summary: str | None = None
        self.recent_turns: list[dict[str, str]] = []

    def update(self, values: dict[str, Any]) -> None:
        if not isinstance(values, dict):
            raise TypeError("memory update must be a dictionary")
        unknown = set(values) - self.FIELDS
        if unknown:
            raise KeyError(f"unknown memory field: {sorted(unknown)[0]}")
        for key, value in values.items():
            setattr(self, key, deepcopy(value))

    def get(self, key: str, default: Any = None) -> Any:
        if key not in self.FIELDS:
            return default
        return deepcopy(getattr(self, key))

    def add_turn(self, role: str, content: str) -> None:
        if role not in {"user", "assistant", "tool", "system"}:
            raise ValueError(f"unsupported turn role: {role!r}")
        if not isinstance(content, str):
            raise TypeError("turn content must be text")
        self.recent_turns.append({"role": role, "content": content})
