import argparse
import asyncio
import json
import logging
from dataclasses import dataclass
from logging import Logger
from typing import Any

from metrics import GenericMetricsRegistry, MetricResult, dict_to_executed_step
from metrics.protocol import MetricCallable
from openai import AsyncOpenAI
from ragas import Experiment, experiment
from ragas.backends import LocalJSONLBackend
from ragas.llms import llm_factory

# Set up module-level logger
logging.basicConfig(level=logging.INFO)
logger: Logger = logging.getLogger(__name__)


def load_metrics_config(config_path: str) -> list[dict]:
    """
    Load metrics configuration from JSON or YAML file.

    Returns raw metric definitions without instantiation.
    Adds default framework='ragas' to each definition if not present.

    Args:
        config_path: Path to configuration file

    Returns:
        List of metric definition dictionaries

    Raises:
        ValueError: If config file invalid or can't be loaded
    """
    # File parsing
    if config_path.endswith(".json"):
        with open(config_path, "r") as f:
            config = json.load(f)
    elif config_path.endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            raise ValueError(
                "YAML support requires 'pyyaml' package.\n"
                "Install with: uv add pyyaml\n"
                "Or use JSON format instead: metrics.json"
            )
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
    else:
        raise ValueError(f"Unsupported config file format: {config_path}\nSupported formats: .json, .yaml, .yml")

    # Validation
    if "metrics" not in config:
        raise ValueError("Config file must contain 'metrics' key")

    if not isinstance(config["metrics"], list):
        raise ValueError("'metrics' must be a list")

    if not config["metrics"]:
        raise ValueError("Config file contains no valid metrics")

    # Add default framework to each metric definition
    for metric_def in config["metrics"]:
        if "framework" not in metric_def:
            metric_def["framework"] = "ragas"

    # Return raw definitions
    return config["metrics"]


def instantiate_metric(metric_def: dict, llm: Any, registry: GenericMetricsRegistry) -> tuple[MetricCallable, str]:
    """
    Instantiate a single metric from its definition via the generic registry.

    Args:
        metric_def: Metric definition dictionary
        llm: LLM wrapper to pass to metric
        registry: GenericMetricsRegistry for callable creation

    Returns:
        Tuple of (MetricCallable, metric_name)

    Raises:
        ValueError: If definition is invalid
    """
    if "type" not in metric_def:
        raise ValueError("Metric definition must include 'type' field")

    metric_type = metric_def["type"]

    if metric_type == "class":
        if "class_name" not in metric_def:
            raise ValueError("Class type requires 'class_name' field")

        class_name = metric_def["class_name"]
        parameters = metric_def.get("parameters", {})
        framework = metric_def.get("framework", "ragas")
        callable_ = registry.get_metric_callable(framework, class_name, parameters, llm)
        return callable_, class_name
    else:
        raise ValueError(f"Unknown metric type '{metric_type}'.\nSupported types: 'class'")


@dataclass
class EvaluationScores:
    """Evaluation scores and results."""

    overall_scores: dict[str, float]
    individual_results: list[dict[str, Any]]
    total_tokens: dict[str, int]
    total_cost: float


def format_experiment_results(
    experiment_file: str,
    metric_definitions: list[dict],
) -> EvaluationScores:
    """
    Format experiment results into the expected EvaluationScores structure.

    Reads the experiment results JSONL file produced by @experiment() and:
    1. Calculates overall scores (mean of each metric)
    2. Extracts individual results with all fields
    3. Sets token usage and cost to zero (tracking not yet implemented)

    Args:
        experiment_file: Path to experiment results JSONL file
        metric_definitions: List of metric definition dicts from config

    Returns:
        EvaluationScores with overall_scores, individual_results, total_tokens, total_cost
    """
    # Load all experiment results
    individual_results = []
    with open(experiment_file, "r") as f:
        for line in f:
            if line.strip():
                individual_results.append(json.loads(line))

    if not individual_results:
        raise ValueError(f"No results found in {experiment_file}")

    # Calculate overall scores (mean of each metric)
    # Extract metric names from definitions
    metric_names = []
    for metric_def in metric_definitions:
        if metric_def.get("type") == "class" and "class_name" in metric_def:
            metric_names.append(metric_def["class_name"])

    overall_scores = {}

    for metric_name in metric_names:
        # Collect all non-None scores for this metric
        scores = [r[metric_name] for r in individual_results if r.get(metric_name) is not None]
        if scores:
            overall_scores[metric_name] = sum(scores) / len(scores)
        else:
            logger.warning(f"No valid scores found for metric: {metric_name}")
            overall_scores[metric_name] = 0.0

    # TODO: Phase 4 - Extract token usage from experiment results if available
    # For now, set to zero as we don't yet know how @experiment() tracks tokens
    logger.info("Token usage tracking not yet implemented for @experiment() pattern")
    total_tokens = {"input_tokens": 0, "output_tokens": 0}
    total_cost = 0.0

    return EvaluationScores(
        overall_scores=overall_scores,
        individual_results=individual_results,
        total_tokens=total_tokens,
        total_cost=total_cost,
    )


