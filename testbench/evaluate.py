"""Evaluate an ExecutedExperiment using metrics defined in the schema.

Reads an ``executed_experiment.json``, evaluates each step's metrics via the
generic metrics registry, and writes an ``evaluated_experiment.json``.

Usage::

    python3 scripts/evaluate.py --model gemini-2.5-flash-lite
    python3 scripts/evaluate.py --input data/experiments/executed_experiment.json
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Literal

from testbench.metrics import GenericMetricsRegistry, MetricResult
from testbench.schema.models import (
    EvaluatedExperiment,
    EvaluatedStep,
    Evaluation,
    ExecutedExperiment,
    ExecutedScenario,
    ExecutedStep,
    Experiment,
    Metric,
    Result,
    Scenario,
)
from testbench.schema.runtime import ExperimentRuntime

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

    def __init__(self, input_path: str, output_path: str) -> None:
        self.input_path = input_path
        self.output_path = output_path

        self._registry = GenericMetricsRegistry.create_default()
        self._model: str = ""
        self._cli_model: str | None = None
        self._default_threshold: float = 0.9

        # Per-scenario collection state (reset in before_scenario)
        self._current_steps: list[EvaluatedStep] = []

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    async def before_run(self, experiment: Experiment) -> None:
        """Extract default_threshold and model from the parsed experiment."""
        self._default_threshold = experiment.default_threshold
        # CLI model overrides experiment's llm_as_a_judge_model
        if self._cli_model:
            self._model = self._cli_model
        else:
            self._model = experiment.llm_as_a_judge_model or ""

    async def before_scenario(self, scenario: Scenario) -> None:
        """Reset per-scenario step collection."""
        self._current_steps = []
        logger.info("Evaluating scenario '%s'", scenario.name)

    async def after_scenario(self, original: Scenario, executed: Scenario) -> None:
        """Finalise collected steps for this scenario."""
        logger.info("Scenario '%s' evaluated (%d steps)", original.name, len(self._current_steps))

    async def on_step(self, step: ExecutedStep, scenario: ExecutedScenario) -> EvaluatedStep:
        """Evaluate all metrics defined on *step* and return an ``EvaluatedStep``."""
        evaluations: list[Evaluation] = []
        metrics: list[Metric] = step.metrics or []

        for metric in metrics:
            try:
                params = metric.parameters or {}
                callable_ = self._registry.get_metric_callable("ragas", metric.metric_name, params, self._model)
                result: MetricResult = await callable_(step)
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
            input=step.input,
            reference=step.reference,
            custom_values=step.custom_values,
            metrics=step.metrics,
            id=step.id,
            turns=step.turns,
            evaluations=evaluations if evaluations else None,
        )
        self._current_steps.append(evaluated)
        return evaluated

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> EvaluatedExperiment:
        """Execute evaluation across all scenarios and return a fully-typed result."""
        self._current_steps = []

        runtime: ExperimentRuntime[ExecutedExperiment, EvaluatedExperiment] = ExperimentRuntime(
            on_step=self.on_step,  # type: ignore[arg-type]
            input_path=self.input_path,
            output_path=self.output_path,
            input_model=ExecutedExperiment,
            output_model=EvaluatedExperiment,
            before_run=self.before_run,
            before_scenario=self.before_scenario,
            after_scenario=self.after_scenario,
        )

        result = await runtime.run()

        logger.info("Evaluation complete: %d scenarios", len(result.scenarios))
        return result


async def main(input_path: str, output_path: str, model: str | None = None) -> None:
    """Load an executed experiment, evaluate it, and write the result."""
    evaluator = MetricEvaluator(
        input_path=input_path,
        output_path=output_path,
    )
    if model:
        evaluator._cli_model = model
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
    parser.add_argument(
        "--model",
        default=None,
        help="LLM model for evaluation (overrides experiment's llm_as_a_judge_model)",
    )
    args = parser.parse_args()

    asyncio.run(main(args.input, args.output, args.model))
