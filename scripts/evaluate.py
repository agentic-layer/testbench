import argparse
import inspect
import json
import logging
import os
from dataclasses import asdict, dataclass
from logging import Logger
from typing import Any

import ragas.metrics as metrics_module
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from ragas import evaluate
from ragas.cost import get_token_usage_for_openai
from ragas.dataset_schema import EvaluationDataset, EvaluationResult
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import Metric

# Set up module-level logger
logging.basicConfig(level=logging.INFO)
logger: Logger = logging.getLogger(__name__)


class MetricsRegistry:
    """Registry for RAGAS metrics discovery and management."""

    def __init__(self):
        """Initialize registry and discover available metrics."""
        self._instances: dict[str, Metric] = {}
        self._classes: dict[str, type[Metric]] = {}
        self._discover_metrics()

    def _discover_metrics(self) -> None:
        """
        Discover both pre-configured instances and metric classes from Ragas.

        Populates _instances and _classes dictionaries.
        """
        for name, obj in inspect.getmembers(metrics_module):
            if name.startswith("_"):
                continue

            if inspect.isclass(obj) and issubclass(obj, Metric) and obj is not Metric:
                self._classes[name] = obj
            elif isinstance(obj, Metric):
                metric_name = obj.name if hasattr(obj, "name") else name
                self._instances[metric_name] = obj

    def get_instance(self, name: str) -> Metric:
        """
        Get pre-configured metric instance by name.

        Args:
            name: Instance name

        Returns:
            Metric instance

        Raises:
            ValueError: If instance not found
        """
        if name not in self._instances:
            raise ValueError(f"Unknown instance '{name}'.\nAvailable: {', '.join(sorted(self._instances.keys()))}")
        return self._instances[name]

    def get_class(self, name: str) -> type[Metric]:
        """
        Get metric class by name.

        Args:
            name: Class name

        Returns:
            Metric class type

        Raises:
            ValueError: If class not found
        """
        if name not in self._classes:
            raise ValueError(f"Unknown class '{name}'.\nAvailable: {', '.join(sorted(self._classes.keys()))}")
        return self._classes[name]

    def instantiate_class(self, class_name: str, parameters: dict[str, Any]) -> Metric:
        """
        Instantiate metric class with custom parameters.

        Args:
            class_name: Name of metric class
            parameters: Dictionary of constructor parameters

        Returns:
            Metric instance

        Raises:
            ValueError: If class not found or instantiation fails
        """
        metric_class = self.get_class(class_name)

        try:
            return metric_class(**parameters)
        except TypeError as e:
            sig = inspect.signature(metric_class.__init__)
            raise ValueError(f"Invalid parameters for {class_name}: {e}\nExpected signature: {sig}")

    def _load_metric_from_definition(self, metric_def: dict) -> Metric:
        """
        Load a single metric from its configuration definition.

        Args:
            metric_def: Dictionary containing metric definition

        Returns:
            Metric instance

        Raises:
            ValueError: If definition is invalid or metric can't be loaded
        """
        if "type" not in metric_def:
            raise ValueError("Metric definition must include 'type' field")

        metric_type = metric_def["type"]

        if metric_type == "instance":
            if "name" not in metric_def:
                raise ValueError("Instance type requires 'name' field")
            return self.get_instance(metric_def["name"])

        elif metric_type == "class":
            if "class_name" not in metric_def:
                raise ValueError("Class type requires 'class_name' field")

            class_name = metric_def["class_name"]
            parameters = metric_def.get("parameters", {})
            return self.instantiate_class(class_name, parameters)

        else:
            raise ValueError(f"Unknown metric type '{metric_type}'.\nSupported types: 'instance', 'class'")

    def load_from_config(self, config_path: str) -> list[Metric]:
        """
        Load metrics configuration from JSON or YAML file.

        Args:
            config_path: Path to configuration file (.json or .yaml/.yml)

        Returns:
            List of configured Metric instances

        Raises:
            ValueError: If config file invalid or metrics can't be loaded
        """
        if config_path.endswith(".json"):
            with open(config_path, "r") as f:
                config = json.load(f)
        elif config_path.endswith((".yaml", ".yml")):
            try:
                import yaml
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

        if "metrics" not in config:
            raise ValueError("Config file must contain 'metrics' key")

        if not isinstance(config["metrics"], list):
            raise ValueError("'metrics' must be a list")

        metrics: list[Metric] = []
        for i, metric_def in enumerate(config["metrics"]):
            try:
                metric = self._load_metric_from_definition(metric_def)
                metrics.append(metric)
            except Exception as e:
                raise ValueError(f"Error loading metric at index {i}: {e}")

        if not metrics:
            raise ValueError("Config file contains no valid metrics")

        return metrics

    def list_instances(self) -> list[str]:
        """Return sorted list of available instance names."""
        return sorted(self._instances.keys())

    def list_classes(self) -> list[str]:
        """Return sorted list of available class names."""
        return sorted(self._classes.keys())

    @classmethod
    def create_default(cls) -> "MetricsRegistry":
        """Factory method for default registry with auto-discovery."""
        return cls()


