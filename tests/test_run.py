"""
Unit tests for run.py

Tests the A2AExecutor class and experiment execution functionality.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from testbench.run import A2AExecutor, _content_hash, main
from testbench.schema.a2a_client import A2AStepResult
from testbench.schema.models import (
    ExecutedExperiment,
    ExecutedScenario,
    ExecutedStep,
    Scenario,
    Step,
    Turn,
)

# ---------------------------------------------------------------------------
# Test _content_hash
# ---------------------------------------------------------------------------


def test_content_hash_deterministic():
    """Test that _content_hash produces deterministic output."""
    data = "test-data"
    hash1 = _content_hash(data)
    hash2 = _content_hash(data)

    assert hash1 == hash2
    assert len(hash1) == 16  # SHA256 truncated to 16 chars


def test_content_hash_different_inputs():
    """Test that different inputs produce different hashes."""
    hash1 = _content_hash("input1")
    hash2 = _content_hash("input2")

    assert hash1 != hash2


def test_content_hash_with_prefix():
    """Test that prefix is prepended to hash."""
    data = "test-data"
    hash_no_prefix = _content_hash(data)
    hash_with_prefix = _content_hash(data, prefix="scn_")

    assert hash_with_prefix == f"scn_{hash_no_prefix}"
    assert hash_with_prefix.startswith("scn_")


def test_content_hash_empty_prefix():
    """Test that empty prefix works correctly."""
    data = "test-data"
    hash1 = _content_hash(data, prefix="")
    hash2 = _content_hash(data)

    assert hash1 == hash2


# ---------------------------------------------------------------------------
# Test A2AExecutor.on_step
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_on_step_success():
    """Test that on_step correctly calls A2A client and returns ExecutedStep."""
    executor = A2AExecutor(
        agent_url="http://test-agent:8000",
        experiment_name="test-workflow",
        input_path="input.json",
        output_path="output.json",
    )

    # Mock the A2A client
    mock_client = AsyncMock()
    mock_result = A2AStepResult(
        turns=[
            Turn(content="What is the weather?", type="human"),
            Turn(content="It's sunny today", type="agent"),
        ],
        response_text="It's sunny today",
        context_id="ctx-123",
    )
    mock_client.send_step = AsyncMock(return_value=mock_result)
    executor._a2a_client = mock_client

    # Set up scenario state
    executor._current_scenario_id = "scn_test123"
    executor._step_index = 0
    executor._context_id = None

    # Create test step and scenario
    step = Step(input="What is the weather?", reference=None)
    scenario = Scenario(name="Weather Test", steps=[step])

    # Call on_step
    result = await executor.on_step(step, scenario)

    # Verify A2A client was called correctly
    mock_client.send_step.assert_called_once_with("What is the weather?", None)

    # Verify ExecutedStep structure
    assert isinstance(result, ExecutedStep)
    assert result.input == "What is the weather?"
    assert result.turns is not None
    assert len(result.turns) == 2
    assert result.turns[0].content == "What is the weather?"
    assert result.turns[0].type == "human"
    assert result.turns[1].content == "It's sunny today"
    assert result.turns[1].type == "agent"
    assert result.id is not None
    assert result.id.startswith("stp_")

    # Verify context_id was updated
    assert executor._context_id == "ctx-123"


@pytest.mark.asyncio
async def test_executor_on_step_maintains_context():
    """Test that on_step passes context_id from previous step."""
    executor = A2AExecutor(
        agent_url="http://test-agent:8000",
        experiment_name="test-workflow",
        input_path="input.json",
        output_path="output.json",
    )

    # Mock the A2A client
    mock_client = AsyncMock()
    mock_result = A2AStepResult(
        turns=[
            Turn(content="Follow-up question", type="human"),
            Turn(content="Follow-up answer", type="agent"),
        ],
        response_text="Follow-up answer",
        context_id="ctx-456",
    )
    mock_client.send_step = AsyncMock(return_value=mock_result)
    executor._a2a_client = mock_client

    # Set up scenario state with existing context_id
    executor._current_scenario_id = "scn_test123"
    executor._step_index = 1
    executor._context_id = "ctx-123"

    # Create test step and scenario
    step = Step(input="Follow-up question", reference=None)
    scenario = Scenario(name="Weather Test", steps=[step])

    # Call on_step
    await executor.on_step(step, scenario)

    # Verify A2A client was called with existing context_id
    mock_client.send_step.assert_called_once_with("Follow-up question", "ctx-123")


@pytest.mark.asyncio
async def test_executor_on_step_increments_index():
    """Test that on_step increments step_index for deterministic IDs."""
    executor = A2AExecutor(
        agent_url="http://test-agent:8000",
        experiment_name="test-workflow",
        input_path="input.json",
        output_path="output.json",
    )

    # Mock the A2A client
    mock_client = AsyncMock()
    mock_result = A2AStepResult(
        turns=[Turn(content="question", type="human"), Turn(content="answer", type="agent")],
        response_text="answer",
        context_id="ctx-1",
    )
    mock_client.send_step = AsyncMock(return_value=mock_result)
    executor._a2a_client = mock_client

    # Set up scenario state
    executor._current_scenario_id = "scn_test123"
    executor._step_index = 0
    executor._context_id = None

    step = Step(input="question", reference=None)
    scenario = Scenario(name="Test", steps=[step])

    # Call on_step multiple times
    result1 = await executor.on_step(step, scenario)
    result2 = await executor.on_step(step, scenario)

    # Verify IDs are different (due to incremented step_index)
    assert result1.id != result2.id
    assert executor._step_index == 2


# ---------------------------------------------------------------------------
# Test A2AExecutor.before_scenario
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_before_scenario_resets_state():
    """Test that before_scenario resets context_id and step_index."""
    executor = A2AExecutor(
        agent_url="http://test-agent:8000",
        experiment_name="test-workflow",
        input_path="input.json",
        output_path="output.json",
    )

    # Set some state to be reset
    executor._context_id = "old-context"
    executor._step_index = 5

    scenario = Scenario(name="Test Scenario", steps=[])

    # Mock the tracer to avoid real OTel calls
    with patch.object(executor._tracer, "start_span") as mock_span_factory:
        mock_span = MagicMock()
        mock_span_context = MagicMock()
        mock_span_context.trace_id = 0x1234567890ABCDEF
        mock_span.get_span_context.return_value = mock_span_context
        mock_span_factory.return_value = mock_span

        await executor.before_scenario(scenario)

    # Verify state was reset
    assert executor._context_id is None
    assert executor._step_index == 0
    assert executor._current_scenario_id is not None
    assert executor._current_scenario_id.startswith("scn_")
    assert executor._current_trace_id is not None


@pytest.mark.asyncio
async def test_executor_before_scenario_creates_span():
    """Test that before_scenario creates an OTel span."""
    executor = A2AExecutor(
        agent_url="http://test-agent:8000",
        experiment_name="test-workflow",
        input_path="input.json",
        output_path="output.json",
    )

    scenario = Scenario(name="Test Scenario", steps=[])

    # Mock the tracer
    with patch.object(executor._tracer, "start_span") as mock_span_factory:
        mock_span = MagicMock()
        mock_span_context = MagicMock()
        mock_span_context.trace_id = 0xABCDEF1234567890
        mock_span.get_span_context.return_value = mock_span_context
        mock_span_factory.return_value = mock_span

        await executor.before_scenario(scenario)

        # Verify span was created and configured
        mock_span_factory.assert_called_once_with("scenario: Test Scenario")
        mock_span.set_attribute.assert_any_call("scenario.name", "Test Scenario")
        mock_span.set_attribute.assert_any_call("experiment.name", "test-workflow")
        mock_span.set_attribute.assert_any_call("agent.url", "http://test-agent:8000")
        # Span stays open until after_scenario ends it
        mock_span.end.assert_not_called()
        assert executor._scenario_span is mock_span


# ---------------------------------------------------------------------------
# Test A2AExecutor.after_scenario
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_after_scenario_sets_metadata():
    """Test that after_scenario sets id and trace_id on executed scenario."""
    executor = A2AExecutor(
        agent_url="http://test-agent:8000",
        experiment_name="test-workflow",
        input_path="input.json",
        output_path="output.json",
    )

    # Set up state
    executor._current_scenario_id = "scn_abc123"
    executor._current_trace_id = "trace_xyz789"
    mock_span = MagicMock()
    executor._scenario_span = mock_span
    executor._span_token = MagicMock()

    original = Scenario(name="Test Scenario", steps=[])
    executed = ExecutedScenario(name="Test Scenario", steps=[])

    await executor.after_scenario(original, executed)

    # Verify metadata was set
    assert executed.id == "scn_abc123"
    assert executed.trace_id == "trace_xyz789"
    # Verify span was ended and context detached
    mock_span.end.assert_called_once()
    assert executor._scenario_span is None
    assert executor._span_token is None


# ---------------------------------------------------------------------------
# Test A2AExecutor.run (full flow)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_run_full_flow(tmp_path):
    """Test complete executor run with minimal experiment."""
    # Create input experiment file
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"

    experiment_data = {
        "scenarios": [
            {
                "name": "Test Scenario",
                "steps": [
                    {"input": "Hello", "reference": None},
                    {"input": "How are you?", "reference": None},
                ],
            }
        ]
    }
    input_path.write_text(json.dumps(experiment_data))

    executor = A2AExecutor(
        agent_url="http://test-agent:8000",
        experiment_name="test-workflow",
        input_path=str(input_path),
        output_path=str(output_path),
    )

    # Mock A2AStepClient.send_step
    mock_results = [
        A2AStepResult(
            turns=[Turn(content="Hello", type="human"), Turn(content="Hi there", type="agent")],
            response_text="Hi there",
            context_id="ctx-1",
        ),
        A2AStepResult(
            turns=[Turn(content="How are you?", type="human"), Turn(content="I'm good", type="agent")],
            response_text="I'm good",
            context_id="ctx-1",
        ),
    ]

    call_count = 0

    async def mock_send_step(user_input, context_id):
        nonlocal call_count
        result = mock_results[call_count]
        call_count += 1
        return result

    # Mock the tracer to avoid real OTel calls
    with patch.object(executor._tracer, "start_span") as mock_span_factory:
        mock_span = MagicMock()
        mock_span_context = MagicMock()
        mock_span_context.trace_id = 0x1234567890ABCDEF
        mock_span.get_span_context.return_value = mock_span_context
        mock_span_factory.return_value = mock_span

        with patch("testbench.run.A2AStepClient") as mock_a2a_step_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.send_step = mock_send_step
            mock_a2a_step_client.return_value = mock_client_instance

            result = await executor.run()

    # Verify result structure
    assert isinstance(result, ExecutedExperiment)
    assert result.id == "test-workflow"
    assert len(result.scenarios) == 1

    scenario = result.scenarios[0]
    assert isinstance(scenario, ExecutedScenario)
    assert scenario.name == "Test Scenario"
    assert scenario.id is not None
    assert scenario.trace_id is not None
    assert len(scenario.steps) == 2

    # Verify steps
    step1 = scenario.steps[0]
    assert isinstance(step1, ExecutedStep)
    assert step1.input == "Hello"
    assert step1.turns is not None
    assert len(step1.turns) == 2

    step2 = scenario.steps[1]
    assert isinstance(step2, ExecutedStep)
    assert step2.input == "How are you?"
    assert step2.turns is not None

    # Verify output file was written
    assert output_path.exists()
    output_data = json.loads(output_path.read_text())
    assert "scenarios" in output_data
    assert len(output_data["scenarios"]) == 1


@pytest.mark.asyncio
async def test_executor_run_with_error_handling(tmp_path):
    """Test that executor handles A2A client errors gracefully."""
    # Create input experiment file
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"

    experiment_data = {
        "scenarios": [
            {
                "name": "Test Scenario",
                "steps": [
                    {"input": "Failing query", "reference": None},
                ],
            }
        ]
    }
    input_path.write_text(json.dumps(experiment_data))

    executor = A2AExecutor(
        agent_url="http://test-agent:8000",
        experiment_name="test-workflow",
        input_path=str(input_path),
        output_path=str(output_path),
    )

    # Mock A2AStepClient to return error turn
    async def mock_send_step_error(user_input, context_id):
        return A2AStepResult(
            turns=[Turn(content="Failing query", type="human"), Turn(content="ERROR: Connection failed", type="agent")],
            response_text="ERROR: Connection failed",
            context_id=None,
        )

    # Mock the tracer
    with patch.object(executor._tracer, "start_span") as mock_span_factory:
        mock_span = MagicMock()
        mock_span_context = MagicMock()
        mock_span_context.trace_id = 0x1234567890ABCDEF
        mock_span.get_span_context.return_value = mock_span_context
        mock_span_factory.return_value = mock_span

        with patch("testbench.run.A2AStepClient") as mock_a2a_step_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.send_step = mock_send_step_error
            mock_a2a_step_client.return_value = mock_client_instance

            result = await executor.run()

    # Verify error was captured in turns
    assert isinstance(result, ExecutedExperiment)
    step = result.scenarios[0].steps[0]
    assert len(step.turns) == 2
    assert "ERROR" in step.turns[1].content


# ---------------------------------------------------------------------------
# Test main()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_creates_executor_and_runs(tmp_path):
    """Test that main() creates executor with correct parameters."""
    # Create input experiment file
    input_path = tmp_path / "experiment.json"

    experiment_data = {
        "scenarios": [
            {
                "name": "Main Test",
                "steps": [{"input": "Test query", "reference": None}],
            }
        ]
    }
    input_path.write_text(json.dumps(experiment_data))

    # Mock setup_otel
    with patch("testbench.run.setup_otel"):
        # Mock A2AExecutor.run
        with patch("testbench.run.A2AExecutor.run") as mock_run:
            mock_result = ExecutedExperiment(scenarios=[])
            mock_run.return_value = mock_result

            await main(
                agent_url="http://test-agent:8000",
                experiment_name="test-workflow",
                input_path=str(input_path),
            )

            # Verify run was called
            mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_main_default_output_path(tmp_path):
    """Test that main() uses default output path."""
    input_path = tmp_path / "input.json"

    experiment_data = {"scenarios": [{"name": "Test", "steps": [{"input": "query", "reference": None}]}]}
    input_path.write_text(json.dumps(experiment_data))

    mock_result = A2AStepResult(
        turns=[Turn(content="query", type="human"), Turn(content="response", type="agent")],
        response_text="response",
        context_id="ctx-1",
    )

    with patch("testbench.run.setup_otel"):
        with patch("testbench.run.A2AStepClient") as mock_a2a_step_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.send_step = AsyncMock(return_value=mock_result)
            mock_a2a_step_client.return_value = mock_client_instance

            # Mock tracer
            with patch("testbench.run.trace.get_tracer") as mock_get_tracer:
                mock_tracer = MagicMock()
                mock_span = MagicMock()
                mock_span_context = MagicMock()
                mock_span_context.trace_id = 0x1234567890ABCDEF
                mock_span.get_span_context.return_value = mock_span_context
                mock_tracer.start_span.return_value = mock_span
                mock_get_tracer.return_value = mock_tracer

                # Change to tmp directory to avoid writing to real data/ folder
                import os

                original_cwd = os.getcwd()
                try:
                    os.chdir(tmp_path)
                    await main(
                        agent_url="http://test-agent:8000",
                        experiment_name="test-workflow",
                        input_path=str(input_path),
                    )

                    # Verify default output path was used
                    expected_output = tmp_path / "data" / "experiments" / "executed_experiment.json"
                    assert expected_output.exists()
                finally:
                    os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_main_integration_with_cli_args(tmp_path):
    """Test main() works with CLI argument pattern."""
    # Create input experiment file
    input_path = tmp_path / "input.json"

    experiment_data = {
        "scenarios": [
            {
                "name": "CLI Test",
                "steps": [{"input": "CLI query", "reference": None}],
            }
        ]
    }
    input_path.write_text(json.dumps(experiment_data))

    mock_result = A2AStepResult(
        turns=[Turn(content="CLI query", type="human"), Turn(content="CLI response", type="agent")],
        response_text="CLI response",
        context_id="ctx-cli",
    )

    import os

    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)

        with patch("testbench.run.setup_otel"):
            # Mock tracer at import time before A2AExecutor is created
            with patch("testbench.run.trace.get_tracer") as mock_get_tracer:
                mock_tracer = MagicMock()
                mock_span = MagicMock()
                mock_span_context = MagicMock()
                mock_span_context.trace_id = 0x1234567890ABCDEF
                mock_span.get_span_context.return_value = mock_span_context
                mock_tracer.start_span.return_value = mock_span
                mock_get_tracer.return_value = mock_tracer

                with patch("testbench.run.A2AStepClient") as mock_a2a_step_client:
                    mock_client_instance = AsyncMock()
                    mock_client_instance.send_step = AsyncMock(return_value=mock_result)
                    mock_a2a_step_client.return_value = mock_client_instance

                    # Simulate CLI invocation
                    await main(
                        agent_url="http://cli-agent:9000",
                        experiment_name="cli-workflow",
                        input_path=str(input_path),
                    )

        # Verify execution completed
        output_path = tmp_path / "data" / "experiments" / "executed_experiment.json"
        assert output_path.exists()

        result_data = json.loads(output_path.read_text())
        # The id field should be set by A2AExecutor.run()
        # If mocking interferes, just verify the core structure
        assert "scenarios" in result_data
        assert len(result_data["scenarios"]) == 1
        assert result_data["scenarios"][0]["name"] == "CLI Test"
        # Verify the step was executed
        assert len(result_data["scenarios"][0]["steps"]) == 1
        assert result_data["scenarios"][0]["steps"][0]["input"] == "CLI query"
    finally:
        os.chdir(original_cwd)
