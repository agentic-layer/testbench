"""RAGAS framework adapter for the generic metrics system."""

import inspect
import logging
from typing import Any, Union

import ragas.metrics.collections as metrics_module
from openai import AsyncOpenAI
from ragas.llms import llm_factory
from ragas.messages import AIMessage, HumanMessage, ToolMessage
from ragas.messages import ToolCall as RagasToolCall
from ragas.metrics.collections import BaseMetric

from testbench.metrics.adapter import FrameworkAdapter
from testbench.metrics.protocol import MetricCallable, MetricResult
from testbench.schema.models import ExecutedStep, ToolCall, Turn

logger = logging.getLogger(__name__)


class RagasMetricCallable:
    """Wraps a RAGAS BaseMetric instance as a MetricCallable."""

    def __init__(self, metric: BaseMetric) -> None:
        self._metric = metric
        # Inspect ascore signature to know which params it accepts
        sig = inspect.signature(metric.ascore)
        self._expected_params = set(sig.parameters.keys())
        # Check whether ascore expects user_input as list (multi-turn) or str (single-turn)
        user_input_param = sig.parameters.get("user_input")
        self._expects_list_input = user_input_param is not None and "list" in str(user_input_param.annotation).lower()

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

        # Multi-turn: convert turns to RAGAS messages or use single input string for single-turn metrics
        if self._expects_list_input:
            params["user_input"] = self._map_user_input(sample.turns or [])
        else:
            params["user_input"] = sample.input

        last_ai = next(
            (t.content for t in reversed(sample.turns or []) if t.type == "agent"),
            sample.input,
        )
        params["response"] = last_ai

        # Reference
        if sample.reference:
            if sample.reference.response is not None:
                params["reference"] = sample.reference.response
            if sample.reference.tool_calls:
                params["reference_tool_calls"] = self._map_reference_tool_calls(sample.reference.tool_calls)
            if sample.reference.topics:
                params["reference_topics"] = sample.reference.topics
            if sample.reference.retrieved_contexts:
                params["retrieved_contexts"] = sample.reference.retrieved_contexts

        return params

    @staticmethod
    def _map_user_input(turns: list[Turn]) -> list[Union[HumanMessage, AIMessage, ToolMessage]]:
        """Convert Turn objects to LangChain message types."""
        mapped: list[Union[HumanMessage, AIMessage, ToolMessage]] = []
        for turn in turns:
            if turn.type == "human":
                mapped.append(HumanMessage(content=turn.content))
            elif turn.type == "agent":
                tool_calls = [RagasToolCall(name=tc.name, args=tc.args) for tc in (turn.tool_calls or [])]
                mapped.append(AIMessage(content=turn.content, tool_calls=tool_calls or None))
            elif turn.type == "tool":
                mapped.append(ToolMessage(content=turn.content))
            else:
                logger.warning(f"Unknown turn type '{turn.type}', treating as human message")
                mapped.append(HumanMessage(content=turn.content))
        return mapped

    @staticmethod
    def _map_reference_tool_calls(tool_calls: list[ToolCall]) -> list[ToolCall]:
        """Convert ToolCall models to RAGAS-expected format."""
        return [
            RagasToolCall(  # type: ignore[misc]
                name=tc.name,
                args=tc.args,
            )
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

    def create_callable(self, class_name: str, parameters: dict[str, Any], llm: str) -> MetricCallable:
        """Instantiate a RAGAS metric and wrap it as a MetricCallable.

        Args:
            class_name: Name of the RAGAS metric class.
            parameters: Constructor parameters.
            llm: LLM model name (e.g. 'gemini-2.5-flash-lite').

        Returns:
            RagasMetricCallable wrapping the instantiated metric.

        Raises:
            ValueError: If class_name is unknown or instantiation fails.
        """
        if class_name not in self._classes:
            raise ValueError(
                f"Unknown RAGAS metric class '{class_name}'.\nAvailable: {', '.join(sorted(self._classes.keys()))}"
            )

        client = AsyncOpenAI()
        llm_instance = llm_factory(llm, client=client)  # type: ignore[arg-type]

        metric_class = self._classes[class_name]
        try:
            params_with_llm = {**parameters, "llm": llm_instance}
            metric = metric_class(**params_with_llm)
        except TypeError as e:
            sig = inspect.signature(metric_class.__init__)
            raise ValueError(f"Invalid parameters for {class_name}: {e}\nExpected signature: {sig}")

        return RagasMetricCallable(metric)  # type: ignore[return-value]

    @property
    def framework_name(self) -> str:
        return "ragas"
