from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping

from retail_store.tools import Tool, ToolResult


class LLMClientError(RuntimeError):
    """Raised when the model-backed agent is unavailable or malformed."""


ToolInvoker = Callable[[str, dict[str, Any]], ToolResult]


class OpenAICompatibleClient:
    """OpenAI-compatible iterative tool-calling client."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 20.0,
        max_tool_rounds: int = 12,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("RETAIL_AGENT_MODEL", "gpt-5.4-nano")
        self.base_url = (
            base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_tool_rounds = max_tool_rounds

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _completion(
        self,
        messages: list[dict[str, Any]],
        tools: Mapping[str, Tool],
    ) -> dict[str, Any]:
        if not self.available:
            raise LLMClientError(
                "OPENAI_API_KEY is required; deterministic language routing is disabled"
            )
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
        if not isinstance(message, dict):
            raise LLMClientError("LLM response message was malformed")
        return message

    def run_agent(
        self,
        user_text: str,
        tools: Mapping[str, Tool],
        system_prompt: str,
        recent_turns: list[dict[str, str]],
        invoke_tool: ToolInvoker,
    ) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        messages.extend(
            {"role": turn["role"], "content": turn["content"]}
            for turn in recent_turns[-12:]
            if turn.get("role") in {"user", "assistant"}
            and isinstance(turn.get("content"), str)
        )
        messages.append({"role": "user", "content": user_text})

        for _round in range(self.max_tool_rounds + 1):
            message = self._completion(messages, tools)
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
                raise LLMClientError("LLM returned neither text nor a tool call")

            messages.append(message)
            for call in tool_calls:
                try:
                    call_id = call["id"]
                    function = call["function"]
                    name = function["name"]
                    arguments = json.loads(function["arguments"])
                    if not isinstance(arguments, dict):
                        raise TypeError("tool arguments are not an object")
                except (KeyError, TypeError, json.JSONDecodeError) as exc:
                    raise LLMClientError("LLM returned a malformed tool call") from exc

                if name not in tools:
                    result = ToolResult(
                        ok=False,
                        data=None,
                        error=f"unknown tool: {name}",
                        session_updates={},
                    )
                else:
                    result = invoke_tool(name, arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(result.to_dict(), default=str),
                    }
                )

        raise LLMClientError(
            f"agent exceeded {self.max_tool_rounds} tool-call rounds"
        )
