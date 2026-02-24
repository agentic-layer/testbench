"""Unit tests for testbench/evaluate.py (MetricEvaluator)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from evaluate import MetricEvaluator, main  # noqa: E402
from schema.models import (  # noqa: E402
    EvaluatedExperiment,
    EvaluatedStep,
    ExecutedStep,
    Metric,
    Reference,
    Turn,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executed_experiment(
    scenarios: list[dict],
    default_threshold: float = 0.9,
    llm_as_a_judge_model: str = "test-model",
) -> dict:
    """Build an ExecutedExperiment dict for JSON serialisation."""
    return {
        "id": "test-exp",
        "llm_as_a_judge_model": llm_as_a_judge_model,
        "default_threshold": default_threshold,
        "scenarios": scenarios,
    }


def _make_scenario(
    name: str,
    steps: list[dict],
    scenario_id: str = "scn_1",
) -> dict:
    return {
        "name": name,
        "id": scenario_id,
        "trace_id": "0" * 32,
        "steps": steps,
    }


def _make_step(
    input_text: str = "What is the weather?",
    metrics: list[dict] | None = None,
    step_id: str = "stp_1",
    turns: list[dict] | None = None,
    reference: dict | None = None,
) -> dict:
    step: dict = {
        "input": input_text,
        "id": step_id,
    }
    if metrics is not None:
        step["metrics"] = metrics
    if turns is not None:
        step["turns"] = turns
    if reference is not None:
        step["reference"] = reference
    return step


def _metric(name: str = "faithfulness", threshold: float | None = None, parameters: dict | None = None) -> dict:
    m: dict = {"metric_name": name}
    if threshold is not None:
        m["threshold"] = threshold
    if parameters is not None:
        m["parameters"] = parameters
    return m


def _mock_metric_callable(score: float = 0.85) -> AsyncMock:
    """Return an AsyncMock that behaves like a MetricCallable."""
    from metrics.protocol import MetricResult

    mock = AsyncMock()
    mock.return_value = MetricResult(score=score)
    return mock


# ---------------------------------------------------------------------------
# Tests: on_step
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_step_single_metric(tmp_path: Path) -> None:
    """Step with one metric produces one Evaluation with correct score."""
    experiment_data = _make_executed_experiment(
        scenarios=[_make_scenario("s1", [_make_step(metrics=[_metric("faithfulness")])])]
    )
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps(experiment_data))

    evaluator = MetricEvaluator(str(input_file), str(tmp_path / "out.json"))
    evaluator._default_threshold = 0.9

    mock_callable = _mock_metric_callable(0.95)

    with patch.object(evaluator._registry, "get_metric_callable", return_value=mock_callable):
        step = ExecutedStep(input="What is the weather?", id="stp_1", metrics=[Metric(metric_name="faithfulness")])
        result = await evaluator.on_step(step, MagicMock())

    assert isinstance(result, EvaluatedStep)
    assert result.evaluations is not None
    assert len(result.evaluations) == 1
    assert result.evaluations[0].result.score == 0.95
    assert result.evaluations[0].metric.metric_name == "faithfulness"


@pytest.mark.asyncio
async def test_evaluate_step_threshold_pass(tmp_path: Path) -> None:
    """Score above threshold → result='pass'."""
    evaluator = MetricEvaluator(str(tmp_path / "in.json"), str(tmp_path / "out.json"))
    evaluator._default_threshold = 0.5

    mock_callable = _mock_metric_callable(0.8)

    with patch.object(evaluator._registry, "get_metric_callable", return_value=mock_callable):
        step = ExecutedStep(
            input="q",
            id="stp_1",
            metrics=[Metric(metric_name="faithfulness", threshold=0.7)],
        )
        result = await evaluator.on_step(step, MagicMock())

    assert result.evaluations is not None
    assert result.evaluations[0].result.result == "pass"


@pytest.mark.asyncio
async def test_evaluate_step_threshold_fail(tmp_path: Path) -> None:
    """Score below threshold → result='fail'."""
    evaluator = MetricEvaluator(str(tmp_path / "in.json"), str(tmp_path / "out.json"))
    evaluator._default_threshold = 0.5

    mock_callable = _mock_metric_callable(0.6)

    with patch.object(evaluator._registry, "get_metric_callable", return_value=mock_callable):
        step = ExecutedStep(
            input="q",
            id="stp_1",
            metrics=[Metric(metric_name="faithfulness", threshold=0.8)],
        )
        result = await evaluator.on_step(step, MagicMock())

    assert result.evaluations is not None
    assert result.evaluations[0].result.result == "fail"


@pytest.mark.asyncio
async def test_evaluate_step_default_threshold(tmp_path: Path) -> None:
    """When metric has no threshold, default_threshold is used."""
    evaluator = MetricEvaluator(str(tmp_path / "in.json"), str(tmp_path / "out.json"))
    evaluator._default_threshold = 0.8

    # Score 0.75 is below default 0.8 → fail
    mock_callable = _mock_metric_callable(0.75)

    with patch.object(evaluator._registry, "get_metric_callable", return_value=mock_callable):
        step = ExecutedStep(
            input="q",
            id="stp_1",
            metrics=[Metric(metric_name="faithfulness")],  # no threshold
        )
        result = await evaluator.on_step(step, MagicMock())

    assert result.evaluations is not None
    assert result.evaluations[0].result.result == "fail"


@pytest.mark.asyncio
async def test_evaluate_step_no_metrics(tmp_path: Path) -> None:
    """Step with no metrics → evaluations is None."""
    evaluator = MetricEvaluator(str(tmp_path / "in.json"), str(tmp_path / "out.json"))

    step = ExecutedStep(input="q", id="stp_1", metrics=None)
    result = await evaluator.on_step(step, MagicMock())

    assert isinstance(result, EvaluatedStep)
    assert result.evaluations is None


@pytest.mark.asyncio
async def test_evaluate_step_preserves_fields(tmp_path: Path) -> None:
    """EvaluatedStep preserves all original ExecutedStep fields."""
    evaluator = MetricEvaluator(str(tmp_path / "in.json"), str(tmp_path / "out.json"))

    mock_callable = _mock_metric_callable(0.9)

    with patch.object(evaluator._registry, "get_metric_callable", return_value=mock_callable):
        step = ExecutedStep(
            input="What is the weather?",
            id="stp_abc",
            reference=Reference(response="It is sunny"),
            custom_values={"key": "val"},
            metrics=[Metric(metric_name="faithfulness")],
            turns=[Turn(content="What is the weather?", type="human")],
        )
        result = await evaluator.on_step(step, MagicMock())

    assert result.input == "What is the weather?"
    assert result.id == "stp_abc"
    assert result.reference is not None
    assert result.reference.response == "It is sunny"
    assert result.custom_values == {"key": "val"}
    assert result.turns is not None
    assert len(result.turns) == 1


@pytest.mark.asyncio
async def test_metric_error_handling(tmp_path: Path) -> None:
    """When a metric raises an exception, it is skipped and others continue."""
    evaluator = MetricEvaluator(str(tmp_path / "in.json"), str(tmp_path / "out.json"))
    evaluator._default_threshold = 0.5

    failing_callable = AsyncMock(side_effect=RuntimeError("LLM timeout"))
    passing_callable = _mock_metric_callable(0.9)

    call_count = 0

    def side_effect(*args: object, **kwargs: object) -> AsyncMock:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return failing_callable
        return passing_callable

    with patch.object(evaluator._registry, "get_metric_callable", side_effect=side_effect):
        step = ExecutedStep(
            input="q",
            id="stp_1",
            metrics=[
                Metric(metric_name="bad_metric"),
                Metric(metric_name="good_metric"),
            ],
        )
        result = await evaluator.on_step(step, MagicMock())

    # Only the passing metric should be in evaluations
    assert result.evaluations is not None
    assert len(result.evaluations) == 1
    assert result.evaluations[0].metric.metric_name == "good_metric"


# ---------------------------------------------------------------------------
# Tests: full run (integration with runtime)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_experiment_full(tmp_path: Path) -> None:
    """Full experiment with two scenarios, each with one step."""
    experiment_data = _make_executed_experiment(
        scenarios=[
            _make_scenario(
                "scenario-a",
                [_make_step("q1", metrics=[_metric("faithfulness")], step_id="stp_1")],
                scenario_id="scn_a",
            ),
            _make_scenario(
                "scenario-b",
                [_make_step("q2", metrics=[_metric("answer_relevancy", threshold=0.5)], step_id="stp_2")],
                scenario_id="scn_b",
            ),
        ],
        default_threshold=0.8,
    )
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps(experiment_data))
    output_file = tmp_path / "output.json"

    evaluator = MetricEvaluator(str(input_file), str(output_file))

    mock_callable = _mock_metric_callable(0.85)

    with patch.object(evaluator._registry, "get_metric_callable", return_value=mock_callable):
        result = await evaluator.run()

    assert isinstance(result, EvaluatedExperiment)
    assert len(result.scenarios) == 2

    # scenario-a: threshold 0.8 (default), score 0.85 → pass
    step_a = result.scenarios[0].steps[0]
    assert step_a.evaluations is not None
    assert step_a.evaluations[0].result.result == "pass"

    # scenario-b: threshold 0.5 (explicit), score 0.85 → pass
    step_b = result.scenarios[1].steps[0]
    assert step_b.evaluations is not None
    assert step_b.evaluations[0].result.result == "pass"


@pytest.mark.asyncio
async def test_main_reads_and_writes_json(tmp_path: Path) -> None:
    """main() writes a valid evaluated_experiment.json."""
    experiment_data = _make_executed_experiment(
        scenarios=[_make_scenario("s1", [_make_step(metrics=[_metric("faithfulness")])])]
    )
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps(experiment_data))
    output_file = tmp_path / "output.json"

    mock_callable = _mock_metric_callable(0.95)

    with patch("evaluate.GenericMetricsRegistry.create_default") as mock_registry_cls:
        mock_registry = MagicMock()
        mock_registry.get_metric_callable.return_value = mock_callable
        mock_registry_cls.return_value = mock_registry

        await main(str(input_file), str(output_file))

    assert output_file.exists()
    data = json.loads(output_file.read_text())
    validated = EvaluatedExperiment.model_validate(data)
    assert len(validated.scenarios) == 1
    assert validated.scenarios[0].steps[0].evaluations is not None


@pytest.mark.asyncio
async def test_evaluate_step_multiple_metrics(tmp_path: Path) -> None:
    """Step with multiple metrics produces multiple Evaluations."""
    evaluator = MetricEvaluator(str(tmp_path / "in.json"), str(tmp_path / "out.json"))
    evaluator._default_threshold = 0.5

    scores = iter([0.9, 0.7])

    async def mock_call(sample: object, **kwargs: object) -> object:
        from metrics.protocol import MetricResult

        return MetricResult(score=next(scores))

    mock_callable = AsyncMock(side_effect=mock_call)

    with patch.object(evaluator._registry, "get_metric_callable", return_value=mock_callable):
        step = ExecutedStep(
            input="q",
            id="stp_1",
            metrics=[
                Metric(metric_name="faithfulness"),
                Metric(metric_name="answer_relevancy"),
            ],
        )
        result = await evaluator.on_step(step, MagicMock())

    assert result.evaluations is not None
    assert len(result.evaluations) == 2
    assert result.evaluations[0].result.score == 0.9
    assert result.evaluations[1].result.score == 0.7
