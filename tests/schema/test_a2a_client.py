"""Unit tests for schema.a2a_client module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from testbench.schema.a2a_client import A2AStepClient, A2AStepResult, initialize_client

# ---------------------------------------------------------------------------
# initialize_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_client_creates_client():
    """initialize_client should return an A2A Client."""
    mock_card = MagicMock()
    mock_client = MagicMock()
    mock_factory = MagicMock()
    mock_factory.create.return_value = mock_client

    with (
        patch("testbench.schema.a2a_client.minimal_agent_card", return_value=mock_card),
        patch("testbench.schema.a2a_client.ClientFactory", return_value=mock_factory),
    ):
        result = await initialize_client("http://agent:8000", MagicMock())

    assert result is mock_client
    mock_factory.create.assert_called_once_with(mock_card)


# ---------------------------------------------------------------------------
# Helpers for building mock A2A responses
# ---------------------------------------------------------------------------


def _make_text_part(text: str) -> MagicMock:
    part = MagicMock()
    part.root = MagicMock(text=text, spec=["text"])
    # Ensure 'kind' is absent so the text branch is taken
    del part.root.kind
    return part


def _make_data_part(data: dict) -> MagicMock:
    """DataPart with kind='data'."""
    inner = MagicMock()
    inner.kind = "data"
    inner.data = data
    # Remove 'text' so the text branch is skipped
    del inner.text
    part = MagicMock()
    part.root = inner
    return part


def _agent_message(parts: list, metadata: dict | None = None) -> MagicMock:
    from a2a.types import Role

    msg = MagicMock()
    msg.role = Role.agent
    msg.parts = parts
    msg.metadata = metadata
    return msg


def _user_message(text: str = "hi") -> MagicMock:
    from a2a.types import Role

    msg = MagicMock()
    msg.role = Role.user
    msg.parts = [_make_text_part(text)]
    msg.metadata = None
    return msg


def _task_with_history(history: list, context_id: str = "ctx-1") -> MagicMock:
    task = MagicMock()
    task.history = history
    task.context_id = context_id
    return task


def _task_with_artifacts(text: str, context_id: str = "ctx-1") -> MagicMock:
    task = MagicMock()
    task.history = None
    task.context_id = context_id
    task.model_dump.return_value = {
        "artifacts": [{"parts": [{"text": text}]}],
    }
    return task


async def _mock_send_message_from_tasks(tasks: list):
    """Async generator yielding (task, None) tuples."""
    for t in tasks:
        yield (t, None)


# ---------------------------------------------------------------------------
# A2AStepClient.send_step — text-only response via history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_step_text_only_history():
    """Text-only agent response extracted from task.history."""
    task = _task_with_history(
        [
            _user_message("Hello"),
            _agent_message([_make_text_part("Hi there!")]),
        ]
    )

    mock_a2a = MagicMock()
    mock_a2a.send_message.return_value = _mock_send_message_from_tasks([task])

    with patch("testbench.schema.a2a_client.initialize_client", new_callable=AsyncMock, return_value=mock_a2a):
        client = A2AStepClient("http://agent:8000", MagicMock())
        result = await client.send_step("Hello")

    assert isinstance(result, A2AStepResult)
    assert result.context_id == "ctx-1"
    assert result.response_text == "Hi there!"
    # turns: human + ai
    assert len(result.turns) == 2
    assert result.turns[0].type == "human"
    assert result.turns[0].content == "Hello"
    assert result.turns[1].type == "agent"
    assert result.turns[1].content == "Hi there!"


# ---------------------------------------------------------------------------
# A2AStepClient.send_step — tool calls via metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_step_tool_calls_metadata():
    """Tool calls extracted from message metadata."""
    task = _task_with_history(
        [
            _user_message("weather?"),
            _agent_message(
                [_make_text_part("")],
                metadata={"tool_calls": [{"name": "get_weather", "args": {"city": "Berlin"}}]},
            ),
            _agent_message([_make_text_part("It's sunny in Berlin.")]),
        ]
    )

    mock_a2a = MagicMock()
    mock_a2a.send_message.return_value = _mock_send_message_from_tasks([task])

    with patch("testbench.schema.a2a_client.initialize_client", new_callable=AsyncMock, return_value=mock_a2a):
        client = A2AStepClient("http://agent:8000", MagicMock())
        result = await client.send_step("weather?")

    # turns: human, ai (tool_calls), ai (text)
    assert len(result.turns) == 3
    assert result.turns[1].type == "agent"
    assert result.turns[1].tool_calls is not None
    assert len(result.turns[1].tool_calls) == 1
    assert result.turns[1].tool_calls[0].name == "get_weather"
    assert result.turns[1].tool_calls[0].args == {"city": "Berlin"}
    assert result.turns[2].content == "It's sunny in Berlin."
    assert result.response_text == "It's sunny in Berlin."


# ---------------------------------------------------------------------------
# A2AStepClient.send_step — tool calls via DataPart
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_step_tool_calls_datapart():
    """Tool calls and responses extracted from DataParts."""
    tool_call_part = _make_data_part({"name": "get_temp", "args": {"city": "Munich"}})
    tool_resp_part = _make_data_part({"name": "get_temp", "response": {"temp": 22}})

    task = _task_with_history(
        [
            _user_message("temp?"),
            _agent_message([tool_call_part]),
            _agent_message([tool_resp_part]),
            _agent_message([_make_text_part("22 degrees")]),
        ]
    )

    mock_a2a = MagicMock()
    mock_a2a.send_message.return_value = _mock_send_message_from_tasks([task])

    with patch("testbench.schema.a2a_client.initialize_client", new_callable=AsyncMock, return_value=mock_a2a):
        client = A2AStepClient("http://agent:8000", MagicMock())
        result = await client.send_step("temp?")

    # turns: human, ai (tool_call), tool (response), ai (text)
    assert len(result.turns) == 4
    assert result.turns[1].type == "agent"
    assert result.turns[1].tool_calls is not None
    assert result.turns[1].tool_calls[0].name == "get_temp"
    assert result.turns[2].type == "tool"
    assert "22" in result.turns[2].content
    assert result.turns[3].type == "agent"
    assert result.turns[3].content == "22 degrees"


# ---------------------------------------------------------------------------
# A2AStepClient.send_step — artifact fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_step_artifact_fallback():
    """When history is unavailable, falls back to artifacts."""
    task = _task_with_artifacts("Artifact text")

    mock_a2a = MagicMock()
    mock_a2a.send_message.return_value = _mock_send_message_from_tasks([task])

    with patch("testbench.schema.a2a_client.initialize_client", new_callable=AsyncMock, return_value=mock_a2a):
        client = A2AStepClient("http://agent:8000", MagicMock())
        result = await client.send_step("hello")

    assert len(result.turns) == 2
    assert result.turns[1].type == "agent"
    assert result.turns[1].content == "Artifact text"
    assert result.response_text == "Artifact text"


# ---------------------------------------------------------------------------
# A2AStepClient.send_step — error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_step_error_handling():
    """On agent error, an ERROR turn is returned."""

    async def _raise(*_args, **_kwargs):
        raise ConnectionError("Agent unreachable")
        yield  # noqa: F811 - unreachable yield makes this an async generator

    mock_a2a = MagicMock()
    mock_a2a.send_message.side_effect = _raise

    with patch("testbench.schema.a2a_client.initialize_client", new_callable=AsyncMock, return_value=mock_a2a):
        client = A2AStepClient("http://agent:8000", MagicMock())
        result = await client.send_step("hi")

    assert len(result.turns) == 2
    assert result.turns[1].type == "agent"
    assert "ERROR" in result.turns[1].content


# ---------------------------------------------------------------------------
# A2AStepClient.send_step — context_id propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_step_preserves_existing_context_id():
    """When context_id is passed in, it is preserved in the result."""
    task = _task_with_history(
        [_user_message("follow-up"), _agent_message([_make_text_part("sure")])],
        context_id="ctx-existing",
    )

    mock_a2a = MagicMock()
    mock_a2a.send_message.return_value = _mock_send_message_from_tasks([task])

    with patch("testbench.schema.a2a_client.initialize_client", new_callable=AsyncMock, return_value=mock_a2a):
        client = A2AStepClient("http://agent:8000", MagicMock())
        result = await client.send_step("follow-up", context_id="ctx-existing")

    assert result.context_id == "ctx-existing"
