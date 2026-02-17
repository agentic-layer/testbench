"""Generic metrics system with framework adapter pattern."""

from metrics.adapter import FrameworkAdapter
from metrics.protocol import MetricCallable, MetricResult
from metrics.ragas_adapter import RagasFrameworkAdapter
from metrics.registry import GenericMetricsRegistry
from metrics.translation import dict_to_executed_step

__all__ = [
    "FrameworkAdapter",
    "GenericMetricsRegistry",
    "MetricCallable",
    "MetricResult",
    "RagasFrameworkAdapter",
    "dict_to_executed_step",
]
