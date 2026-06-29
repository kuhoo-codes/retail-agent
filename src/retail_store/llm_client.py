from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

from retail_store.tools import Tool


class LLMClientError(RuntimeError):
    """Raised when the optional model selector is unavailable or malformed."""


@dataclass(frozen=True)
class LLMDecision:
    tool_name: str | None
    arguments: dict[str, Any]
    message: str | None = None


class OpenAICompatibleClient:
    """Isolated OpenAI-compatible Chat Completions tool-selection client."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("RETAIL_AGENT_MODEL", "gpt-5.4-mini")
        self.base_url = (
            base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def select_tool(
        self,
        user_text: str,
        tools: Mapping[str, Tool],
        system_prompt: str,
        recent_turns: list[dict[str, str]] | None = None,
    ) -> LLMDecision:
        if not self.available:
            raise LLMClientError("OPENAI_API_KEY is not configured")

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]
        for turn in (recent_turns or [])[-8:]:
            if turn.get("role") in {"user", "assistant"} and isinstance(
                turn.get("content"), str
            ):
                messages.append(
                    {"role": turn["role"], "content": turn["content"]}
                )
        if not messages or messages[-1] != {"role": "user", "content": user_text}:
            messages.append({"role": "user", "content": user_text})

        payload = {
            "model": self.model,
            "messages": messages,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools.values()
            ],
            "tool_choice": "auto",
            "parallel_tool_calls": False,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMClientError(f"LLM request failed: {exc}") from exc

        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError("LLM response did not contain a message") from exc

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            content = message.get("content")
            return LLMDecision(
                tool_name=None,
                arguments={},
                message=content if isinstance(content, str) else None,
            )
        try:
            function = tool_calls[0]["function"]
            arguments = json.loads(function["arguments"])
            if not isinstance(arguments, dict):
                raise TypeError("tool arguments are not an object")
            return LLMDecision(
                tool_name=function["name"],
                arguments=arguments,
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise LLMClientError("LLM returned a malformed tool call") from exc