def instantiate_metric_from_class(
    class_name: str, parameters: dict[str, Any], registry: MetricsRegistry | None = None
) -> Metric:
    """
    Instantiate a metric class with custom parameters.

    Args:
        class_name: Name of metric class
        parameters: Dictionary of constructor parameters
        registry: Optional registry (None = create default)

    Returns:
        Metric instance

    Raises:
        ValueError: If class not found or instantiation fails
    """
    if registry is None:
        registry = MetricsRegistry.create_default()

    return registry.instantiate_class(class_name, parameters)


def load_metrics_config(config_path: str, registry: MetricsRegistry | None = None) -> list[Metric]:
    """
    Load metrics configuration from JSON or YAML file.

    Args:
        config_path: Path to configuration file
        registry: Optional registry (None = create default)

    Returns:
        List of configured Metric instances

    Raises:
        ValueError: If config file invalid or metrics can't be loaded
    """
    if registry is None:
        registry = MetricsRegistry.create_default()

    return registry.load_from_config(config_path)


@dataclass
class EvaluationScores:
    """Evaluation scores and results."""

    overall_scores: dict[str, float]
    individual_results: list[dict[str, Any]]
    total_tokens: dict[str, int]
    total_cost: float


def format_evaluation_scores(
    ragas_result: EvaluationResult,
    cost_per_input_token: float,
    cost_per_output_token: float,
    experiment_file: str,
) -> EvaluationScores:
    """
    Format the RAGAS evaluation results.

    Args:
        ragas_result: The result object from RAGAS evaluate()
        cost_per_input_token: Cost per input token
        cost_per_output_token: Cost per output token
        experiment_file: Path to experiment JSONL file (to extract trace_ids)

    Returns:
        Formatted dictionary matching the required structure
    """

    # Load trace_ids from experiment file (RAGAS drops custom fields during processing)
    trace_ids = []
    with open(experiment_file, "r") as f:
        for line in f:
            data = json.loads(line)
            trace_ids.append(data.get("trace_id"))

    # Calculate overall scores (mean of each metric)
    overall_scores = ragas_result._repr_dict

    # Build individual results
    individual_results = ragas_result.to_pandas().to_dict(orient="records")

    # Merge trace_ids back into individual_results (preserve by row order)
    for i, result in enumerate(individual_results):
        if i < len(trace_ids):
            result["trace_id"] = trace_ids[i]
        else:
            logger.warning(f"No trace_id found for result {i}")
            result["trace_id"] = None

    # Extract token usage and calculate cost using TokenUsageParser
    # Check if token usage data was collected (some metrics don't use LLMs or use separate LLM instances)
    if ragas_result.cost_cb and hasattr(ragas_result.cost_cb, "usage_data") and ragas_result.cost_cb.usage_data:
        token_usage = ragas_result.total_tokens()
        # Handle both single TokenUsage and list of TokenUsage
        if isinstance(token_usage, list):
            input_tokens = sum(usage.input_tokens for usage in token_usage)
            output_tokens = sum(usage.output_tokens for usage in token_usage)
        else:
            input_tokens = token_usage.input_tokens
            output_tokens = token_usage.output_tokens

        total_tokens = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        total_cost = ragas_result.total_cost(
            cost_per_input_token=cost_per_input_token,
            cost_per_output_token=cost_per_output_token,
        )
    else:
        # No token usage data collected (e.g., non-LLM metrics or Nvidia metrics using separate LLM instances)
        logger.info("No token usage data collected for these metrics")
        total_tokens = {"input_tokens": 0, "output_tokens": 0}
        total_cost = 0.0

    return EvaluationScores(
        overall_scores=overall_scores,
        individual_results=individual_results,
        total_tokens=total_tokens,
        total_cost=total_cost,
    )


