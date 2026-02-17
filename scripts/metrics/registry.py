"""Generic metrics registry supporting multiple frameworks."""

from __future__ import annotations

from typing import Any

from metrics.adapter import FrameworkAdapter
from metrics.protocol import MetricCallable


class GenericMetricsRegistry:
    """Framework-agnostic registry for metric discovery and creation."""

    def __init__(self) -> None:
        self._adapters: dict[str, FrameworkAdapter] = {}

    def register_adapter(self, adapter: FrameworkAdapter) -> None:
        """Register a framework adapter.

        Args:
            adapter: The FrameworkAdapter to register.
        """
        self._adapters[adapter.framework_name] = adapter

    def get_metric_callable(
        self, framework: str, class_name: str, parameters: dict[str, Any], llm: Any
    ) -> MetricCallable:
        """Get a MetricCallable for the given framework and metric class.

        Args:
            framework: Framework name (e.g. 'ragas').
            class_name: Metric class name.
            parameters: Constructor parameters.
            llm: LLM wrapper.

        Returns:
            A MetricCallable wrapping the metric.

        Raises:
            ValueError: If framework is unknown.
        """
        if framework not in self._adapters:
            raise ValueError(f"Unknown framework '{framework}'.\nAvailable: {', '.join(sorted(self._adapters.keys()))}")
        return self._adapters[framework].create_callable(class_name, parameters, llm)

    def list_metrics(self, framework: str | None = None) -> dict[str, list[str]]:
        """List available metrics, optionally filtered by framework.

        Args:
            framework: If provided, only list metrics for this framework.

        Returns:
            Dictionary mapping framework names to sorted lists of metric class names.
        """
        result: dict[str, list[str]] = {}
        adapters = self._adapters
        if framework is not None:
            if framework not in self._adapters:
                raise ValueError(f"Unknown framework '{framework}'.")
            adapters = {framework: self._adapters[framework]}

        for name, adapter in adapters.items():
            result[name] = sorted(adapter.discover_metrics().keys())

        return result

    @classmethod
    def create_default(cls) -> GenericMetricsRegistry:
        """Create a registry with the RAGAS adapter pre-registered."""
        from metrics.ragas_adapter import RagasFrameworkAdapter

        registry = cls()
        registry.register_adapter(RagasFrameworkAdapter())
        return registry
