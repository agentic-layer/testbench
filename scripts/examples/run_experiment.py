"""Example: execute an Experiment against an A2A agent using ExperimentRuntime.

Demonstrates how to:
1. Use ExperimentRuntime hooks to query an agent via A2A protocol
2. Maintain context_id across steps within a scenario
3. Capture trace_id per scenario via OpenTelemetry
4. Convert the runtime output into ExecutedExperiment with proper types
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging

import httpx
from opentelemetry import trace
from otel_setup import setup_otel
from schema.a2a_client import A2AStepClient
from schema.models import (
    ExecutedExperiment,
    ExecutedScenario,
    ExecutedStep,
    Experiment,
    Scenario,
    Step,
)
from schema.runtime import ExperimentRuntime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _content_hash(data: str, prefix: str = "") -> str:
    """Generate a deterministic ID from content using SHA256."""
    digest = hashlib.sha256(data.encode()).hexdigest()[:16]
    return f"{prefix}{digest}" if prefix else digest


class A2AExecutor:
    """Execute an Experiment by querying an A2A agent for each step.

    Wraps :class:`ExperimentRuntime` and manages per-scenario state
    (``context_id``, OTel spans) plus the post-run type conversion from
    ``Scenario`` → ``ExecutedScenario``.
    """

    def __init__(self, agent_url: str, workflow_name: str, input_path: str, output_path: str) -> None:
        self.agent_url = agent_url
        self.workflow_name = workflow_name
        self.input_path = input_path
        self.output_path = output_path

        # Per-scenario mutable state, reset in before_scenario
        self._context_id: str | None = None
        self._current_trace_id: str | None = None

        # Deterministic ID state
        self._current_scenario_id: str = ""
        self._step_index: int = 0

        # Reusable HTTP client and A2A step client (created once in run())
        self._http_client: httpx.AsyncClient | None = None
        self._a2a_client: A2AStepClient | None = None

        self._tracer = trace.get_tracer("testbench.run_experiment")

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    async def before_scenario(self, scenario: Scenario) -> None:
        """Reset conversation state and start an OTel span for the scenario."""
        self._context_id = None
        self._step_index = 0

        scenario_id = _content_hash(f"{self.workflow_name}:{scenario.name}", prefix="scn_")
        self._current_scenario_id = scenario_id

        # We cannot hold a span open across awaits easily, so we record
        # the trace_id from a short-lived span that acts as the scenario root.
        span = self._tracer.start_span(f"scenario: {scenario.name}")
        span_context = span.get_span_context()
        trace_id = format(span_context.trace_id, "032x")
        self._current_trace_id = trace_id

        span.set_attribute("scenario.name", scenario.name)
        span.set_attribute("scenario.id", scenario_id)
        span.set_attribute("workflow.name", self.workflow_name)
        span.set_attribute("agent.url", self.agent_url)
        span.set_attribute("scenario.step_count", len(scenario.steps))
        span.end()


        logger.info("Scenario '%s' started (id=%s, trace_id=%s)", scenario.name, scenario_id, trace_id)

    async def on_step(self, step: Step, scenario: Scenario) -> ExecutedStep:
        """Send step.input to the agent and return an ExecutedStep with turns."""
        assert self._a2a_client is not None, "A2A client not initialised"

        logger.info("  Step: %s", step.input[:80])

        result = await self._a2a_client.send_step(step.input, self._context_id)
        self._context_id = result.context_id
        turns = result.turns

        step_id = _content_hash(f"{self._current_scenario_id}:{step.input}:{self._step_index}", prefix="stp_")
        self._step_index += 1

        return ExecutedStep(
            id=step_id,
            input=step.input,
            reference=step.reference,
            custom_values=step.custom_values,
            metrics=step.metrics,
            turns=turns,
        )

    async def after_scenario(self, original: Scenario, executed: ExecutedScenario) -> None:
        """Log scenario completion and finalize collected steps."""
        executed.id = self._current_scenario_id
        executed.trace_id = self._current_trace_id
        logger.info("Scenario '%s' completed (%d steps)", original.name, len(executed.steps))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> ExecutedExperiment:
        """Execute all scenarios and return a fully-typed ExecutedExperiment."""
        runtime: ExperimentRuntime[Experiment, ExecutedExperiment] = ExperimentRuntime(
            on_step=self.on_step,
            input_path=self.input_path,
            output_path=self.output_path,
            before_scenario=self.before_scenario,
            after_scenario=self.after_scenario,
            output_model=ExecutedExperiment,
        )

        async with httpx.AsyncClient(timeout=httpx.Timeout(300)) as client:
            self._http_client = client
            self._a2a_client = A2AStepClient(self.agent_url, client)
            result = await runtime.run()
            self._a2a_client = None
            self._http_client = None

        result.id = self.workflow_name
        return result


async def main(agent_url: str, workflow_name: str, input_path: str) -> None:
    """Load an experiment, execute it, and write the result."""
    setup_otel()

    output_path = "data/experiments/executed_experiment.json"
    executor = A2AExecutor(
        agent_url=agent_url,
        workflow_name=workflow_name,
        input_path=input_path,
        output_path=output_path,
    )
    await executor.run()
    logger.info("Wrote executed experiment to %s", output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Execute an experiment against an A2A agent")
    parser.add_argument("url", help="A2A agent URL")
    parser.add_argument(
        "workflow_name",
        nargs="?",
        default="local-test",
        help="Workflow name for OTel labeling (default: local-test)",
    )
    parser.add_argument(
        "--input",
        default="data/datasets/experiment.json",
        help="Path to experiment JSON file (default: data/datasets/experiment.json)",
    )
    args = parser.parse_args()

    asyncio.run(main(args.url, args.workflow_name, args.input))
