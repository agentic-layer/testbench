"""Publish evaluation metrics via OpenTelemetry OTLP.

Phase 4 of the evaluation pipeline. Reads an ``EvaluatedExperiment`` JSON
file and publishes per-step metric scores as OpenTelemetry gauge metrics.

Usage::

    OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318" python3 testbench/publish.py workflow exec-1 1
"""

import argparse
import logging
import math
import os
from logging import Logger
from pathlib import Path
from typing import Any, TypeGuard

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from schema.models import EvaluatedExperiment

# Set up module-level logger
logging.basicConfig(level=logging.INFO)
logger: Logger = logging.getLogger(__name__)


def load_evaluation_data(file_path: str) -> EvaluatedExperiment:
    """Load an EvaluatedExperiment from a JSON file.

    Args:
        file_path: Path to the evaluated experiment JSON file.

    Returns:
        Parsed EvaluatedExperiment model.
    """
    data = Path(file_path).read_text()
    return EvaluatedExperiment.model_validate_json(data)


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


def create_and_push_metrics(
    experiment: EvaluatedExperiment, workflow_name: str, execution_id: str, execution_number: int
) -> None:
    """Create OpenTelemetry metrics for evaluation results and push via OTLP.

    Creates per-step gauges for each metric evaluation.

    The OTLP endpoint is read from the OTEL_EXPORTER_OTLP_ENDPOINT environment variable,
    with a default of 'http://localhost:4318' if not set.

    Args:
        experiment: The evaluated experiment with metric scores.
        workflow_name: Name of the test workflow (used as label to distinguish workflows).
        execution_id: Testkube execution ID for this workflow run.
        execution_number: Number of the execution for the current workflow.
    """
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    if not otlp_endpoint.startswith("http://") and not otlp_endpoint.startswith("https://"):
        otlp_endpoint = f"http://{otlp_endpoint}"

    exporter = OTLPMetricExporter(endpoint=f"{otlp_endpoint}/v1/metrics")
    reader = PeriodicExportingMetricReader(exporter=exporter, export_interval_millis=3600000)
    resource = Resource.create({"service.name": "ragas-evaluation", "workflow.name": workflow_name})
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    meter = metrics.get_meter("ragas.evaluation", "1.0.0")

    try:
        logger.info(f"Pushing metrics to OTLP endpoint at {otlp_endpoint}...")

        # Single gauge for all evaluation metrics, differentiated by 'name' attribute
        metric_gauge = meter.create_gauge(
            name="testbench_evaluation_metric",
            description="Evaluation metric from RAGAS testbench",
            unit="",
        )

        # Iterate scenarios → steps → evaluations
        for scenario in experiment.scenarios:
            trace_id = scenario.trace_id or "missing-trace-id"

            for step in scenario.steps:
                step_id = step.id or "unknown"
                user_input_truncated = _get_user_input_truncated(step.input)

                if not step.evaluations:
                    continue

                for evaluation in step.evaluations:
                    metric_name = evaluation.metric.metric_name
                    score = evaluation.result.score

                    if score is None or not _is_metric_value(score):
                        logger.debug(f"Skipping invalid metric value for {metric_name}: {score}")
                        continue

                    attributes = {
                        "name": metric_name,
                        "workflow_name": workflow_name,
                        "execution_id": execution_id,
                        "execution_number": execution_number,
                        "trace_id": trace_id,
                        "step_id": step_id,
                        "user_input_truncated": user_input_truncated,
                    }
                    metric_gauge.set(score, attributes)  # type: ignore[arg-type]
                    logger.info(f"testbench_evaluation_metric{attributes} = {score}")

        # force_flush() returns True if successful, False otherwise
        flush_success = provider.force_flush()
        if flush_success:
            logger.info("Metrics successfully pushed via OTLP")
        else:
            error_msg = f"Failed to flush metrics to OTLP endpoint at {otlp_endpoint}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
    except Exception as e:
        logger.error(f"Error pushing metrics via OTLP: {e}")
        raise
    finally:
        provider.shutdown()


def publish_metrics(input_file: str, workflow_name: str, execution_id: str, execution_number: int) -> None:
    """Publish evaluation metrics via OpenTelemetry OTLP.

    The OTLP endpoint is read from the OTEL_EXPORTER_OTLP_ENDPOINT environment variable,
    with a default of 'http://localhost:4318' if not set.

    Args:
        input_file: Path to the evaluated experiment JSON file.
        workflow_name: Name of the test workflow (e.g., 'weather-assistant-test').
        execution_id: Testkube execution ID for this workflow run.
        execution_number: Number of the execution for the current workflow (e.g. 3).
    """
    logger.info(f"Loading evaluation data from {input_file}...")
    experiment = load_evaluation_data(input_file)

    step_count = sum(len(s.steps) for s in experiment.scenarios)
    if step_count == 0:
        logger.warning("No evaluation results found. Skipping metrics publishing.")
        return

    logger.info(f"Publishing metrics for {step_count} steps...")
    logger.info(f"Workflow: {workflow_name}, Execution: {execution_id}")
    create_and_push_metrics(experiment, workflow_name, execution_id, execution_number)


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
