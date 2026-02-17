"""Core types for the generic metrics system."""

from dataclasses import dataclass
from typing import Any, Protocol

from schema.models import ExecutedStep


@dataclass
class MetricResult:
    """Result of a single metric evaluation."""

    score: float
    reason: str | None = None


class MetricCallable(Protocol):
    """Protocol for framework-agnostic metric callables."""

    async def __call__(self, sample: ExecutedStep, **metric_args: Any) -> MetricResult: ...
