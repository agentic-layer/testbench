"""
Unit tests for the generic metrics package.

Tests adapter, registry, translation, and callable components.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "testbench"))

from metrics.protocol import MetricResult
from metrics.ragas.translation import dict_to_executed_step
from metrics.registry import GenericMetricsRegistry
from schema.models import ExecutedStep, Reference, Turn

# ── dict_to_executed_step tests ──────────────────────────────────────────


class TestDictToExecutedStep:
    def test_single_turn_basic(self):
        """Single-turn row maps user_input to input, response to custom_values."""
        row = {
            "user_input": "What is the weather?",
            "response": "It is sunny.",
            "retrieved_contexts": ["Context about weather"],
            "reference": "Expected answer",
        }
        step = dict_to_executed_step(row)

        assert isinstance(step, ExecutedStep)
        assert step.input == "What is the weather?"
        assert step.turns is None
        assert step.custom_values is not None
        assert step.custom_values["response"] == "It is sunny."
        assert step.custom_values["retrieved_contexts"] == ["Context about weather"]
        assert step.reference is not None
        assert step.reference.response == "Expected answer"

    def test_multi_turn(self):
        """Multi-turn row: user_input list -> turns, first human msg -> input."""
        row = {
            "user_input": [
                {"content": "Hello", "type": "human"},
                {"content": "Hi there!", "type": "ai"},
                {"content": "What's the weather?", "type": "human"},
            ],
            "response": "It is sunny.",
        }
        step = dict_to_executed_step(row)

        assert step.input == "Hello"
        assert step.turns is not None
        assert len(step.turns) == 3
        assert step.turns[0].type == "human"
        assert step.turns[1].type == "agent"  # 'ai' normalized to 'agent'
        assert step.turns[2].type == "human"

    def test_with_reference_tool_calls(self):
        """Reference tool calls are mapped to Reference.tool_calls."""
        row = {
            "user_input": "Call the tool",
            "reference_tool_calls": [
                {"name": "get_weather", "args": {"city": "Berlin"}},
                {"name": "get_time", "arguments": {"tz": "CET"}},
            ],
        }
        step = dict_to_executed_step(row)

        assert step.reference is not None
        assert step.reference.tool_calls is not None
        assert len(step.reference.tool_calls) == 2
        assert step.reference.tool_calls[0].name == "get_weather"
        assert step.reference.tool_calls[0].arguments == {"city": "Berlin"}
        # 'args' key should also work (fallback)
        assert step.reference.tool_calls[1].name == "get_time"
        assert step.reference.tool_calls[1].arguments == {"tz": "CET"}

    def test_minimal_input(self):
        """Minimal row with just user_input."""
        row = {"user_input": "Hello"}
        step = dict_to_executed_step(row)

        assert step.input == "Hello"
        assert step.reference is None
        assert step.turns is None

    def test_sample_hash_as_id(self):
        """sample_hash is used as step id."""
        row = {"user_input": "Q", "sample_hash": "abc123"}
        step = dict_to_executed_step(row)
        assert step.id == "abc123"

    def test_explicit_id(self):
        """Explicit 'id' field takes precedence."""
        row = {"user_input": "Q", "id": "explicit-id", "sample_hash": "hash"}
        step = dict_to_executed_step(row)
        assert step.id == "explicit-id"

    def test_turns_from_row(self):
        """Turns field in row is parsed when user_input is string."""
        row = {
            "user_input": "Hello",
            "turns": [
                {"content": "Hello", "type": "human"},
                {"content": "Hi!", "type": "ai"},
            ],
        }
        step = dict_to_executed_step(row)
        assert step.turns is not None
        assert len(step.turns) == 2
        assert step.turns[1].type == "agent"


# ── RagasFrameworkAdapter tests ──────────────────────────────────────────


class TestRagasFrameworkAdapter:
    def test_discovery(self):
        """Adapter discovers RAGAS metric classes."""
        from metrics.ragas.adapter import RagasFrameworkAdapter

        adapter = RagasFrameworkAdapter()
        metrics = adapter.discover_metrics()
        assert len(metrics) > 0

    def test_framework_name(self):
        """Adapter reports correct framework name."""
        from metrics.ragas.adapter import RagasFrameworkAdapter

        adapter = RagasFrameworkAdapter()
        assert adapter.framework_name == "ragas"

    def test_create_callable_success(self):
        """Adapter creates callable for valid metric class."""
        from metrics.ragas.adapter import RagasFrameworkAdapter

        adapter = RagasFrameworkAdapter()
        metrics = adapter.discover_metrics()
        if not metrics:
            pytest.skip("No RAGAS metrics available")

        mock_llm = MagicMock()

        # Try to find a class that can be instantiated
        for class_name in metrics:
            try:
                callable_ = adapter.create_callable(class_name, {}, mock_llm)
                assert callable_ is not None
                return
            except (TypeError, ValueError):
                continue
        pytest.skip("No RAGAS metrics can be instantiated without parameters")

    def test_create_callable_unknown_class(self):
        """Adapter raises ValueError for unknown class."""
        from metrics.ragas.adapter import RagasFrameworkAdapter

        adapter = RagasFrameworkAdapter()
        mock_llm = MagicMock()

        with pytest.raises(ValueError, match="Unknown RAGAS metric class"):
            adapter.create_callable("NonexistentMetric", {}, mock_llm)


# ── RagasMetricCallable tests ────────────────────────────────────────────


class TestRagasMetricCallable:
    @pytest.mark.asyncio
    async def test_callable_returns_metric_result(self):
        """RagasMetricCallable wraps metric.ascore and returns MetricResult."""
        from metrics.ragas.adapter import RagasMetricCallable

        # Create a mock RAGAS metric
        mock_metric = MagicMock()
        mock_metric.name = "test_metric"

        # Mock ascore to return a result with .value
        mock_result = MagicMock()
        mock_result.value = 0.85
        mock_metric.ascore = AsyncMock(return_value=mock_result)

        callable_ = RagasMetricCallable(mock_metric)

        step = ExecutedStep(
            input="What is the weather?",
            custom_values={"response": "It is sunny.", "retrieved_contexts": ["weather context"]},
            reference=Reference(response="Expected answer"),
        )

        result = await callable_(step)
        assert isinstance(result, MetricResult)
        assert result.score == 0.85
        mock_metric.ascore.assert_called_once()

    @pytest.mark.asyncio
    async def test_callable_multi_turn(self):
        """RagasMetricCallable handles multi-turn steps by converting to LangChain messages."""
        from metrics.ragas.adapter import RagasMetricCallable

        mock_metric = MagicMock()
        mock_metric.name = "test_metric"

        mock_result = MagicMock()
        mock_result.value = 0.9
        mock_metric.ascore = AsyncMock(return_value=mock_result)

        callable_ = RagasMetricCallable(mock_metric)

        step = ExecutedStep(
            input="Hello",
            turns=[
                Turn(content="Hello", type="human"),
                Turn(content="Hi there!", type="agent"),
            ],
            custom_values={"response": "Hi there!"},
        )

        result = await callable_(step)
        assert result.score == 0.9

        # Verify user_input was converted to LangChain messages
        call_kwargs = mock_metric.ascore.call_args
        if "user_input" in (call_kwargs.kwargs if call_kwargs.kwargs else {}):
            user_input = call_kwargs.kwargs["user_input"]
            assert isinstance(user_input, list)


# ── GenericMetricsRegistry tests ─────────────────────────────────────────


class TestGenericMetricsRegistry:
    def test_create_default(self):
        """create_default registers the RAGAS adapter."""
        registry = GenericMetricsRegistry.create_default()
        metrics = registry.list_metrics()
        assert "ragas" in metrics
        assert len(metrics["ragas"]) > 0

    def test_register_adapter(self):
        """Custom adapter can be registered."""
        registry = GenericMetricsRegistry()

        mock_adapter = MagicMock()
        mock_adapter.framework_name = "test_framework"
        mock_adapter.discover_metrics.return_value = {"TestMetric": MagicMock}

        registry.register_adapter(mock_adapter)

        metrics = registry.list_metrics("test_framework")
        assert "test_framework" in metrics
        assert "TestMetric" in metrics["test_framework"]

    def test_get_metric_callable(self):
        """get_metric_callable delegates to the correct adapter."""
        registry = GenericMetricsRegistry()

        mock_callable = AsyncMock()
        mock_adapter = MagicMock()
        mock_adapter.framework_name = "test_fw"
        mock_adapter.create_callable.return_value = mock_callable

        registry.register_adapter(mock_adapter)

        result = registry.get_metric_callable("test_fw", "SomeMetric", {"p": 1}, "llm")
        assert result is mock_callable
        mock_adapter.create_callable.assert_called_once_with("SomeMetric", {"p": 1}, "llm")

    def test_unknown_framework_error(self):
        """get_metric_callable raises for unknown framework."""
        registry = GenericMetricsRegistry()

        with pytest.raises(ValueError, match="Unknown framework 'nonexistent'"):
            registry.get_metric_callable("nonexistent", "Metric", {}, "llm")

    def test_list_metrics_filtered(self):
        """list_metrics can filter by framework."""
        registry = GenericMetricsRegistry.create_default()

        ragas_only = registry.list_metrics("ragas")
        assert "ragas" in ragas_only
        assert len(ragas_only) == 1

    def test_list_metrics_unknown_framework(self):
        """list_metrics raises for unknown framework."""
        registry = GenericMetricsRegistry()

        with pytest.raises(ValueError, match="Unknown framework"):
            registry.list_metrics("nonexistent")
