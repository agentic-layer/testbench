"""Evaluate an ExecutedExperiment using metrics defined in the schema.

Reads an ``executed_experiment.json``, evaluates each step's metrics via the
generic metrics registry, and writes an ``evaluated_experiment.json``.

Usage::

    python3 scripts/examples/evaluate_experiment.py gemini-2.5-flash-lite
    python3 scripts/examples/evaluate_experiment.py --input data/experiments/executed_experiment.json
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any, Literal

from metrics import GenericMetricsRegistry, MetricResult
from openai import AsyncOpenAI
from ragas.llms import llm_factory
from schema.models import (
    EvaluatedExperiment,
    EvaluatedStep,
    Evaluation,
    ExecutedExperiment,
    ExecutedStep,
    Metric,
    Result,
    Scenario,
    Step,
)
from schema.runtime import ExperimentRuntime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MetricEvaluator:
    """Evaluate metrics for each step of an executed experiment.

    Uses :class:`ExperimentRuntime` with ``input_model=ExecutedExperiment``
    and ``output_model=EvaluatedExperiment`` so that the loaded JSON is
    parsed with full ``ExecutedStep`` fields (``id``, ``turns``, etc.)
    and the output is validated as ``EvaluatedExperiment`` with proper
    ``EvaluatedStep`` / ``EvaluatedScenario`` types.
    """

    def __init__(self, model: str, input_path: str, output_path: str) -> None:
        self.model = model
        self.input_path = input_path
        self.output_path = output_path

        self._registry = GenericMetricsRegistry.create_default()
        self._llm: Any = None
        self._default_threshold: float = 0.9

        # Per-scenario collection state (reset in before_scenario)
        self._current_steps: list[EvaluatedStep] = []

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    async def before_scenario(self, scenario: Scenario) -> None:
        """Reset per-scenario step collection."""
        self._current_steps = []
        logger.info("Evaluating scenario '%s'", scenario.name)

    async def after_scenario(self, original: Scenario, executed: Scenario) -> None:
        """Finalise collected steps for this scenario."""
        logger.info("Scenario '%s' evaluated (%d steps)", original.name, len(self._current_steps))

    async def on_step(self, step: Step, scenario: Scenario) -> EvaluatedStep:
        """Evaluate all metrics defined on *step* and return an ``EvaluatedStep``."""
        executed_step: ExecutedStep = step  # type: ignore[assignment]

        evaluations: list[Evaluation] = []
        metrics: list[Metric] = executed_step.metrics or []

        for metric in metrics:
            try:
                params = metric.parameters or {}
                available = self._registry.list_metrics()
                logger.info("  Available metrics: %s", available)
                callable_ = self._registry.get_metric_callable("ragas", metric.metric_name, params, self._llm)
                result: MetricResult = await callable_(executed_step)
                score = result.score

                threshold = metric.threshold if metric.threshold is not None else self._default_threshold
                pass_fail: Literal["pass", "fail"] = "pass" if score >= threshold else "fail"

                evaluations.append(
                    Evaluation(
                        metric=metric,
                        result=Result(result=pass_fail, score=score),
                    )
                )
                logger.info(
                    "  Metric '%s': score=%.3f threshold=%.3f → %s",
                    metric.metric_name,
                    score,
                    threshold,
                    pass_fail,
                )
            except Exception:
                logger.exception("  Metric '%s' failed, skipping", metric.metric_name)

        evaluated = EvaluatedStep(
            input=executed_step.input,
            reference=executed_step.reference,
            custom_values=executed_step.custom_values,
            metrics=executed_step.metrics,
            id=executed_step.id,
            turns=executed_step.turns,
            evaluations=evaluations if evaluations else None,
        )
        self._current_steps.append(evaluated)
        return evaluated

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> EvaluatedExperiment:
        """Execute evaluation across all scenarios and return a fully-typed result."""
        import json

        # Read default_threshold from the experiment BEFORE evaluating steps.
        with open(self.input_path) as f:
            exp_data = json.load(f)
        self._default_threshold = exp_data.get("default_threshold", 0.9)

        ragas_llm: AsyncOpenAI = AsyncOpenAI(api_key="Placeholder->NotUsed")
        self._llm = llm_factory(self.model, client=ragas_llm)  # type: ignore[arg-type]

        self._current_steps = []

        runtime: ExperimentRuntime[ExecutedExperiment, EvaluatedExperiment] = ExperimentRuntime(
            on_step=self.on_step,
            input_path=self.input_path,
            output_path=self.output_path,
            input_model=ExecutedExperiment,
            output_model=EvaluatedExperiment,
            before_scenario=self.before_scenario,
            after_scenario=self.after_scenario,
        )

        result = await runtime.run()

        logger.info("Evaluation complete: %d scenarios", len(result.scenarios))
        return result


async def main(model: str, input_path: str, output_path: str) -> None:
    """Load an executed experiment, evaluate it, and write the result."""
    evaluator = MetricEvaluator(
        model=model,
        input_path=input_path,
        output_path=output_path,
    )
    await evaluator.run()
    logger.info("Wrote evaluated experiment to %s", output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate an executed experiment using RAGAS metrics")
    parser.add_argument(
        "--input",
        default="data/experiments/executed_experiment.json",
        help="Path to executed experiment JSON (default: data/experiments/executed_experiment.json)",
    )
    parser.add_argument(
        "--output",
        default="data/experiments/evaluated_experiment.json",
        help="Path for evaluated experiment JSON (default: data/experiments/evaluated_experiment.json)",
    )
    args = parser.parse_args()

    # Read model from the experiment's llm_as_a_judge_model field
    import json

    with open(args.input) as f:
        exp_data = json.load(f)
    model = exp_data.get("llm_as_a_judge_model")
    if model is None:
        parser.error("Experiment has no llm_as_a_judge_model field")

    asyncio.run(main(model, args.input, args.output))
