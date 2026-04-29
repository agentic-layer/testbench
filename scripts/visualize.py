"""Generate an HTML visualization dashboard from evaluation results.

Reads an ``EvaluatedExperiment`` JSON file and produces a self-contained
HTML report with charts, tables, and statistics.

Usage::

    python3 scripts/visualize.py weather-assistant-test exec-001 1
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging import Logger
from pathlib import Path
from typing import Any, TypeGuard

from schema.models import (
    EvaluatedExperiment,
    EvaluatedScenario,
    EvaluatedStep,
    Experiment,
    Scenario,
)
from schema.runtime import ExperimentRuntime

# Set up module-level logger
logging.basicConfig(level=logging.INFO)
logger: Logger = logging.getLogger(__name__)


@dataclass
class VisualizationData:
    """Container for evaluation data to be visualized."""

    overall_scores: dict[str, float]
    individual_results: list[dict[str, Any]]
    total_tokens: dict[str, int]
    total_cost: float
    metric_names: list[str]
    default_threshold: float = 0.9
    pass_count: int = 0
    fail_count: int = 0


def _is_valid_metric_value(value: Any) -> TypeGuard[int | float]:
    """
    Check if a value is a valid metric score (numeric and not NaN).

    Args:
        value: Value to check

    Returns:
        True if value is a valid metric score
    """
    if not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return True


@dataclass
class _CollectorState:
    """Mutable state accumulated during the runtime walk."""

    individual_results: list[dict[str, Any]] = field(default_factory=list)
    all_metric_scores: dict[str, list[float]] = field(default_factory=dict)
    metric_names: set[str] = field(default_factory=set)
    current_trace_id: str = "unknown"
    default_threshold: float = 0.9
    pass_count: int = 0
    fail_count: int = 0
    current_scenario_name: str = ""
    current_scenario_index: int = 0


class ReportGenerator:
    """Generate an HTML visualization report using :class:`ExperimentRuntime`.

    Uses the runtime hook pattern to iterate scenarios/steps consistently
    with the rest of the pipeline.
    """

    def __init__(
        self,
        input_path: str,
        output_html_path: str,
        experiment_name: str,
        execution_id: str,
        execution_number: int,
    ) -> None:
        self._input_path = input_path
        self._output_html_path = output_html_path
        self._experiment_name = experiment_name
        self._execution_id = execution_id
        self._execution_number = execution_number

        self._state = _CollectorState()
        self._llm_as_a_judge_model: str | None = None

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    async def before_run(self, experiment: EvaluatedExperiment) -> None:  # type: ignore[override]
        """Reset collection state and capture experiment-level fields."""
        self._state = _CollectorState()
        if isinstance(experiment, Experiment):
            self._state.default_threshold = experiment.default_threshold
            self._llm_as_a_judge_model = experiment.llm_as_a_judge_model

    async def before_scenario(self, scenario: Scenario) -> None:
        """Track the current scenario's trace_id and name."""
        trace_id = "unknown"
        if isinstance(scenario, EvaluatedScenario) and scenario.trace_id:
            trace_id = scenario.trace_id
        self._state.current_trace_id = trace_id
        self._state.current_scenario_name = scenario.name
        self._state.current_scenario_index += 1

    async def on_step(self, step: EvaluatedStep, scenario: Scenario) -> EvaluatedStep:  # type: ignore[override]
        """Collect step data into flat result dicts."""
        flat_result: dict[str, Any] = {
            "user_input": step.input,
            "step_id": step.id or "unknown",
            "trace_id": self._state.current_trace_id,
            "scenario_name": self._state.current_scenario_name,
        }

        # Add turns if present (for multi-turn conversation rendering)
        if step.turns:
            flat_result["turns"] = [
                {
                    "content": turn.content,
                    "type": turn.type,
                    "tool_calls": [{"name": tc.name, "args": tc.args} for tc in turn.tool_calls]
                    if turn.tool_calls
                    else [],
                }
                for turn in step.turns
            ]

        # Add reference if present
        if step.reference:
            if step.reference.response:
                flat_result["reference"] = step.reference.response
            if step.reference.tool_calls:
                flat_result["reference_tool_calls"] = [
                    {"name": tc.name, "args": tc.args} for tc in step.reference.tool_calls
                ]
            if step.reference.topics:
                flat_result["reference_topics"] = step.reference.topics

        # Add custom values if present
        if step.custom_values:
            flat_result.update(step.custom_values)

        # Extract metric scores, thresholds, pass/fail, and details
        if step.evaluations:
            for evaluation in step.evaluations:
                metric_name = evaluation.metric.metric_name
                score = evaluation.result.score

                if score is not None and _is_valid_metric_value(score):
                    flat_result[metric_name] = score

                    if metric_name not in self._state.all_metric_scores:
                        self._state.all_metric_scores[metric_name] = []
                    self._state.all_metric_scores[metric_name].append(score)
                    self._state.metric_names.add(metric_name)

                # Store per-metric threshold
                if evaluation.metric.threshold is not None:
                    flat_result[f"{metric_name}__threshold"] = evaluation.metric.threshold

                # Store pass/fail result
                if evaluation.result.result is not None:
                    flat_result[f"{metric_name}__pass"] = evaluation.result.result
                    if evaluation.result.result == "pass":
                        self._state.pass_count += 1
                    else:
                        self._state.fail_count += 1

                # Store details
                if evaluation.result.details:
                    flat_result[f"{metric_name}__details"] = evaluation.result.details

        self._state.individual_results.append(flat_result)
        return step

    async def after_run(self, experiment: EvaluatedExperiment) -> None:  # type: ignore[override]
        """Build VisualizationData and generate the HTML report."""
        # Calculate overall scores as mean of each metric
        overall_scores: dict[str, float] = {}
        for metric_name, scores in self._state.all_metric_scores.items():
            if scores:
                overall_scores[metric_name] = sum(scores) / len(scores)

        metric_names = sorted(self._state.metric_names)

        viz_data = VisualizationData(
            overall_scores=overall_scores,
            individual_results=self._state.individual_results,
            total_tokens={"input_tokens": 0, "output_tokens": 0},
            total_cost=0.0,
            metric_names=metric_names,
            default_threshold=self._state.default_threshold,
            pass_count=self._state.pass_count,
            fail_count=self._state.fail_count,
        )

        logger.info("Found %d metrics: %s", len(viz_data.metric_names), ", ".join(viz_data.metric_names))
        logger.info("Processing %d samples...", len(viz_data.individual_results))

        generate_html_report(
            viz_data,
            self._output_html_path,
            self._experiment_name,
            self._execution_id,
            self._execution_number,
            llm_as_a_judge_model=self._llm_as_a_judge_model,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> EvaluatedExperiment:
        """Execute the visualization pipeline via ExperimentRuntime."""
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


# ---------------------------------------------------------------------------
# Pure functions (unchanged from original)
# ---------------------------------------------------------------------------


def calculate_metric_statistics(individual_results: list[dict[str, Any]], metric_name: str) -> dict[str, float] | None:
    """
    Calculate min, max, mean, median, std for a specific metric.

    Filters out NaN/invalid values before calculation.

    Args:
        individual_results: List of result dictionaries
        metric_name: Name of the metric to calculate statistics for

    Returns:
        Dictionary with statistics or None if no valid values
    """
    values = []
    for result in individual_results:
        value = result.get(metric_name)
        if _is_valid_metric_value(value):
            values.append(float(value))

    if not values:
        logger.warning(f"Metric '{metric_name}' has no valid values across samples")
        return None

    stats = {
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
        "median": statistics.median(values),
        "valid_count": len(values),
    }

    # Only calculate std if we have more than one value
    if len(values) > 1:
        stats["std"] = statistics.stdev(values)
    else:
        stats["std"] = 0.0

    return stats


def _format_multi_turn_conversation(conversation: list[dict[str, Any]]) -> str:
    """
    Format a multi-turn conversation as HTML with support for tool calls.

    Args:
        conversation: List of Turn dicts (from step.turns) with 'content', 'type', and optional 'tool_calls' fields

    Returns:
        Formatted HTML string
    """
    html_output = '<div class="conversation">'
    for msg in conversation:
        msg_type = msg.get("type", "unknown")
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls", [])

        # Determine CSS class based on message type
        if msg_type == "human":
            css_class = "human"
            label = "HUMAN"
        elif msg_type == "tool":
            css_class = "tool"
            label = "TOOL"
        else:  # agent (or ai for backwards compatibility)
            css_class = "agent"
            label = "AGENT"

        html_output += f'<div class="message {css_class}">'
        html_output += f"<strong>{label}:</strong> "

        # If agent message has tool calls, display them
        if tool_calls:
            html_output += '<div class="tool-calls-container">'
            for tool_call in tool_calls:
                tool_name = tool_call.get("name", "unknown")
                tool_args = tool_call.get("args", {})
                # Format args as JSON for readability
                args_str = html.escape(json.dumps(tool_args, indent=2))
                html_output += '<div class="tool-call">'
                html_output += f'<span class="tool-call-name">\u2192 Tool: {tool_name}</span>'
                html_output += f'<pre class="tool-call-args">{args_str}</pre>'
                html_output += "</div>"
            html_output += "</div>"

        # Display content if not empty
        if content:
            # Escape HTML to prevent injection and preserve formatting
            escaped_content = html.escape(content)
            html_output += f'<span class="message-content">{escaped_content}</span>'

        html_output += "</div>"

    html_output += "</div>"
    return html_output


def _is_multi_turn_conversation(result: dict[str, Any]) -> bool:
    """
    Check if result has multi-turn conversation data (from step.turns).

    Args:
        result: The result dict to check

    Returns:
        True if it has turns data (list of Turn dicts)
    """
    turns = result.get("turns")
    if not isinstance(turns, list):
        return False
    if not turns:
        return False
    return isinstance(turns[0], dict) and "content" in turns[0] and "type" in turns[0]


def prepare_chart_data(viz_data: VisualizationData) -> dict[str, Any]:
    """
    Transform VisualizationData into JSON-serializable structure for JavaScript.

    Args:
        viz_data: VisualizationData container

    Returns:
        Dictionary with all data needed for charts and tables
    """
    if not viz_data.individual_results:
        logger.warning("No individual results found. Creating minimal report.")
        return {
            "overall_scores": {},
            "metric_distributions": {},
            "samples": [],
            "tokens": viz_data.total_tokens,
            "cost": viz_data.total_cost,
        }

    # Calculate distributions and statistics for each metric
    metric_distributions = {}
    for metric_name in viz_data.metric_names:
        stats = calculate_metric_statistics(viz_data.individual_results, metric_name)
        if stats:
            # Extract values for distribution
            values = [
                float(result[metric_name])
                for result in viz_data.individual_results
                if _is_valid_metric_value(result.get(metric_name))
            ]
            metric_distributions[metric_name] = {"values": values, "stats": stats}

    # Prepare sample data for table
    samples = []
    for i, result in enumerate(viz_data.individual_results):
        trace_id = result.get("trace_id")
        if not trace_id:
            logger.warning(f"Sample {i} missing trace_id")
            trace_id = f"missing-trace-{i}"

        user_input = result.get("user_input", "")
        response = result.get("response", "")

        # Check if result has multi-turn conversation data (from step.turns)
        is_multi_turn = _is_multi_turn_conversation(result)

        sample: dict[str, Any] = {
            "index": i + 1,
            "user_input": user_input,
            "user_input_formatted": _format_multi_turn_conversation(result["turns"])
            if is_multi_turn
            else str(user_input),
            "response": response,
            "is_multi_turn": is_multi_turn,
            "turns": result.get("turns", []),  # Include turns for tooltip generation
            "metrics": {metric: result.get(metric) for metric in viz_data.metric_names if metric in result},
            "trace_id": trace_id,
            "scenario_name": result.get("scenario_name", ""),
        }

        # Propagate per-metric threshold, pass/fail, and details
        for metric in viz_data.metric_names:
            threshold_key = f"{metric}__threshold"
            pass_key = f"{metric}__pass"
            details_key = f"{metric}__details"
            if threshold_key in result:
                sample[threshold_key] = result[threshold_key]
            if pass_key in result:
                sample[pass_key] = result[pass_key]
            if details_key in result:
                sample[details_key] = result[details_key]

        # Propagate reference tool_calls and topics
        if "reference_tool_calls" in result:
            sample["reference_tool_calls"] = result["reference_tool_calls"]
        if "reference_topics" in result:
            sample["reference_topics"] = result["reference_topics"]

        samples.append(sample)

    return {
        "overall_scores": viz_data.overall_scores,
        "metric_distributions": metric_distributions,
        "samples": samples,
        "tokens": viz_data.total_tokens,
        "cost": viz_data.total_cost,
        "default_threshold": viz_data.default_threshold,
        "pass_count": viz_data.pass_count,
        "fail_count": viz_data.fail_count,
    }


def generate_css_styles() -> str:
    """Generate inline CSS styles for the HTML report."""
    return """
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    line-height: 1.6;
    color: #333;
    background-color: #f5f5f5;
    padding: 20px;
}

.header {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 40px 20px;
    text-align: center;
    border-radius: 8px;
    margin-bottom: 30px;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.header h1 {
    font-size: 2.5rem;
    margin-bottom: 10px;
}

.timestamp {
    font-size: 0.9rem;
    opacity: 0.9;
}

.metadata {
    display: flex;
    flex-direction: column;
    gap: 5px;
}

.workflow-info {
    font-size: 0.85rem;
    opacity: 0.85;
    font-family: 'Courier New', monospace;
}

.summary-section {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 20px;
    margin-bottom: 40px;
}

.card {
    background: white;
    padding: 25px;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    text-align: center;
    transition: transform 0.2s, box-shadow 0.2s;
}

.card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
}

.card h3 {
    font-size: 0.9rem;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 10px;
}

.metric-value {
    font-size: 2rem;
    font-weight: bold;
    color: #667eea;
    margin-bottom: 5px;
}

.metric-detail {
    font-size: 0.85rem;
    color: #999;
}

.chart-section, .distributions-section, .table-section {
    background: white;
    padding: 30px;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    margin-bottom: 40px;
}

.chart-section h2, .distributions-section h2, .table-section h2 {
    font-size: 1.5rem;
    margin-bottom: 20px;
    color: #333;
    border-bottom: 2px solid #667eea;
    padding-bottom: 10px;
}

.chart-container {
    position: relative;
    height: 400px;
    margin: 20px 0;
}

.distributions-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
    gap: 30px;
    margin-top: 20px;
}

.distribution-card {
    background: #f9f9f9;
    padding: 20px;
    border-radius: 8px;
    border: 1px solid #e0e0e0;
}

.distribution-card h3 {
    font-size: 1.1rem;
    margin-bottom: 15px;
    color: #667eea;
    text-align: center;
}

.distribution-card canvas {
    margin-bottom: 15px;
}

.stats {
    display: flex;
    justify-content: space-around;
    font-size: 0.85rem;
    color: #666;
    padding-top: 15px;
    border-top: 1px solid #e0e0e0;
    flex-wrap: wrap;
    gap: 10px;
}

.stats span {
    display: flex;
    flex-direction: column;
    align-items: center;
}

.table-controls {
    display: flex;
    gap: 15px;
    margin-bottom: 20px;
    flex-wrap: wrap;
}

.table-controls input,
.table-controls select {
    padding: 10px;
    border: 1px solid #ddd;
    border-radius: 4px;
    font-size: 0.9rem;
}

.table-controls input {
    flex: 1;
    min-width: 200px;
}

.table-container {
    overflow-x: auto;
    max-height: 600px;
    overflow-y: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
}

thead {
    position: sticky;
    top: 0;
    background: #667eea;
    color: white;
    z-index: 10;
}

thead th {
    padding: 12px;
    text-align: left;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

tbody tr {
    border-bottom: 1px solid #eee;
    transition: background-color 0.2s;
}

tbody tr:hover {
    background-color: #f5f5f5;
}

tbody td {
    padding: 12px;
    vertical-align: top;
}

tbody td:first-child {
    font-weight: bold;
    color: #999;
}

.user-input-cell, .response-cell {
    max-width: 400px;
}

/* For single-turn inputs, truncate with ellipsis */
.user-input-cell:not(:has(.conversation)),
.response-cell {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* For multi-turn conversations, allow wrapping */
.user-input-cell:has(.conversation) {
    white-space: normal;
    vertical-align: top;
}

.metric-score {
    font-weight: bold;
    padding: 4px 8px;
    border-radius: 4px;
    display: inline-block;
}

.metric-score.high {
    background-color: #d4edda;
    color: #155724;
}

.metric-score.medium {
    background-color: #fff3cd;
    color: #856404;
}

.metric-score.low {
    background-color: #f8d7da;
    color: #721c24;
}

.trace-id {
    font-family: 'Courier New', monospace;
    font-size: 0.8rem;
    color: #666;
}

/* Multi-turn conversation styling */
.conversation {
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-width: 100%;
}

.conversation .message {
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 0.85rem;
    line-height: 1.4;
    max-width: 90%;
}

.conversation .message.human {
    background-color: #e3f2fd;
    border-left: 3px solid #2196f3;
    align-self: flex-start;
}

.conversation .message.agent {
    background-color: #f3e5f5;
    border-left: 3px solid #9c27b0;
    align-self: flex-end;
}

.conversation .message.tool {
    background-color: #fff3cd;
    border-left: 3px solid #ffc107;
    align-self: center;
    max-width: 95%;
}

.tool-calls-container {
    margin-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.tool-call {
    background-color: rgba(255, 255, 255, 0.5);
    padding: 8px;
    border-radius: 4px;
    border: 1px solid rgba(0, 0, 0, 0.1);
}

.tool-call-name {
    display: block;
    font-weight: bold;
    color: #5d4037;
    margin-bottom: 4px;
    font-size: 0.8rem;
}

.tool-call-args {
    background-color: #f5f5f5;
    padding: 6px;
    border-radius: 3px;
    font-family: 'Courier New', monospace;
    font-size: 0.75rem;
    margin: 0;
    overflow-x: auto;
    border: 1px solid #e0e0e0;
}

.message-content {
    display: block;
    margin-top: 4px;
}

.conversation .message strong {
    display: block;
    font-size: 0.75rem;
    text-transform: uppercase;
    color: #666;
    margin-bottom: 4px;
}

.badge {
    display: inline-block;
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 0.7rem;
    font-weight: bold;
    text-transform: uppercase;
    margin-left: 4px;
    vertical-align: middle;
}

.badge.pass {
    background-color: #d4edda;
    color: #155724;
}

.badge.fail {
    background-color: #f8d7da;
    color: #721c24;
}

.scenario-header td {
    background-color: #e8eaf6;
    font-weight: bold;
    font-size: 0.95rem;
    color: #3949ab;
    padding: 10px 12px;
    border-bottom: 2px solid #7986cb;
}

.reference-details {
    margin-top: 8px;
    font-size: 0.8rem;
    color: #555;
}

.reference-details summary {
    cursor: pointer;
    color: #667eea;
    font-weight: 600;
}

.reference-details pre {
    background-color: #f5f5f5;
    padding: 6px;
    border-radius: 3px;
    font-size: 0.75rem;
    overflow-x: auto;
    border: 1px solid #e0e0e0;
}

.eval-details {
    margin-top: 4px;
    font-size: 0.75rem;
}

.eval-details summary {
    cursor: pointer;
    color: #667eea;
}

.eval-details pre {
    background-color: #f5f5f5;
    padding: 6px;
    border-radius: 3px;
    font-size: 0.7rem;
    overflow-x: auto;
    border: 1px solid #e0e0e0;
    margin-top: 4px;
}

.footer {
    text-align: center;
    padding: 20px;
    color: #999;
    font-size: 0.85rem;
}

@media (max-width: 768px) {
    .header h1 {
        font-size: 1.8rem;
    }

    .summary-section {
        grid-template-columns: 1fr;
    }

    .distributions-grid {
        grid-template-columns: 1fr;
    }

    .table-controls {
        flex-direction: column;
    }
}

@media print {
    body {
        background: white;
        padding: 0;
    }

    .card, .chart-section, .distributions-section, .table-section {
        box-shadow: none;
        page-break-inside: avoid;
    }

    .table-container {
        max-height: none;
        overflow: visible;
    }
}
"""


def generate_summary_cards_html(chart_data: dict[str, Any]) -> str:
    """Generate HTML for summary statistics cards."""
    tokens = chart_data["tokens"]
    total_tokens = tokens.get("input_tokens", 0) + tokens.get("output_tokens", 0)
    cost = chart_data["cost"]

    cards_html = f"""
<section class="summary-section">
    <div class="card">
        <h3>Total Samples</h3>
        <p class="metric-value">{len(chart_data["samples"])}</p>
    </div>
    <div class="card">
        <h3>Metrics Evaluated</h3>
        <p class="metric-value">{len(chart_data["overall_scores"])}</p>
    </div>
"""

    # Only show tokens card if they have values
    if total_tokens > 0:
        cards_html += f"""    <div class="card">
        <h3>Total Tokens</h3>
        <p class="metric-value">{total_tokens:,}</p>
        <p class="metric-detail">Input: {tokens.get("input_tokens", 0):,} | Output: {tokens.get("output_tokens", 0):,}</p>
    </div>
"""

    # Only show cost card if it has a value
    if cost > 0:
        cards_html += f"""    <div class="card">
        <h3>Total Cost</h3>
        <p class="metric-value">${cost:.4f}</p>
    </div>
"""

    # Pass rate card (only when pass/fail data is available)
    pass_count = chart_data.get("pass_count", 0)
    fail_count = chart_data.get("fail_count", 0)
    total_evaluated = pass_count + fail_count
    if total_evaluated > 0:
        pass_rate = pass_count / total_evaluated * 100
        cards_html += f"""    <div class="card">
        <h3>Pass Rate</h3>
        <p class="metric-value">{pass_rate:.1f}%</p>
        <p class="metric-detail">{pass_count} passed | {fail_count} failed</p>
    </div>
"""

    cards_html += """</section>
"""
    return cards_html


def generate_overall_scores_chart_html() -> str:
    """Generate container for overall scores bar chart."""
    return """
<section class="chart-section">
    <h2>Overall Metric Scores</h2>
    <div class="chart-container">
        <canvas id="overallScoresChart"></canvas>
    </div>
</section>
"""


def generate_metric_distributions_html(chart_data: dict[str, Any]) -> str:
    """Generate containers for metric distribution histograms."""
    if not chart_data["metric_distributions"]:
        return ""

    html_str = """
<section class="distributions-section">
    <h2>Metric Distributions</h2>
    <div class="distributions-grid">
"""

    for metric_name, dist_data in chart_data["metric_distributions"].items():
        stats = dist_data["stats"]
        html_str += f"""
        <div class="distribution-card">
            <h3>{metric_name}</h3>
            <canvas id="chart-{metric_name}"></canvas>
            <div class="stats">
                <span><strong>Min:</strong> {stats["min"]:.3f}</span>
                <span><strong>Max:</strong> {stats["max"]:.3f}</span>
                <span><strong>Mean:</strong> {stats["mean"]:.3f}</span>
                <span><strong>Median:</strong> {stats["median"]:.3f}</span>
            </div>
        </div>
"""

    html_str += """
    </div>
</section>
"""
    return html_str


def _get_score_class(score: float, threshold: float | None = None) -> str:
    """Get CSS class for score color coding.

    When *threshold* is provided the boundaries are derived from it:
    ``>= threshold`` → high, ``>= threshold * 0.75`` → medium, else low.
    Without a threshold the legacy hard-coded 0.8 / 0.5 bands are used.
    """
    if threshold is not None:
        if score >= threshold:
            return "high"
        elif score >= threshold * 0.75:
            return "medium"
        else:
            return "low"
    # Legacy fallback
    if score >= 0.8:
        return "high"
    elif score >= 0.5:
        return "medium"
    else:
        return "low"


def generate_samples_table_html(chart_data: dict[str, Any]) -> str:
    """Generate detailed HTML table with all samples and scores."""
    if not chart_data["samples"]:
        return "<p>No samples to display.</p>"

    # Get all metric names from first sample
    metric_names = []
    if chart_data["samples"] and chart_data["samples"][0]["metrics"]:
        metric_names = sorted(chart_data["samples"][0]["metrics"].keys())

    # Check if any sample has response data
    has_responses = any(sample.get("response") for sample in chart_data["samples"])

    # Generate table header
    html_str = """
<section class="table-section">
    <h2>Detailed Results</h2>
    <div class="table-controls">
        <input type="text" id="searchInput" placeholder="Search...">
    </div>
    <div class="table-container">
        <table id="resultsTable">
            <thead>
                <tr>
                    <th>#</th>
                    <th>User Input</th>
"""

    # Add Response column header only if there's response data
    if has_responses:
        html_str += "                    <th>Response</th>\n"

    # Add metric columns
    for metric_name in metric_names:
        html_str += f"                    <th>{metric_name}</th>\n"

    html_str += """                    <th>Trace ID</th>
                </tr>
            </thead>
            <tbody>
"""

    # Resolve default threshold for score coloring
    default_threshold = chart_data.get("default_threshold", 0.9)

    # Generate table rows with scenario grouping
    last_scenario_name = None
    for sample in chart_data["samples"]:
        # Emit scenario group header on boundary change
        scenario_name = sample.get("scenario_name", "")
        if scenario_name and scenario_name != last_scenario_name:
            col_count = 3 + len(metric_names) + (1 if has_responses else 0)
            html_str += (
                f'                <tr class="scenario-header">'
                f'<td colspan="{col_count}">{html.escape(scenario_name)}</td></tr>\n'
            )
            last_scenario_name = scenario_name

        # Use formatted HTML for multi-turn conversations
        user_input_display = sample.get("user_input_formatted", sample["user_input"])

        # For tooltips and search, we need plain text version
        if sample.get("is_multi_turn"):
            # Get turns from sample (already included)
            turns = sample.get("turns", [])
            tooltip_parts = []
            for msg in turns:
                msg_type = msg.get("type", "unknown")
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls", [])

                if tool_calls:
                    # For agent messages with tool calls, show tool names
                    tool_names = ", ".join([tc.get("name", "unknown") for tc in tool_calls])
                    tooltip_parts.append(f"{msg_type}: [calls: {tool_names}]")
                elif content:
                    # For messages with content, show truncated content
                    truncated = content[:50] + "..." if len(content) > 50 else content
                    tooltip_parts.append(f"{msg_type}: {truncated}")
                else:
                    # Empty message (shouldn't happen, but handle gracefully)
                    tooltip_parts.append(f"{msg_type}: (empty)")

            tooltip_text = " | ".join(tooltip_parts)
        else:
            tooltip_text = str(sample["user_input"])

        # Build reference details section
        ref_details_html = ""
        ref_response = sample.get("response", "")
        ref_tool_calls = sample.get("reference_tool_calls")
        ref_topics = sample.get("reference_topics")
        if ref_tool_calls or ref_topics:
            ref_details_html = '<details class="reference-details"><summary>Reference details</summary>'
            if ref_response:
                ref_details_html += f"<p><strong>Response:</strong> {html.escape(str(ref_response))}</p>"
            if ref_tool_calls:
                tc_json = html.escape(json.dumps(ref_tool_calls, indent=2))
                ref_details_html += f"<p><strong>Expected tool calls:</strong></p><pre>{tc_json}</pre>"
            if ref_topics:
                ref_details_html += f"<p><strong>Expected topics:</strong> {html.escape(', '.join(ref_topics))}</p>"
            ref_details_html += "</details>"

        html_str += f"""                <tr>
                    <td>{sample["index"]}</td>
                    <td class="user-input-cell" title="{tooltip_text}">{user_input_display}{ref_details_html}</td>
"""

        # Add response cell only if we have response data
        if has_responses:
            response = sample.get("response", "")
            html_str += f'                    <td class="response-cell" title="{response}">{response}</td>\n'

        # Add metric values with threshold-aware coloring and pass/fail badges
        for metric_name in metric_names:
            score = sample["metrics"].get(metric_name)
            if _is_valid_metric_value(score):
                # Resolve threshold: per-metric → default
                metric_threshold = sample.get(f"{metric_name}__threshold", default_threshold)
                score_class = _get_score_class(float(score), threshold=metric_threshold)
                cell_html = f'<span class="metric-score {score_class}">{score:.3f}</span>'

                # Pass/fail badge
                pass_result = sample.get(f"{metric_name}__pass")
                if pass_result is not None:
                    badge_class = "pass" if pass_result == "pass" else "fail"  # nosec B105
                    badge_label = "PASS" if pass_result == "pass" else "FAIL"  # nosec B105
                    cell_html += f' <span class="badge {badge_class}">{badge_label}</span>'

                # Details collapsible
                details = sample.get(f"{metric_name}__details")
                if details:
                    details_json = html.escape(json.dumps(details, indent=2))
                    cell_html += (
                        f'<details class="eval-details"><summary>details</summary><pre>{details_json}</pre></details>'
                    )

                html_str += f"                    <td>{cell_html}</td>\n"
            else:
                html_str += "                    <td>N/A</td>\n"

        html_str += f"""                    <td class="trace-id">{sample["trace_id"]}</td>
                </tr>
"""

    html_str += """            </tbody>
        </table>
    </div>
</section>
"""
    return html_str


def generate_javascript(chart_data: dict[str, Any]) -> str:
    """
    Generate JavaScript code including Chart.js chart definitions and table interactivity.

    Args:
        chart_data: Prepared chart data dictionary

    Returns:
        Complete JavaScript code as string
    """
    # Embed data as JSON
    chart_data_json = json.dumps(chart_data, indent=2)

    js_code = f"""
const reportData = {chart_data_json};

// Overall Scores Bar Chart
if (reportData.overall_scores && Object.keys(reportData.overall_scores).length > 0) {{
    const ctx = document.getElementById('overallScoresChart');
    if (ctx) {{
        new Chart(ctx, {{
            type: 'bar',
            data: {{
                labels: Object.keys(reportData.overall_scores),
                datasets: [{{
                    label: 'Score',
                    data: Object.values(reportData.overall_scores),
                    backgroundColor: 'rgba(54, 162, 235, 0.6)',
                    borderColor: 'rgba(54, 162, 235, 1)',
                    borderWidth: 1
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    x: {{
                        beginAtZero: true,
                        max: 1.0,
                        title: {{ display: true, text: 'Score' }}
                    }}
                }},
                plugins: {{
                    legend: {{ display: false }},
                    title: {{
                        display: true,
                        text: 'Mean Scores Across All Samples'
                    }}
                }}
            }}
        }});
    }}
}}

// Metric Distribution Histograms
if (reportData.metric_distributions) {{
    Object.keys(reportData.metric_distributions).forEach(metricName => {{
        const distribution = reportData.metric_distributions[metricName];
        const values = distribution.values;

        // Create histogram bins
        const binCount = Math.min(10, Math.ceil(Math.sqrt(values.length)));
        const min = Math.min(...values);
        const max = Math.max(...values);
        const binWidth = (max - min) / binCount;

        const bins = Array(binCount).fill(0);
        const labels = [];

        for (let i = 0; i < binCount; i++) {{
            const binStart = min + i * binWidth;
            const binEnd = min + (i + 1) * binWidth;
            labels.push(`${{binStart.toFixed(2)}}-${{binEnd.toFixed(2)}}`);
        }}

        values.forEach(value => {{
            let binIndex = Math.floor((value - min) / binWidth);
            if (binIndex >= binCount) binIndex = binCount - 1;
            if (binIndex < 0) binIndex = 0;
            bins[binIndex]++;
        }});

        const ctx = document.getElementById(`chart-${{metricName}}`);
        if (ctx) {{
            new Chart(ctx, {{
                type: 'bar',
                data: {{
                    labels: labels,
                    datasets: [{{
                        label: 'Frequency',
                        data: bins,
                        backgroundColor: 'rgba(75, 192, 192, 0.6)',
                        borderColor: 'rgba(75, 192, 192, 1)',
                        borderWidth: 1
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: true,
                    scales: {{
                        y: {{
                            beginAtZero: true,
                            title: {{ display: true, text: 'Count' }}
                        }},
                        x: {{
                            title: {{ display: true, text: 'Score Range' }}
                        }}
                    }},
                    plugins: {{
                        legend: {{ display: false }}
                    }}
                }}
            }});
        }}
    }});
}}

// Table Search Functionality
const searchInput = document.getElementById('searchInput');
if (searchInput) {{
    searchInput.addEventListener('keyup', function() {{
        const searchTerm = this.value.toLowerCase();
        const table = document.getElementById('resultsTable');
        const rows = table.getElementsByTagName('tr');

        for (let i = 1; i < rows.length; i++) {{
            const row = rows[i];
            const text = row.textContent.toLowerCase();

            if (text.includes(searchTerm)) {{
                row.style.display = '';
            }} else {{
                row.style.display = 'none';
            }}
        }}
    }});
}}
"""

    return js_code


def generate_html_report(
    viz_data: VisualizationData,
    output_file: str,
    experiment_name: str,
    execution_id: str,
    execution_number: int,
    *,
    llm_as_a_judge_model: str | None = None,
) -> None:
    """
    Generate complete self-contained HTML file.

    Args:
        viz_data: VisualizationData container
        output_file: Path to output HTML file
        experiment_name: Name of the experiment
        execution_id: Testkube execution ID for this workflow run
        execution_number: Testkube execution number for this workflow run
        llm_as_a_judge_model: Optional LLM model name used for evaluation
    """
    # Ensure output directory exists
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Prepare chart data
    chart_data = prepare_chart_data(viz_data)

    # Generate title from workflow metadata
    title = f"{experiment_name} - Execution {execution_number} ({execution_id})"

    # Generate timestamp
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Optional model info line
    model_info = ""
    if llm_as_a_judge_model:
        model_info = (
            f'            <p class="workflow-info">LLM-as-a-Judge Model: {html.escape(llm_as_a_judge_model)}</p>'
        )

    # Build complete HTML
    html_str = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
{generate_css_styles()}
    </style>
</head>
<body>
    <header class="header">
        <h1>{title}</h1>
        <div class="metadata">
            <p class="timestamp">Generated: {timestamp}</p>
            <p class="workflow-info">Experiment: {experiment_name} | Execution: {execution_number} | ID: {execution_id}</p>
{model_info}
        </div>
    </header>

{generate_summary_cards_html(chart_data)}

{generate_overall_scores_chart_html()}

{generate_metric_distributions_html(chart_data)}

{generate_samples_table_html(chart_data)}

    <footer class="footer">
        <p>Generated by Testbench</p>
    </footer>

    <script>
{generate_javascript(chart_data)}
    </script>
</body>
</html>
"""

    # Write to file
    with open(output_file, "w") as f:
        f.write(html_str)

    logger.info(f"Report saved to: {output_file}")


def main(
    input_file: str,
    output_file: str,
    experiment_name: str,
    execution_id: str,
    execution_number: int,
) -> None:
    """
    Main function to generate HTML visualization.

    Args:
        input_file: Path to evaluated_experiment.json
        output_file: Path to output HTML file
        experiment_name: Name of the experiment
        execution_id: Testkube execution ID for this workflow run
        execution_number: Testkube execution number for this workflow run
    """
    logger.info("Loading evaluation data from %s...", input_file)
    logger.info("Experiment: %s, Execution: %s", experiment_name, execution_id)

    generator = ReportGenerator(
        input_path=input_file,
        output_html_path=output_file,
        experiment_name=experiment_name,
        execution_id=execution_id,
        execution_number=execution_number,
    )
    asyncio.run(generator.run())

    logger.info("HTML report generated successfully: %s", output_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate HTML dashboard from testbench evaluation results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python3 scripts/visualize.py weather-assistant-test exec-123 1

  # Custom input/output paths
  python3 scripts/visualize.py weather-assistant-test exec-123 1 \\
    --input data/results/custom.json \\
    --output reports/exec-123.html

  # After running evaluate.py in pipeline
  python3 scripts/evaluate.py gemini-2.5-flash-lite --metrics-config examples/metrics_simple.json
  python3 scripts/visualize.py weather-agent exec-001 1
        """,
    )

    # Positional required arguments (matching publish.py)
    parser.add_argument(
        "experiment_name",
        help="Name of the experiment (e.g., 'weather-assistant-test')",
    )
    parser.add_argument(
        "execution_id",
        help="Testkube execution ID for this workflow run",
    )
    parser.add_argument(
        "execution_number",
        type=int,
        help="Testkube execution number for this workflow run",
    )

    # Optional arguments
    parser.add_argument(
        "--input",
        type=str,
        default="data/experiments/evaluated_experiment.json",
        help="Path to evaluated_experiment.json file (default: data/experiments/evaluated_experiment.json)",
    )

    parser.add_argument(
        "--output",
        type=str,
        default="data/results/evaluation_report.html",
        help="Path for output HTML file (default: data/results/evaluation_report.html)",
    )

    args = parser.parse_args()
    main(
        args.input,
        args.output,
        args.experiment_name,
        args.execution_id,
        args.execution_number,
    )