def main(
    output_file: str,
    model: str,
    metrics_config: str,
    cost_per_input_token: float = 5.0 / 1e6,
    cost_per_output_token: float = 15.0 / 1e6,
) -> None:
    """
    Main function to evaluate results using RAGAS metrics.

    Args:
        output_file: Path to save evaluation_scores.json
        model: Model name to use for evaluation
        metrics_config: Path to metrics configuration file (JSON or YAML)
        cost_per_input_token: Cost per input token
        cost_per_output_token: Cost per output token
    """
    # Load metrics from configuration file (creates registry internally)
    logger.info(f"Loading metrics from config: {metrics_config}")
    metrics = load_metrics_config(metrics_config)
    logger.info(f"Loaded {len(metrics)} metrics: {', '.join([m.name for m in metrics])}")

    # Create LLM client using the AI-Gateway
    # Setting a placeholder for the api_key since we instantiate a ChatOpenAI object,
    # but the AI-Gateway actually uses Gemini under the hood.
    # Not setting api_key here results in an OpenAIError
    ragas_llm: ChatOpenAI = ChatOpenAI(model=model, api_key=SecretStr("Placeholder->NotUsed"))
    llm = LangchainLLMWrapper(ragas_llm)  # type: ignore[arg-type]

    dataset = EvaluationDataset.from_jsonl("data/experiments/ragas_experiment.jsonl")

    # Detect and log dataset type
    if dataset.samples:
        from ragas.dataset_schema import MultiTurnSample

        is_multi_turn = isinstance(dataset.samples[0], MultiTurnSample)
        logger.info(f"Loaded {'multi-turn' if is_multi_turn else 'single-turn'} dataset")

    # Calculate metrics
    logger.info(f"Calculating metrics: {', '.join([m.name for m in metrics])}...")
    ragas_result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=llm,
        token_usage_parser=get_token_usage_for_openai,
    )

    # Ensure we have an EvaluationResult (not an Executor)
    if not isinstance(ragas_result, EvaluationResult):
        raise TypeError(f"Expected EvaluationResult, got {type(ragas_result)}")

    # Format results
    logger.info("Formatting evaluation scores...")
    evaluation_scores = format_evaluation_scores(
        ragas_result,
        cost_per_input_token=cost_per_input_token,
        cost_per_output_token=cost_per_output_token,
        experiment_file="data/experiments/ragas_experiment.jsonl",
    )

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # Save to file
    with open(output_file, "w") as f:
        json.dump(asdict(evaluation_scores), f, indent=2)

    logger.info(f"Evaluation scores saved to {output_file}")
    logger.info(f"Overall scores: {evaluation_scores.overall_scores}")


if __name__ == "__main__":
    # Create registry for help text generation
    registry = MetricsRegistry.create_default()

    # Parse the parameters (model and metrics-config) evaluate.py was called with
    parser = argparse.ArgumentParser(
        description="Evaluate results using RAGAS metrics via configuration file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Available metric instances (pre-configured):
  {", ".join(registry.list_instances())}

Available metric classes (configurable via --metrics-config):
  {", ".join(registry.list_classes())}

Examples:
  python3 scripts/evaluate.py gemini-2.5-flash-lite --metrics-config examples/metrics_simple.json
  python3 scripts/evaluate.py gemini-2.5-flash-lite --metrics-config examples/metrics_advanced.json

Config file format (JSON):
  {{
    "version": "1.0",
    "metrics": [
      {{"type": "instance", "name": "faithfulness"}},
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
        help="Path to metrics configuration file (JSON or YAML). Default: examples/metrics_simple.json",
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
    main(
        output_file="data/results/evaluation_scores.json",
        model=args.model,
        metrics_config=args.metrics_config,
        cost_per_input_token=args.cost_per_input,
        cost_per_output_token=args.cost_per_output,
    )
