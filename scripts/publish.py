"""Publish evaluation metrics via OpenTelemetry OTLP.

Phase 4 of the evaluation pipeline. Reads an ``EvaluatedExperiment`` JSON
file and publishes per-step metric scores as OpenTelemetry gauge metrics.

Usage::

    OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318" python3 scripts/publish.py workflow exec-1 1
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import os
from logging import Logger
from typing import Any, TypeGuard

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from schema.models import (
    EvaluatedExperiment,
    EvaluatedScenario,
    EvaluatedStep,
    Scenario,
)
from schema.runtime import ExperimentRuntime

# Set up module-level logger
logging.basicConfig(level=logging.INFO)
logger: Logger = logging.getLogger(__name__)


def _is_metric_value(value: Any) -> TypeGuard[int | float]:
    """Check if a value is a valid metric score (numeric and not NaN)."""
    if not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return True


def _get_user_input_truncated(user_input: str, max_length: int = 50) -> str:
    """Truncate user input text for display in metric labels."""
    if len(user_input) <= max_length:
        return user_input
    return user_input[:max_length] + "..."


class MetricsPublisher:
    """Publish evaluation metrics via OTLP using :class:`ExperimentRuntime`.

    Uses the runtime hook pattern to iterate scenarios/steps consistently
    with the rest of the pipeline.
    """

    def __init__(
        self,
        input_path: str,
        workflow_name: str,
        execution_id: str,
        execution_number: int,
    ) -> None:
        self._input_path = input_path
        self._workflow_name = workflow_name
        self._execution_id = execution_id
        self._execution_number = execution_number

        self._disabled: bool = False
        self._provider: MeterProvider | None = None
        self._gauge: Any = None
        self._otlp_endpoint: str = ""
        self._current_trace_id: str = "missing-trace-id"
        self._current_experiment_id: str = ""
        self._current_scenario_id: str = ""
        self._current_scenario_name: str = ""
        self._current_step_index: int = 0

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    async def before_run(self, experiment: EvaluatedExperiment) -> None:  # type: ignore[override]
        """Create OTel MeterProvider, exporter, and gauge instrument."""
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otlp_endpoint is None:
            logger.warning("OTEL_EXPORTER_OTLP_ENDPOINT not set — OTLP publishing disabled")
            self._disabled = True
            return

        if not otlp_endpoint.startswith("http://") and not otlp_endpoint.startswith("https://"):
            otlp_endpoint = f"http://{otlp_endpoint}"

        self._otlp_endpoint = otlp_endpoint

        exporter = OTLPMetricExporter(endpoint=f"{otlp_endpoint}/v1/metrics")
        reader = PeriodicExportingMetricReader(exporter=exporter, export_interval_millis=3600000)
        resource = Resource.create({"service.name": "testbench", "workflow.name": self._workflow_name})
        self._provider = MeterProvider(resource=resource, metric_readers=[reader])
        metrics.set_meter_provider(self._provider)
        meter = metrics.get_meter("testbench", "1.0.0")

        self._gauge = meter.create_gauge(
            name="testbench_evaluation_metric",
            description="Evaluation metric from testbench",
            unit="",
        )

        self._current_experiment_id = experiment.id or ""
        logger.info("Pushing metrics to OTLP endpoint at %s...", otlp_endpoint)

    async def before_scenario(self, scenario: Scenario) -> None:
        """Track the current scenario's trace_id and metadata."""
        trace_id = "missing-trace-id"
        if isinstance(scenario, EvaluatedScenario) and scenario.trace_id:
            trace_id = scenario.trace_id
        self._current_trace_id = trace_id
        self._current_scenario_id = scenario.id if isinstance(scenario, EvaluatedScenario) and scenario.id else ""
        self._current_scenario_name = scenario.name
        self._current_step_index = 0

    async def on_step(self, step: EvaluatedStep, scenario: Scenario) -> EvaluatedStep:  # type: ignore[override]
        """Record gauge values for each evaluation in the step."""
        if self._disabled:
            return step

        step_id = step.id or "unknown"
        user_input_truncated = _get_user_input_truncated(step.input)

        if step.evaluations:
            for evaluation in step.evaluations:
                metric_name = evaluation.metric.metric_name
                score = evaluation.result.score

                if score is None or not _is_metric_value(score):
                    logger.debug("Skipping invalid metric value for %s: %s", metric_name, score)
                    continue

                attributes = {
                    "name": metric_name,
                    "workflow_name": self._workflow_name,
                    "execution_id": self._execution_id,
                    "execution_number": self._execution_number,
                    "experiment_id": self._current_experiment_id,
                    "scenario_id": self._current_scenario_id,
                    "scenario_name": self._current_scenario_name,
                    "step_id": step_id,
                    "step_index": str(self._current_step_index),
                    "trace_id": self._current_trace_id,
                    "threshold": str(evaluation.metric.threshold) if evaluation.metric.threshold is not None else "",
                    "result": evaluation.result.result or "",
                    "user_input_truncated": user_input_truncated,
                }
                self._gauge.set(score, attributes)  # type: ignore[arg-type]
                logger.info("testbench_evaluation_metric%s = %s", attributes, score)

        self._current_step_index += 1
        return step

    async def after_run(self, experiment: EvaluatedExperiment) -> None:  # type: ignore[override]
        """Flush and shut down the OTel provider."""
        if self._provider is None:
            return

        try:
            flush_success = self._provider.force_flush()
            if flush_success:
                logger.info("Metrics successfully pushed via OTLP")
            else:
                error_msg = f"Failed to flush metrics to OTLP endpoint at {self._otlp_endpoint}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
        except Exception:
            logger.exception("Error pushing metrics via OTLP")
            raise
        finally:
            self._provider.shutdown()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> EvaluatedExperiment:
        """Execute the publish pipeline via ExperimentRuntime."""
        runtime: ExperimentRuntime[EvaluatedExperiment, EvaluatedExperiment] = ExperimentRuntime(
            on_step=self.on_step,  # type: ignore[arg-type]
            input_path=self._input_path,
            output_path=None,
            input_model=EvaluatedExperiment,
            output_model=EvaluatedExperiment,
            before_run=self.before_run,  # type: ignore[arg-type]
            before_scenario=self.before_scenario,
            after_run=self.after_run,  # type: ignore[arg-type]
        )
        return await runtime.run()


