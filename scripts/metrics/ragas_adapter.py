"""RAGAS framework adapter for the generic metrics system."""

import inspect
import logging
from typing import Any, Union

import ragas.metrics.collections as metrics_module
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from ragas.metrics.collections import BaseMetric
from schema.models import ExecutedStep, ToolCall, Turn

from metrics.adapter import FrameworkAdapter
from metrics.protocol import MetricCallable, MetricResult

logger = logging.getLogger(__name__)


class RagasMetricCallable:
    """Wraps a RAGAS BaseMetric instance as a MetricCallable."""

    def __init__(self, metric: BaseMetric) -> None:
        self._metric = metric
        # Inspect ascore signature to know which params it accepts
        self._expected_params = set(inspect.signature(metric.ascore).parameters.keys())

    async def __call__(self, sample: ExecutedStep, **metric_args: Any) -> MetricResult:
        """Evaluate a sample using the wrapped RAGAS metric.

        Args:
            sample: ExecutedStep to evaluate.
            **metric_args: Additional arguments (unused currently).

        Returns:
            MetricResult with the score.
        """
        params = self._build_ragas_params(sample)

        # Filter to only params that ascore expects
        filtered = {k: v for k, v in params.items() if k in self._expected_params}

        result = await self._metric.ascore(**filtered)  # type: ignore[call-arg]
        return MetricResult(score=result.value)

    def _build_ragas_params(self, sample: ExecutedStep) -> dict[str, Any]:
        """Map an ExecutedStep to the dict format RAGAS ascore expects."""
        params: dict[str, Any] = {}

        # Multi-turn: convert turns to LangChain messages
        if sample.turns:
            params["user_input"] = self._map_user_input(sample.turns)
        else:
            params["user_input"] = sample.input

        # Extract RAGAS-specific fields from custom_values
        cv = sample.custom_values or {}
        if "response" in cv:
            params["response"] = cv["response"]
        if "retrieved_contexts" in cv:
            params["retrieved_contexts"] = cv["retrieved_contexts"]

        # Reference
        if sample.reference:
            if sample.reference.response is not None:
                params["reference"] = sample.reference.response
            if sample.reference.tool_calls:
                params["reference_tool_calls"] = self._map_reference_tool_calls(sample.reference.tool_calls)

        return params

    @staticmethod
    def _map_user_input(turns: list[Turn]) -> list[Union[HumanMessage, AIMessage, ToolMessage]]:
        """Convert Turn objects to LangChain message types."""
        mapped: list[Union[HumanMessage, AIMessage, ToolMessage]] = []
        for turn in turns:
            if turn.type == "human":
                mapped.append(HumanMessage(content=turn.content))
            elif turn.type == "agent":
                mapped.append(AIMessage(content=turn.content))
            elif turn.type == "tool":
                tool_call_id = ""
                if turn.tool_calls:
                    tool_call_id = turn.tool_calls[0].name
                mapped.append(ToolMessage(content=turn.content, tool_call_id=tool_call_id))
            else:
                logger.warning(f"Unknown turn type '{turn.type}', treating as human message")
                mapped.append(HumanMessage(content=turn.content))
        return mapped

    @staticmethod
    def _map_reference_tool_calls(tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
        """Convert ToolCall models to RAGAS-expected dict format."""
        return [
            {
                "name": tc.name,
                "args": tc.arguments,
                "id": "",
            }
            for tc in tool_calls
        ]


class RagasFrameworkAdapter(FrameworkAdapter):
    """Adapter for the RAGAS evaluation framework."""

    def __init__(self) -> None:
        self._classes: dict[str, type[BaseMetric]] = {}
        self._do_discover()

    def _do_discover(self) -> None:
        """Discover metric classes from ragas.metrics.collections."""
        for name, obj in inspect.getmembers(metrics_module):
            if name.startswith("_"):
                continue
            if inspect.isclass(obj) and issubclass(obj, BaseMetric) and obj is not BaseMetric:
                self._classes[name] = obj

    def discover_metrics(self) -> dict[str, type[Any]]:
        """Return discovered RAGAS metric classes."""
        return dict(self._classes)

    def create_callable(self, class_name: str, parameters: dict[str, Any], llm: Any) -> MetricCallable:
        """Instantiate a RAGAS metric and wrap it as a MetricCallable.

        Args:
            class_name: Name of the RAGAS metric class.
            parameters: Constructor parameters.
            llm: LLM wrapper to inject.

        Returns:
            RagasMetricCallable wrapping the instantiated metric.

        Raises:
            ValueError: If class_name is unknown or instantiation fails.
        """
        if class_name not in self._classes:
            raise ValueError(
                f"Unknown RAGAS metric class '{class_name}'.\nAvailable: {', '.join(sorted(self._classes.keys()))}"
            )

        metric_class = self._classes[class_name]
        try:
            params_with_llm = {**parameters, "llm": llm}
            metric = metric_class(**params_with_llm)
        except TypeError as e:
            sig = inspect.signature(metric_class.__init__)
            raise ValueError(f"Invalid parameters for {class_name}: {e}\nExpected signature: {sig}")

        return RagasMetricCallable(metric)  # type: ignore[return-value]

    @property
    def framework_name(self) -> str:
        return "ragas"
