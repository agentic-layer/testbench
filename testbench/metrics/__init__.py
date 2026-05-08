"""Generic metrics system with framework adapter pattern."""

from testbench.metrics.adapter import FrameworkAdapter
from testbench.metrics.protocol import MetricCallable, MetricResult
from testbench.metrics.ragas.adapter import RagasFrameworkAdapter
from testbench.metrics.registry import GenericMetricsRegistry

__all__ = [
    "FrameworkAdapter",
    "GenericMetricsRegistry",
    "MetricCallable",
    "MetricResult",
    "RagasFrameworkAdapter",
]
