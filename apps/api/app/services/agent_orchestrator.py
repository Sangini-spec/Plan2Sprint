"""
Agent Orchestrator — core runner for Azure AI Agent Service.

Provides:
  - Agent creation with tool definitions
  - Thread (conversation) management
  - Run execution with tool-call loops
  - Graceful fallback when Agent Service is unavailable

The orchestrator uses the OpenAI-compatible chat completions API with
function calling (same endpoint as sprint generation) rather than the
full Agent Service SDK, so it works with the existing Azure AI Foundry
deployment without additional provisioning.

When Azure AI Agent Service endpoints are configured, it will use those
for richer agent state management. Otherwise falls back to the stateless
chat + tool-calling loop.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool Definition
# ---------------------------------------------------------------------------

@dataclass
class AgentTool:
    """A tool that an agent can invoke during reasoning."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    handler: Callable[..., Awaitable[Any]]


@dataclass
class AgentConfig:
    """Configuration for an agent."""
    name: str
    instructions: str
    tools: list[AgentTool] = field(default_factory=list)
    model: str = ""
    temperature: float = 0.3
    max_tokens: int = 8192
    max_tool_rounds: int = 10  # Safety limit on tool-call loops


# ---------------------------------------------------------------------------
# Agent Run Result
# ---------------------------------------------------------------------------

@dataclass
class AgentRunResult:
    """Result of a single agent run."""
    success: bool
    output: str
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    raw_response: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class AgentOrchestrator:
    """
    Runs an agent with tool-calling loop.

    Uses the OpenAI-compatible chat completions API with function calling.
    The agent reasons, decides which tools to call, receives results, and
    continues until it produces a final text response.
    """

    def __init__(self) -> None:
        # Prefer Agent Service endpoint, fall back to AI Foundry endpoint
        self._endpoint = settings.azure_agent_endpoint or settings.azure_ai_endpoint
        self._api_key = settings.azure_agent_api_key or settings.azure_ai_api_key
        self._model = settings.azure_agent_model or settings.azure_ai_model or "grok-4-fast-reasoning"

    @property
    def is_configured(self) -> bool:
        return bool(self._endpoint and self._api_key)

    def _build_tools_schema(self, tools: list[AgentTool]) -> list[dict]:
        """Convert AgentTool list to OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]

    async def run(
        self,
        config: AgentConfig,
        user_message: str,
        context: dict[str, Any] | None = None,
    ) -> AgentRunResult:
        """
        Execute an agent run with tool-calling loop.

        Args:
            config: Agent configuration (instructions, tools, model settings)
            user_message: The initial prompt for this run
            context: Optional context dict passed to tool handlers

        Returns:
            AgentRunResult with the agent's final output
        """
        if not self.is_configured:
            return AgentRunResult(
                success=False,
                output="",
                error="Azure AI Agent Service is not configured. Set AZURE_AGENT_ENDPOINT and AZURE_AGENT_API_KEY.",
            )

        model = config.model or self._model
        tools_schema = self._build_tools_schema(config.tools) if config.tools else []
        tool_calls_log: list[dict[str, Any]] = []

        # Build initial messages
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": config.instructions},
            {"role": "user", "content": user_message},
        ]

        headers = {
            "Content-Type": "application/json",
            "api-key": self._api_key,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            for round_num in range(config.max_tool_rounds):
                payload: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": config.temperature,
                    "max_tokens": config.max_tokens,
                }
                if tools_schema:
                    payload["tools"] = tools_schema
                    payload["tool_choice"] = "auto"

                try:
                    resp = await client.post(
                        self._endpoint,
                        headers=headers,
                        json=payload,
                    )
                    resp.raise_for_status()
                except httpx.HTTPStatusError as e:
                    logger.error(f"Agent API call failed (round {round_num}): {e}")
                    return AgentRunResult(
                        success=False,
                        output="",
                        error=f"Azure AI API error: {e.response.status_code} - {e.response.text[:300]}",
                    )
                except httpx.RequestError as e:
                    logger.error(f"Agent API request failed: {e}")
                    return AgentRunResult(
                        success=False,
                        output="",
                        error=f"Connection error: {str(e)[:200]}",
                    )

                data = resp.json()
                choice = data["choices"][0]
                message = choice["message"]
                finish_reason = choice.get("finish_reason", "")

                # If the model wants to call tools
                if message.get("tool_calls"):
                    # Add assistant message with tool calls to history
                    messages.append(message)

                    for tc in message["tool_calls"]:
                        fn_name = tc["function"]["name"]
                        fn_args_str = tc["function"].get("arguments", "{}")
                        tc_id = tc["id"]

                        logger.info(f"Agent tool call (round {round_num}): {fn_name}")

                        # Find the matching tool handler
                        handler = None
                        for tool in config.tools:
                            if tool.name == fn_name:
                                handler = tool.handler
                                break

                        if handler is None:
                            tool_result = json.dumps({"error": f"Unknown tool: {fn_name}"})
                        else:
                            try:
                                fn_args = json.loads(fn_args_str)
                                # Pass context to handler if it accepts it
                                result = await handler(**fn_args, _context=context)
                                tool_result = json.dumps(result, default=str)
                            except Exception as e:
                                logger.warning(f"Tool {fn_name} failed: {e}")
                                tool_result = json.dumps({"error": str(e)[:500]})

                        tool_calls_log.append({
                            "round": round_num,
                            "tool": fn_name,
                            "args": fn_args_str,
                            "result_length": len(tool_result),
                        })

                        # Add tool result to conversation
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": tool_result,
                        })

                    # Continue the loop — let the model reason over tool results
                    continue

                # No tool calls — the model produced a final response
                final_text = message.get("content", "")
                logger.info(
                    f"Agent '{config.name}' completed in {round_num + 1} rounds, "
                    f"{len(tool_calls_log)} tool calls"
                )
                return AgentRunResult(
                    success=True,
                    output=final_text,
                    tool_calls_made=tool_calls_log,
                    raw_response=data,
                )

        # Exhausted max rounds
        logger.warning(f"Agent '{config.name}' hit max tool rounds ({config.max_tool_rounds})")
        return AgentRunResult(
            success=False,
            output="",
            error=f"Agent exceeded maximum tool-call rounds ({config.max_tool_rounds})",
            tool_calls_made=tool_calls_log,
        )


# Singleton
orchestrator = AgentOrchestrator()
