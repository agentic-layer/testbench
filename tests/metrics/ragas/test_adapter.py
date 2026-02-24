"""Unit tests for the RAGAS framework adapter and metric callable."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from metrics.protocol import MetricResult
from schema.models import ExecutedStep, Reference, Turn

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