@experiment()
async def evaluation_experiment(
    row: dict[str, Any],
    metric_definitions: list[dict],
    llm: Any,  # LangchainLLMWrapper - using Any to avoid mypy type alias issue
    registry: GenericMetricsRegistry,
) -> dict[str, Any]:
    """
    Evaluate a single sample using metrics via the generic registry.

    This function is decorated with @experiment() to enable automatic result tracking
    and batch processing across the dataset.

    Args:
        row: Dataset row containing user_input, response, retrieved_contexts, reference
        metric_definitions: List of metric definition dicts from config
        llm: LLM wrapper for metric calculation
        registry: GenericMetricsRegistry for callable creation

    Returns:
        Dictionary with original row data plus metric scores
    """
    result = dict(row)
    result["individual_results"] = {}

    # Convert the raw dict row to a typed ExecutedStep
    executed_step = dict_to_executed_step(row)

    # Instantiate and calculate each metric for this row
    for metric_def in metric_definitions:
        try:
            metric_callable, metric_name = instantiate_metric(metric_def, llm, registry)

            # Call the metric callable with the typed ExecutedStep
            metric_result: MetricResult = await metric_callable(executed_step)
            result["individual_results"][metric_name] = metric_result.score
        except Exception as e:
            metric_name = metric_def.get("class_name", "unknown")
            logger.warning(f"Failed to calculate {metric_name} for row: {e}")
            result[metric_name] = None

    return result


async def main(
    model: str,
    metrics_config: str,
    cost_per_input_token: float = 5.0 / 1e6,
    cost_per_output_token: float = 15.0 / 1e6,
) -> None:
    """
    Main function to evaluate results using RAGAS metrics.

    Args:
        model: Model name to use for evaluation
        metrics_config: Path to metrics configuration file (JSON or YAML)
        cost_per_input_token: Cost per input token
        cost_per_output_token: Cost per output token
    """
    # Load metric definitions from configuration file
    logger.info(f"Loading metrics from config: {metrics_config}")
    metric_definitions = load_metrics_config(metrics_config)
    logger.info(f"Loaded {len(metric_definitions)} metric definitions")

    # Create LLM client using the AI-Gateway
    # Setting a placeholder for the api_key since we instantiate a ChatOpenAI object,
    # but the AI-Gateway actually uses Gemini under the hood.
    # Not setting api_key here results in an OpenAIError
    ragas_llm: AsyncOpenAI = AsyncOpenAI(api_key="Placeholder->NotUsed")
    llm = llm_factory(model, client=ragas_llm)  # type: ignore[arg-type]

    dataset = Experiment.load(name="ragas_experiment", backend=LocalJSONLBackend(root_dir="./data"))

    # Extract metric names from definitions for logging
    metric_names = [d.get("class_name", "unknown") for d in metric_definitions]
    logger.info(f"Calculating metrics: {', '.join(metric_names)}...")

    # Create generic registry for metric instantiation
    registry = GenericMetricsRegistry.create_default()

    # Run evaluation experiment - this will process each row and save results automatically
    # Metrics are instantiated per-row inside evaluation_experiment()
    # EvaluationDataset is compatible with Dataset[Any] at runtime
    await evaluation_experiment.arun(
        dataset=dataset,  # type: ignore[arg-type]
        name="ragas_evaluation",
        metric_definitions=metric_definitions,
        llm=llm,
        registry=registry,
    )

    logger.info("Evaluation experiment completed")
    logger.info("Evaluation scores saved to './data/experiments/ragas_evaluation.jsonl'")


if __name__ == "__main__":
    # Create registry for help text generation
    registry = GenericMetricsRegistry.create_default()
    ragas_metrics = registry.list_metrics("ragas").get("ragas", [])

    # Parse the parameters (model and metrics-config) evaluate.py was called with
    parser = argparse.ArgumentParser(
        description="Evaluate results using RAGAS metrics via configuration file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""

Available metric classes (configurable via --metrics-config):
  {", ".join(ragas_metrics)}

Examples:
  python3 scripts/evaluate.py gemini-2.5-flash-lite --metrics-config examples/metrics_simple.json
  python3 scripts/evaluate.py gemini-2.5-flash-lite --metrics-config examples/metrics_advanced.json

Config file format (JSON):
  {{
    "version": "1.0",
    "metrics": [
      {{
        "type": "class",
        "class_name": "AspectCritic",
        "parameters": {{"name": "harmfulness", "definition": "Is this harmful?"}}
      }}
    ]
  }}
        """,
    )

    parser.add_argument(
        "model",
        type=str,
        help="Model name to use for evaluation (e.g., gemini-2.5-flash-lite)",
    )

    parser.add_argument(
        "--metrics-config",
        type=str,
        default="config/metrics.json",
        help="Path to metrics configuration file (JSON or YAML). Default: config/metrics.json",
    )

    parser.add_argument(
        "--cost-per-input",
        type=float,
        default=5.0 / 1e6,
        help="Cost per input token (default: 5.0/1M = $0.000005 for typical GPT-4 pricing)",
    )

    parser.add_argument(
        "--cost-per-output",
        type=float,
        default=15.0 / 1e6,
        help="Cost per output token (default: 15.0/1M = $0.000015 for typical GPT-4 pricing)",
    )

    args = parser.parse_args()

    # Run evaluation with the 'model' and 'metrics_config' provided as parameters, 'output_file' is hardcoded
    asyncio.run(
        main(
            model=args.model,
            metrics_config=args.metrics_config,
            cost_per_input_token=args.cost_per_input,
            cost_per_output_token=args.cost_per_output,
        )
    )
