"""Generic metrics system with framework adapter pattern."""

from metrics.adapter import FrameworkAdapter
from metrics.protocol import MetricCallable, MetricResult
from metrics.ragas.adapter import RagasFrameworkAdapter
from metrics.registry import GenericMetricsRegistry

__all__ = [
    "FrameworkAdapter",
    "GenericMetricsRegistry",
    "MetricCallable",
    "MetricResult",
    "RagasFrameworkAdapter",
]
