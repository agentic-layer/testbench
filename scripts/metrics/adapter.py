"""Abstract base class for framework adapters."""

from abc import ABC, abstractmethod
from typing import Any

from metrics.protocol import MetricCallable


class FrameworkAdapter(ABC):
    """Base class for metric framework adapters."""

    @abstractmethod
    def discover_metrics(self) -> dict[str, type[Any]]:
        """Discover available metric classes from the framework.

        Returns:
            Dictionary mapping class names to their types.
        """

    @abstractmethod
    def create_callable(self, class_name: str, parameters: dict[str, Any], llm: str) -> MetricCallable:
        """Create a MetricCallable for the given metric class.

        Args:
            class_name: Name of the metric class.
            parameters: Constructor parameters for the metric.
            llm: LLM model name (e.g. 'gemini-2.5-flash-lite').

        Returns:
            A MetricCallable that wraps the framework-specific metric.

        Raises:
            ValueError: If class_name is unknown or parameters are invalid.
        """

    @property
    @abstractmethod
    def framework_name(self) -> str:
        """Return the name of this framework (e.g. 'ragas', 'deepeval')."""