def publish_metrics(input_file: str, workflow_name: str, execution_id: str, execution_number: int) -> None:
    """Publish evaluation metrics via OpenTelemetry OTLP.

    The OTLP endpoint is read from the ``OTEL_EXPORTER_OTLP_ENDPOINT`` environment
    variable. If the variable is not set, a warning is logged and publishing is skipped.

    Args:
        input_file: Path to the evaluated experiment JSON file.
        workflow_name: Name of the test workflow (e.g., 'weather-assistant-test').
        execution_id: Testkube execution ID for this workflow run.
        execution_number: Number of the execution for the current workflow (e.g. 3).
    """
    logger.info("Loading evaluation data from %s...", input_file)

    publisher = MetricsPublisher(
        input_path=input_file,
        workflow_name=workflow_name,
        execution_id=execution_id,
        execution_number=execution_number,
    )
    asyncio.run(publisher.run())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish evaluation metrics via OpenTelemetry OTLP")
    parser.add_argument(
        "workflow_name",
        help="Name of the test workflow (e.g., 'weather-assistant-test')",
    )
    parser.add_argument(
        "execution_id",
        help="Testkube execution ID for this workflow run",
    )
    parser.add_argument(
        "execution_number",
        help="Testkube execution number for this workflow run",
    )
    parser.add_argument(
        "--input",
        default="data/experiments/evaluated_experiment.json",
        help="Path to evaluated experiment JSON (default: data/experiments/evaluated_experiment.json)",
    )

    args = parser.parse_args()

    publish_metrics(
        input_file=args.input,
        workflow_name=args.workflow_name,
        execution_id=args.execution_id,
        execution_number=args.execution_number,
    )
