# Generic MetricsRegistry Architecture Concept

## Purpose

This document describes a concept for transforming MetricsRegistry from a RAGAS-specific implementation into a framework-agnostic architecture that can support multiple metric frameworks (RAGAS, DeepEval, etc.).

## Problem Statement

The current `MetricsRegistry` is tightly coupled to RAGAS:

```python
class MetricsRegistry:
    def __init__(self):
        self._classes: dict[str, type[BaseMetric]] = {}  # RAGAS BaseMetric
        self._discover_metrics()

    def _discover_metrics(self) -> None:
        # Hardcoded to ragas.metrics.collections
        for name, obj in inspect.getmembers(metrics_module):
            if inspect.isclass(obj) and issubclass(obj, BaseMetric):
                self._classes[name] = obj
```

**Limitations**:
- Cannot use metrics from DeepEval or other frameworks
- Returns framework-specific instances (RAGAS `BaseMetric`)
- Assumes RAGAS conventions (llm injection, ascore method)
- Not extensible without modifying core code

## User Requirements

1. **Generic registry**: Not limited to RAGAS metrics
2. **Callable interface**: Registry returns a callable, not a metric instance
3. **Callable signature**: `async def(sample: ExecutedStep, **metric_args) -> MetricResult` (where `ExecutedStep` is defined in `scripts/schema/executed_experiment.schema.json` and `MetricResult` contains `score: float` and `reason: str | None`)
4. **Easy extensibility**: Adding new frameworks should be straightforward
5. **Configurable naming**: Support framework-prefixed names with optional aliases

## Framework Comparison

### RAGAS vs DeepEval

| Aspect | RAGAS | DeepEval |
|--------|-------|----------|
| **Base Class** | `ragas.metrics.collections.BaseMetric` | `deepeval.metrics.BaseMetric` |
| **Input Format** | Dict with flexible keys | `LLMTestCase` typed object |
| **Async Method** | `async ascore(**kwargs)` | `async a_measure(test_case)` |
| **Result Format** | `MetricResult` with `.value` | Sets `metric.score` attribute |
| **LLM Injection** | Constructor param: `__init__(llm=...)` | Per-metric: `evaluation_model=...` |
| **Discovery** | Import from collections module | Import from metrics module |

**Key Insight**: Frameworks have fundamentally different APIs, requiring an adapter pattern to unify them.

---

## Proposed Architecture

### Core Concept: Adapter Pattern

Instead of the registry working directly with framework-specific metrics, introduce an **adapter layer** that wraps framework-specific metrics behind a unified interface.

```
┌─────────────────────────────────────┐
│   GenericMetricsRegistry            │
│                                     │
│  get_metric_callable() → Callable   │
└──────────────┬──────────────────────┘
               │
       ┌───────┴──────────┐
       │                  │
┌──────▼──────┐    ┌──────▼──────┐
│   RAGAS     │    │  DeepEval   │
│  Adapter    │    │  Adapter    │
└──────┬──────┘    └──────┬──────┘
       │                  │
┌──────▼──────┐    ┌──────▼──────┐
│   RAGAS     │    │  DeepEval   │
│   Metrics   │    │   Metrics   │
└─────────────┘    └─────────────┘
```

### 1. MetricCallable Protocol

Define a **protocol** (not abstract class) that all adapters must conform to:

```python
from dataclasses import dataclass
from typing import Protocol, Any

@dataclass
class MetricResult:
    """
    Unified result from a metric evaluation.

    Attributes:
        score: Float score between 0.0 and 1.0
        reason: Optional explanation for the score (LLM-generated reasoning)
    """
    score: float
    reason: str | None = None

class MetricCallable(Protocol):
    """
    Unified interface for executing metrics across all frameworks.

    This is the callable that the registry returns to users.
    """

    async def __call__(
        self,
        sample: ExecutedStep,
        **metric_args: Any
    ) -> MetricResult:
        """
        Evaluate a single sample.

        Args:
            sample: An ExecutedStep object as defined in executed_experiment.schema.json,
                     containing input, turns, reference, custom_values, and metrics.
            **metric_args: Additional runtime arguments for the metric

        Returns:
            MetricResult containing score (0.0-1.0) and optional reason
        """
        ...
```

**Design Rationale**:
- **Protocol (not ABC)**: Enables structural subtyping - any object with `async __call__(sample, **args) -> MetricResult` satisfies the protocol
- **Structured return type**: `MetricResult` dataclass with `score: float` and `reason: str | None` — provides both the numeric result and the LLM-generated reasoning behind it
- **ExecutedStep as input**: Uses the `ExecutedStep` type defined in `executed_experiment.schema.json`, providing a structured input with `input`, `turns`, `reference`, `custom_values`, and `metrics` fields
- **Runtime args**: Allows passing additional parameters at evaluation time

### 2. FrameworkAdapter Abstract Base Class

Define an **ABC** that all framework adapters must implement:

```python
from abc import ABC, abstractmethod
from typing import Any, Type

class FrameworkAdapter(ABC):
    """
    Base class for integrating a metric framework into the registry.

    Each framework (RAGAS, DeepEval, etc.) implements this interface.
    """

    @abstractmethod
    def discover_metrics(self) -> dict[str, Type[Any]]:
        """
        Discover available metric classes from this framework.

        Returns:
            Dict mapping metric class names to their types
            Example: {"Faithfulness": <class 'ragas...Faithfulness'>}
        """
        pass

    @abstractmethod
    def create_callable(
        self,
        class_name: str,
        parameters: dict[str, Any],
        llm: Any
    ) -> MetricCallable:
        """
        Create a MetricCallable for the specified metric.

        This method:
        1. Gets the metric class from discovered metrics
        2. Instantiates it with framework-specific logic
        3. Wraps it in an adapter that conforms to MetricCallable

        Args:
            class_name: Name of metric class (e.g., "Faithfulness")
            parameters: Constructor parameters for the metric
            llm: LLM instance (may be used differently per framework)

        Returns:
            A callable conforming to MetricCallable protocol
        """
        pass

    @property
    @abstractmethod
    def framework_name(self) -> str:
        """
        Identifier for this framework (e.g., 'ragas', 'deepeval').

        Used in:
        - Config files: {"framework": "ragas", ...}
        - Result keys: "ragas.Faithfulness"
        - Error messages
        """
        pass
```

**Design Rationale**:
- **ABC (not Protocol)**: Enforces implementation inheritance
- **Discovery method**: Each framework knows how to find its metrics
- **Factory method**: Encapsulates framework-specific instantiation logic
- **LLM parameter**: Passed to adapter even though frameworks use it differently

### 3. RAGAS Adapter Implementation

#### RagasMetricCallable

Wraps a RAGAS metric instance to conform to `MetricCallable`

**Parameter filtering**: Only passes parameters the metric expects
**Format translation**: Converts generic sample → RAGAS conventions
**Result extraction**: Unwraps framework result into `MetricResult(score, reason)`
**No metric_args usage yet**: Reserved for future use

#### RagasFrameworkAdapter

Implements `FrameworkAdapter` for RAGAS

### 4. GenericMetricsRegistry

The registry manages framework adapters.

---