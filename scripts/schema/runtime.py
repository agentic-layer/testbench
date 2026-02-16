"""Experiment runtime that iterates scenarios and steps, calling async hooks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

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
        before_scenario: BeforeScenarioHook | None = None,
        after_scenario: AfterScenarioHook | None = None,
    ) -> None:
        self._on_step = on_step
        self._before_scenario = before_scenario
        self._after_scenario = after_scenario

    async def run(self, experiment: Experiment) -> Experiment:
        """Execute all scenarios sequentially, returning a new experiment."""
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

        return experiment.model_copy(update={"scenarios": executed_scenarios})
