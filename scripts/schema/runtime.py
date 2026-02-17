"""Experiment runtime that iterates scenarios and steps, calling async hooks."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path

from schema.models import Experiment, Scenario, Step

# ---------------------------------------------------------------------------
# Hook type aliases
# ---------------------------------------------------------------------------

BeforeScenarioHook = Callable[[Scenario], Awaitable[None]]
AfterScenarioHook = Callable[[Scenario, Scenario], Awaitable[None]]
OnStepHook = Callable[[Step, Scenario], Awaitable[Step]]


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


class ExperimentRuntime:
    """Iterate an experiment's scenarios and steps, delegating work to hooks.

    The runtime is type-agnostic: it accepts any ``Experiment`` subtype and
    preserves all fields via ``model_copy(update=...)``.  The concrete output
    type is determined by what ``on_step`` returns.
    """

    def __init__(
        self,
        on_step: OnStepHook,
        input_path: str | Path,
        output_path: str | Path,
        before_scenario: BeforeScenarioHook | None = None,
        after_scenario: AfterScenarioHook | None = None,
    ) -> None:
        self._on_step = on_step
        self._input_path = Path(input_path)
        self._output_path = Path(output_path)
        self._before_scenario = before_scenario
        self._after_scenario = after_scenario

    async def run(self) -> Experiment:
        """Load experiment, execute all scenarios, write result, and return it."""
        data = json.loads(self._input_path.read_text())
        experiment = Experiment.model_validate(data)

        executed_scenarios: list[Scenario] = []

        for scenario in experiment.scenarios:
            if self._before_scenario is not None:
                await self._before_scenario(scenario)

            output_steps: list[Step] = []
            for step in scenario.steps:
                output_steps.append(await self._on_step(step, scenario))

            output_scenario = scenario.model_copy(update={"steps": output_steps})

            if self._after_scenario is not None:
                await self._after_scenario(scenario, output_scenario)

            executed_scenarios.append(output_scenario)

        result = experiment.model_copy(update={"scenarios": executed_scenarios})

        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._output_path.write_text(result.model_dump_json(indent=2))

        return result
