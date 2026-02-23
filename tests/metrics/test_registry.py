"""Unit tests for the GenericMetricsRegistry."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from metrics.registry import GenericMetricsRegistry

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
