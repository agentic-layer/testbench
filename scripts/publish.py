import argparse
import hashlib
import json
import logging
import math
import os
from dataclasses import dataclass
from logging import Logger
from typing import Any, TypeGuard

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

# Set up module-level logger
logging.basicConfig(level=logging.INFO)
logger: Logger = logging.getLogger(__name__)


@dataclass
class EvaluationData:
    """Container for all evaluation data to be published as metrics."""

    individual_results: list[dict[str, Any]]
    total_tokens: dict[str, int]
    total_cost: float


def load_evaluation_data(file_path: str) -> EvaluationData:
    """Load the evaluation_scores.json file and return the relevant data for metrics."""
    with open(file_path, "r") as file:
        data = json.load(file)
        return EvaluationData(
            individual_results=data.get("individual_results", []),
            total_tokens=data.get("total_tokens", {"input_tokens": 0, "output_tokens": 0}),
            total_cost=data.get("total_cost", 0.0),
        )


def _is_metric_value(value: Any) -> TypeGuard[int | float]:
    """Check if a value is a valid metric score (numeric and not NaN)."""
    if not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return True


def _get_user_input_hash(user_input: str) -> str:
    """Generate a short hash of the user input for stable identification."""
    return hashlib.sha256(user_input.encode()).hexdigest()[:12]


def _get_user_input_truncated(user_input: str, max_length: int = 50) -> str:
    """Truncate user input text for display in metric labels."""
    if len(user_input) <= max_length:
        return user_input
    return user_input[:max_length] + "..."


