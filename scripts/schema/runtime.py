"""Experiment runtime that iterates scenarios and steps, calling async hooks."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Generic, TypeVar, get_args

from schema.models import Experiment, Scenario, Step

# ---------------------------------------------------------------------------
# Type variables
# ---------------------------------------------------------------------------

ScenarioIn = TypeVar("ScenarioIn", bound=Scenario)
ScenarioOut = TypeVar("ScenarioOut", bound=Scenario)
StepIn = TypeVar("StepIn", bound=Step)
StepOut = TypeVar("StepOut", bound=Step)
ExperimentIn = TypeVar("ExperimentIn", bound=Experiment)
ExperimentOut = TypeVar("ExperimentOut", bound=Experiment)

# ---------------------------------------------------------------------------
# Hook type aliases (generic – parameterise for concrete pipelines)
# ---------------------------------------------------------------------------

BeforeRunHook = Callable[[ExperimentIn], Awaitable[None]]
BeforeScenarioHook = Callable[[ScenarioIn], Awaitable[None]]
AfterScenarioHook = Callable[[ScenarioIn, ScenarioOut], Awaitable[None]]
OnStepHook = Callable[[StepIn, ScenarioIn], Awaitable[StepOut]]


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


def _resolve_scenario_type(model: type[Experiment]) -> type[Scenario]:
    """Extract the Scenario subclass from an Experiment model's ``scenarios`` field."""
    annotation = model.model_fields["scenarios"].annotation
    args = get_args(annotation)
    if args and isinstance(args[0], type) and issubclass(args[0], Scenario):
        return args[0]
    return Scenario


class ExperimentRuntime(Generic[ExperimentIn, ExperimentOut]):
    """Iterate an experiment's scenarios and steps, delegating work to hooks.

    The runtime is generic over input and output experiment types.
    ``ExperimentIn`` (via *input_model*) determines the Pydantic model used
    to **load** the experiment file.  ``ExperimentOut`` (via *output_model*)
    determines the model used to **construct and serialise** the result.

    When *output_model* differs from *input_model*, each output scenario is
    validated through the output model's scenario type so that subtype fields
    produced by hooks (e.g. ``ExecutedStep.turns``) are preserved and the
    ``after_scenario`` hook receives a properly-typed output scenario.
    """

    def __init__(
        self,
        on_step: OnStepHook[Step, Scenario, Step],
        input_path: str | Path,
        output_path: str | Path,
        before_run: BeforeRunHook[Experiment] | None = None,
        before_scenario: BeforeScenarioHook[Scenario] | None = None,
        after_scenario: AfterScenarioHook[Scenario, Scenario] | None = None,
        input_model: type[ExperimentIn] = Experiment,  # type: ignore[assignment]
        output_model: type[ExperimentOut] | None = None,
    ) -> None:
        self._on_step = on_step
        self._input_path = Path(input_path)
        self._output_path = Path(output_path)
        self._before_run = before_run
        self._before_scenario = before_scenario
        self._after_scenario = after_scenario
        self._input_model = input_model
        self._output_model: type[ExperimentOut] = output_model or input_model  # type: ignore[assignment]
        self._output_scenario_type = _resolve_scenario_type(self._output_model)  # type: ignore[arg-type]

    async def run(self) -> ExperimentOut:
        """Load experiment, execute all scenarios, write result, and return it."""
        data = json.loads(self._input_path.read_text())
        experiment = self._input_model.model_validate(data)

        if self._before_run is not None:
            await self._before_run(experiment)

        executed_scenarios: list[Scenario] = []

        for scenario in experiment.scenarios:
            if self._before_scenario is not None:
                await self._before_scenario(scenario)

            output_steps: list[Step] = []
            for step in scenario.steps:
                output_steps.append(await self._on_step(step, scenario))

            # Validate through the output scenario type so that subtype fields
            # from hooks are preserved and the correct model is constructed
            # (e.g. ExecutedScenario instead of Scenario).
            scenario_data = scenario.model_dump()
            scenario_data["steps"] = [s.model_dump() for s in output_steps]
            output_scenario = self._output_scenario_type.model_validate(scenario_data)

            if self._after_scenario is not None:
                await self._after_scenario(scenario, output_scenario)

            executed_scenarios.append(output_scenario)

        # Validate through the output experiment model.
        experiment_data = experiment.model_dump()
        experiment_data["scenarios"] = [s.model_dump() for s in executed_scenarios]
        result = self._output_model.model_validate(experiment_data)

        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._output_path.write_text(result.model_dump_json(indent=2, serialize_as_any=True, exclude_none=True))

        return result