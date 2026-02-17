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
import json
import logging
from pathlib import Path
from uuid import uuid4

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


class A2AExecutor:
    """Execute an Experiment by querying an A2A agent for each step.

    Wraps :class:`ExperimentRuntime` and manages per-scenario state
    (``context_id``, OTel spans) plus the post-run type conversion from
    ``Scenario`` → ``ExecutedScenario``.
    """

    def __init__(self, agent_url: str, workflow_name: str) -> None:
        self.agent_url = agent_url
        self.workflow_name = workflow_name

        # Per-scenario mutable state, reset in before_scenario
        self._context_id: str | None = None
        self._scenario_meta: list[dict[str, str]] = []
        self._scenario_steps: list[list[ExecutedStep]] = []
        self._current_steps: list[ExecutedStep] = []

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
        self._current_steps = []

        scenario_id = uuid4().hex

        # We cannot hold a span open across awaits easily, so we record
        # the trace_id from a short-lived span that acts as the scenario root.
        span = self._tracer.start_span(f"scenario: {scenario.name}")
        span_context = span.get_span_context()
        trace_id = format(span_context.trace_id, "032x")

        span.set_attribute("scenario.name", scenario.name)
        span.set_attribute("scenario.id", scenario_id)
        span.set_attribute("workflow.name", self.workflow_name)
        span.set_attribute("agent.url", self.agent_url)
        span.set_attribute("scenario.step_count", len(scenario.steps))
        span.end()

        self._scenario_meta.append({"id": scenario_id, "trace_id": trace_id})

        logger.info("Scenario '%s' started (id=%s, trace_id=%s)", scenario.name, scenario_id, trace_id)

    async def on_step(self, step: Step, scenario: Scenario) -> ExecutedStep:
        """Send step.input to the agent and return an ExecutedStep with turns."""
        assert self._a2a_client is not None, "A2A client not initialised"

        logger.info("  Step: %s", step.input[:80])

        result = await self._a2a_client.send_step(step.input, self._context_id)
        self._context_id = result.context_id
        turns = result.turns

        executed_step = ExecutedStep(
            id=uuid4().hex,
            input=step.input,
            reference=step.reference,
            custom_values=step.custom_values,
            metrics=step.metrics,
            turns=turns,
        )
        self._current_steps.append(executed_step)
        return executed_step

    async def after_scenario(self, original: Scenario, executed: Scenario) -> None:
        """Log scenario completion and finalize collected steps."""
        self._scenario_steps.append(list(self._current_steps))
        logger.info("Scenario '%s' completed (%d steps)", original.name, len(executed.steps))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, experiment: Experiment) -> ExecutedExperiment:
        """Execute all scenarios and return a fully-typed ExecutedExperiment."""
        self._scenario_meta = []
        self._scenario_steps = []
        self._current_steps = []

        runtime = ExperimentRuntime(
            on_step=self.on_step,
            before_scenario=self.before_scenario,
            after_scenario=self.after_scenario,
        )

        async with httpx.AsyncClient(timeout=httpx.Timeout(300)) as client:
            self._http_client = client
            self._a2a_client = A2AStepClient(self.agent_url, client)
            result = await runtime.run(experiment)
            self._a2a_client = None
            self._http_client = None

        # Convert Scenario → ExecutedScenario with accumulated metadata.
        # model_copy preserves the Scenario type, so steps get coerced back to
        # Step dicts (losing ExecutedStep fields).  We use the separately
        # collected _scenario_steps which hold the real ExecutedStep objects.
        executed_scenarios: list[ExecutedScenario] = []
        for scenario, meta, steps in zip(result.scenarios, self._scenario_meta, self._scenario_steps):
            executed_scenarios.append(
                ExecutedScenario(
                    name=scenario.name,
                    reference=scenario.reference,
                    evaluations=scenario.evaluations,
                    steps=steps,
                    id=meta["id"],
                    trace_id=meta["trace_id"],
                )
            )

        return ExecutedExperiment(
            **experiment.model_dump(exclude={"scenarios"}),
            id=uuid4().hex,
            scenarios=executed_scenarios,
        )


async def main(agent_url: str, workflow_name: str, input_path: str) -> None:
    """Load an experiment, execute it, and write the result."""
    setup_otel()

    # Load experiment from JSON
    experiment_data = json.loads(Path(input_path).read_text())
    experiment = Experiment.model_validate(experiment_data)
    logger.info("Loaded experiment with %d scenarios from %s", len(experiment.scenarios), input_path)

    # Execute
    executor = A2AExecutor(agent_url=agent_url, workflow_name=workflow_name)
    executed = await executor.run(experiment)

    # Write output
    output_path = Path("data/experiments/executed_experiment.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(executed.model_dump_json(indent=2))
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