def create_and_push_metrics(
    evaluation_data: EvaluationData, workflow_name: str, execution_id: str, execution_number: int
) -> None:
    """
    Create OpenTelemetry metrics for evaluation results and push via OTLP.

    Creates per-sample gauges for each metric, plus token usage and cost gauges.

    The OTLP endpoint is read from the OTEL_EXPORTER_OTLP_ENDPOINT environment variable,
    with a default of 'http://localhost:4318' if not set.

    Args:
        evaluation_data: Container with individual results, token counts, and cost
        workflow_name: Name of the test workflow (used as label to distinguish workflows)
        execution_id: Testkube execution ID for this workflow run
        execution_number: Number of the execution for the current workflow
    """
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    if not otlp_endpoint.startswith("http://") and not otlp_endpoint.startswith("https://"):
        otlp_endpoint = f"http://{otlp_endpoint}"

    exporter = OTLPMetricExporter(endpoint=f"{otlp_endpoint}/v1/metrics")
    reader = PeriodicExportingMetricReader(exporter=exporter, export_interval_millis=1000)
    resource = Resource.create({"service.name": "ragas-evaluation", "workflow.name": workflow_name})
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    meter = metrics.get_meter("ragas.evaluation", "1.0.0")

    try:
        logger.info(f"Pushing metrics to OTLP endpoint at {otlp_endpoint}...")

        # Collect metric names from individual results (any numeric field is a metric)
        metric_names: set[str] = set()
        for result in evaluation_data.individual_results:
            for key, value in result.items():
                if _is_metric_value(value):
                    metric_names.add(key)

        # Single gauge for all evaluation metrics, differentiated by 'name' attribute
        metric_gauge = meter.create_gauge(
            name="testbench_evaluation_metric",
            description="Evaluation metric from RAGAS testbench",
            unit="",
        )

        # Set per-sample values for each metric
        for metric_name in sorted(metric_names):
            for result in evaluation_data.individual_results:
                score = result.get(metric_name)
                if not _is_metric_value(score):
                    logger.debug(f"Skipping invalid metric value for {metric_name}: {score}")
                    continue
                trace_id = result.get("trace_id")
                if not trace_id:
                    logger.warning(f"Missing trace_id for sample in execution {execution_id}")
                    trace_id = "missing-trace-id"
                user_input = result.get("user_input", "(user_input missing or invalid)")
                attributes = {
                    "name": metric_name,
                    "workflow_name": workflow_name,
                    "execution_id": execution_id,
                    "execution_number": execution_number,
                    "trace_id": trace_id,
                    "user_input_hash": _get_user_input_hash(user_input),
                    "user_input_truncated": _get_user_input_truncated(user_input),
                }
                metric_gauge.set(score, attributes)
                logger.info(f"testbench_evaluation_metric{attributes} = {score}")

        # Token usage gauge with 'type' attribute
        token_gauge = meter.create_gauge(
            name="testbench_evaluation_token_usage",
            description="Token usage from RAGAS evaluation",
            unit="",
        )

        input_tokens = evaluation_data.total_tokens.get("input_tokens", 0)
        token_gauge.set(
            input_tokens,
            {
                "type": "input_tokens",
                "workflow_name": workflow_name,
                "execution_id": execution_id,
                "execution_number": execution_number,
            },
        )
        logger.info(
            f"testbench_evaluation_token_usage{{type=input_tokens, workflow_name={workflow_name}, execution_id={execution_id}, execution_number={execution_number}}} = {input_tokens}"
        )

        output_tokens = evaluation_data.total_tokens.get("output_tokens", 0)
        token_gauge.set(
            output_tokens,
            {
                "type": "output_tokens",
                "workflow_name": workflow_name,
                "execution_id": execution_id,
                "execution_number": execution_number,
            },
        )
        logger.info(
            f"testbench_evaluation_token_usage{{type=output_tokens, workflow_name={workflow_name}, execution_id={execution_id}, execution_number={execution_number}}} = {output_tokens}"
        )

        # Total cost gauge
        cost_gauge = meter.create_gauge(
            name="testbench_evaluation_cost",
            description="Total cost of RAGAS evaluation in USD",
            unit="",
        )
        cost_gauge.set(
            evaluation_data.total_cost,
            {"workflow_name": workflow_name, "execution_id": execution_id, "execution_number": execution_number},
        )
        logger.info(
            f"testbench_evaluation_cost{{workflow_name={workflow_name}, execution_id={execution_id}, execution_number={execution_number}}} = {evaluation_data.total_cost}"
        )

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
    """
    Publish evaluation metrics via OpenTelemetry OTLP.

    The OTLP endpoint is read from the OTEL_EXPORTER_OTLP_ENDPOINT environment variable,
    with a default of 'http://localhost:4318' if not set.

    Args:
        input_file: Path to the evaluation scores JSON file
        workflow_name: Name of the test workflow (e.g., 'weather-assistant-test').
        execution_id: Testkube execution ID for this workflow run.
        execution_number: Number of the execution for the current workflow (e.g. 3)
    """
    logger.info(f"Loading evaluation data from {input_file}...")
    evaluation_data = load_evaluation_data(input_file)

    if not evaluation_data.individual_results:
        logger.warning("No individual results found in evaluation_scores.json")
        return

    logger.info(f"Publishing metrics for {len(evaluation_data.individual_results)} samples...")
    logger.info(f"Workflow: {workflow_name}, Execution: {execution_id}")
    create_and_push_metrics(evaluation_data, workflow_name, execution_id, execution_number)


if __name__ == "__main__":
    """
    Main function to publish metrics via OpenTelemetry OTLP.

    The OTLP endpoint is read from the OTEL_EXPORTER_OTLP_ENDPOINT environment variable,
    with a default of 'http://localhost:4318' if not set.

    Args:
        workflow_name: Name of the test workflow
        execution_id: Testkube execution ID for this workflow run
        execution_number: Testkube execution number for this workflow run

    Examples:
            python3 scripts/publish.py weather-assistant-test exec-123 1
            OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 python3 scripts/publish.py weather-assistant-test exec-123 1
    """

    parser = argparse.ArgumentParser(description="Publish RAGAS evaluation metrics via OpenTelemetry OTLP")
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
        help="Testkube execution number for this workflow run (for use as a *numeric* identifier in Grafana)",
    )

    args = parser.parse_args()

    publish_metrics(
        input_file="data/results/evaluation_scores.json",
        workflow_name=args.workflow_name,
        execution_id=args.execution_id,
        execution_number=args.execution_number,
    )
