"""Reusable A2A client for sending messages and extracting turns.

Encapsulates the send-message-and-extract-turns pattern.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import httpx
from a2a.client.client import Client, ClientConfig
from a2a.client.client_factory import ClientFactory, minimal_agent_card
from a2a.types import AgentCard, Message, Part, Role, TextPart
from schema.models import ToolCall, Turn

logger = logging.getLogger(__name__)


async def initialize_client(agent_url: str, client: httpx.AsyncClient) -> Client:
    """Initialize the A2A client with a minimal agent card."""
    logger.info("Initializing A2A client for: %s", agent_url)

    agent_card: AgentCard = minimal_agent_card(agent_url)
    config: ClientConfig = ClientConfig(httpx_client=client)
    factory: ClientFactory = ClientFactory(config)
    a2a_client: Client = factory.create(agent_card)

    logger.info("A2A client initialized successfully")
    return a2a_client


class A2AStepResult:
    """Result of sending a single step to an A2A agent."""

    __slots__ = ("turns", "response_text", "context_id")

    def __init__(self, turns: list[Turn], response_text: str, context_id: str | None) -> None:
        self.turns = turns
        self.response_text = response_text
        self.context_id = context_id


class A2AStepClient:
    """Thin wrapper that sends a user message via A2A and extracts structured turns."""

    def __init__(self, agent_url: str, http_client: httpx.AsyncClient) -> None:
        self._agent_url = agent_url
        self._http_client = http_client

    async def send_step(
        self,
        user_input: str,
        context_id: str | None = None,
    ) -> A2AStepResult:
        """Send *user_input* to the agent and return extracted turns.

        Args:
            user_input: The text to send as a human turn.
            context_id: Optional conversation context id (returned from a
                previous call).

        Returns:
            An :class:`A2AStepResult` containing the extracted turns,
            the final AI response text, and the (possibly updated) context_id.
        """
        a2a_client = await initialize_client(self._agent_url, self._http_client)

        message = Message(
            role=Role.user,
            parts=[Part(root=TextPart(text=user_input))],
            message_id=uuid4().hex,
            context_id=context_id,
        )

        turns: list[Turn] = [Turn(content=user_input, type="human")]
        last_task = None
        captured_context_id = context_id

        try:
            async for response in a2a_client.send_message(message):
                if not isinstance(response, tuple):
                    logger.warning("Unexpected response type: %s", type(response))
                    continue

                task, _ = response
                if task is None:
                    continue

                last_task = task

                if captured_context_id is None and task.context_id:
                    captured_context_id = task.context_id
                    logger.info("  Captured context_id: %s", captured_context_id)

        except Exception as e:
            logger.error("Error querying agent for step '%s': %s", user_input[:50], e)
            turns.append(Turn(content=f"ERROR: {e}", type="agent"))
            return A2AStepResult(turns=turns, response_text=f"ERROR: {e}", context_id=captured_context_id)

        response_text = ""

        # Extract turns from task.history (preferred) or fall back to artifacts
        if last_task is not None and hasattr(last_task, "history") and last_task.history:
            response_text = _extract_turns_from_history(last_task.history, turns)
        elif last_task is not None:
            response_text = _extract_turns_from_artifacts(last_task, turns)

        return A2AStepResult(turns=turns, response_text=response_text, context_id=captured_context_id)


def _extract_turns_from_history(history: list[Any], turns: list[Turn]) -> str:
    """Parse task history into Turn objects, returning the final AI text."""
    response_text = ""

    for msg in history:
        if msg.role == Role.user:
            continue

        if msg.role == Role.agent:
            tool_calls_in_msg: list[ToolCall] = []
            tool_responses: list[str] = []
            text_content = ""

            # Strategy 1: Check message metadata for tool calls
            if msg.metadata and "tool_calls" in msg.metadata:
                metadata_tool_calls = msg.metadata.get("tool_calls", [])
                if isinstance(metadata_tool_calls, list):
                    for tc in metadata_tool_calls:
                        if isinstance(tc, dict) and "name" in tc:
                            tool_calls_in_msg.append(ToolCall(name=tc["name"], args=tc.get("args", {})))

            # Strategy 2: Check parts for DataParts and TextParts
            for part in msg.parts:
                actual_part = part.root if hasattr(part, "root") else part

                if hasattr(actual_part, "text"):
                    text_content = actual_part.text
                elif (
                    hasattr(actual_part, "kind")
                    and actual_part.kind == "data"
                    and hasattr(actual_part, "data")
                    and isinstance(actual_part.data, dict)
                    and "name" in actual_part.data
                ):
                    if "args" in actual_part.data and "response" not in actual_part.data:
                        tool_calls_in_msg.append(
                            ToolCall(
                                name=actual_part.data["name"],
                                args=actual_part.data.get("args", {}),
                            )
                        )
                    elif "response" in actual_part.data and "args" not in actual_part.data:
                        tool_responses.append(str(actual_part.data.get("response", {})))

            if tool_calls_in_msg:
                turns.append(Turn(content="", type="agent", tool_calls=tool_calls_in_msg))
                logger.info("  Extracted %d tool call(s)", len(tool_calls_in_msg))

            if tool_responses:
                for resp in tool_responses:
                    turns.append(Turn(content=resp, type="tool"))
                logger.info("  Extracted %d tool response(s)", len(tool_responses))

            if text_content:
                turns.append(Turn(content=text_content, type="agent"))
                response_text = text_content

    return response_text


def _extract_turns_from_artifacts(task: Any, turns: list[Turn]) -> str:
    """Fallback: extract text from task artifacts."""
    output_text = ""
    artifacts: list[dict[str, Any]] = task.model_dump(mode="json", include={"artifacts"}).get("artifacts", [])
    if artifacts and artifacts[0].get("parts"):
        output_text = artifacts[0]["parts"][0].get("text", "")
    if output_text:
        turns.append(Turn(content=output_text, type="agent"))
    return output_text
