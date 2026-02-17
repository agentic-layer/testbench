"""Pydantic models derived from the testbench JSON schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Common models (common.schema.json)
# ---------------------------------------------------------------------------


class ToolCall(BaseModel):
    """Expected tool call in a reference."""

    name: str
    arguments: dict[str, Any]


class Reference(BaseModel):
    """Expected reference data for evaluation."""

    response: str | None = None
    tool_calls: list[ToolCall] | None = None
    topics: list[str] | None = None


class TurnToolCall(BaseModel):
    """Tool call recorded within a conversation turn."""

    name: str
    args: dict[str, Any]


class Turn(BaseModel):
    """A single turn in a multi-turn conversation."""

    content: str
    type: Literal["human", "agent", "tool"]
    tool_calls: list[TurnToolCall] | None = None


class Metric(BaseModel):
    """Metric configuration for evaluations."""

    metric_name: str
    threshold: float | None = Field(default=None, ge=0, le=1)
    parameters: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Experiment models (experiment.schema.json)
# ---------------------------------------------------------------------------


class Step(BaseModel):
    """A single step (user input) within a scenario."""

    input: str
    reference: Reference | None = None
    custom_values: dict[str, Any] | None = None
    metrics: list[Metric] | None = None


class Scenario(BaseModel):
    """A named test scenario consisting of one or more steps."""

    name: str
    steps: list[Step]
    reference: Reference | None = None
    evaluations: list[Metric] | None = None


class Experiment(BaseModel):
    """Top-level experiment definition."""

    llm_as_a_judge_model: str | None = None
    default_threshold: float = Field(default=0.9, ge=0, le=1)
    scenarios: list[Scenario]


# ---------------------------------------------------------------------------
# Executed experiment models (executed_experiment.schema.json)
# ---------------------------------------------------------------------------


class ExecutedStep(Step):
    """A step enriched with execution results."""

    id: str | None = None
    turns: list[Turn] | None = None


class ExecutedScenario(Scenario):
    """A scenario enriched with execution metadata."""

    id: str | None = None
    trace_id: str | None = None
    steps: list[ExecutedStep]  # type: ignore[assignment]


class ExecutedExperiment(Experiment):
    """An experiment after agent execution."""

    id: str | None = None
    scenarios: list[ExecutedScenario]  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Evaluated experiment models (evaluated_experiment.schema.json)
# ---------------------------------------------------------------------------


class Result(BaseModel):
    """Outcome of a single metric evaluation."""

    result: Literal["pass", "fail"] | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    details: dict[str, Any] | None = None


class Evaluation(BaseModel):
    """A metric paired with its evaluation result."""

    metric: Metric
    result: Result


class EvaluatedStep(ExecutedStep):
    """An executed step enriched with evaluation results."""

    evaluations: list[Evaluation] | None = None


class EvaluatedScenario(ExecutedScenario):
    """An executed scenario enriched with evaluation results."""

    evaluations: list[Evaluation] | None = None  # type: ignore[assignment]
    steps: list[EvaluatedStep]  # type: ignore[assignment]


class EvaluatedExperiment(ExecutedExperiment):
    """A fully evaluated experiment."""

    scenarios: list[EvaluatedScenario]  # type: ignore[assignment]
