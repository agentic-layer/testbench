"""
Unit tests for publish.py

Tests the OpenTelemetry OTLP metrics publishing functionality.
"""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from publish import (
    MetricsPublisher,
    _get_user_input_truncated,
    _is_metric_value,
    publish_metrics,
)
from schema.models import (
    EvaluatedExperiment,
    EvaluatedScenario,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evaluated_experiment(
    scenarios: list[dict] | None = None,
) -> EvaluatedExperiment:
    """Build an EvaluatedExperiment from simple dicts for testing."""
    if scenarios is None:
        scenarios = [
            _make_scenario(
                "scenario-1",
                [
                    _make_step(
                        "What is the weather?",
                        step_id="stp_1",
                        evaluations=[("faithfulness", 0.85, "pass", 0.8)],
                        trace_id="a1b2c3d4e5f6789012345678901234aa",
                    )
                ],
                trace_id="a1b2c3d4e5f6789012345678901234aa",
            )
        ]
    return EvaluatedExperiment(id="exp_test123", scenarios=[EvaluatedScenario(**s) for s in scenarios])


def _make_scenario(
    name: str,
    steps: list[dict],
    scenario_id: str = "scn_1",
    trace_id: str = "0" * 32,
) -> dict:
    return {
        "name": name,
        "id": scenario_id,
        "trace_id": trace_id,
        "steps": steps,
    }


def _make_step(
    input_text: str = "What is the weather?",
    step_id: str = "stp_1",
    evaluations: list[tuple[str, float, str] | tuple[str, float, str, float]] | None = None,
    trace_id: str | None = None,
) -> dict:
    step: dict = {"input": input_text, "id": step_id}
    if evaluations is not None:
        eval_list = []
        for entry in evaluations:
            name, score, result = entry[0], entry[1], entry[2]
            threshold = entry[3] if len(entry) > 3 else None  # type: ignore[arg-type]
            metric: dict = {"metric_name": name}
            if threshold is not None:
                metric["threshold"] = threshold
            eval_list.append({"metric": metric, "result": {"score": score, "result": result}})
        step["evaluations"] = eval_list
    return step


def _write_experiment(tmp_path: Path, experiment: EvaluatedExperiment) -> str:
    """Write experiment to a JSON file and return the path."""
    file_path = tmp_path / "evaluated.json"
    file_path.write_text(experiment.model_dump_json(indent=2))
    return str(file_path)


# ---------------------------------------------------------------------------
# Tests: _is_metric_value
# ---------------------------------------------------------------------------


def test_is_metric_value_with_float():
    assert _is_metric_value(0.85) is True
    assert _is_metric_value(1.0) is True
    assert _is_metric_value(0.0) is True


def test_is_metric_value_with_int():
    assert _is_metric_value(1) is True
    assert _is_metric_value(0) is True


def test_is_metric_value_with_nan():
    assert _is_metric_value(float("nan")) is False
    assert _is_metric_value(math.nan) is False


def test_is_metric_value_with_non_numeric():
    assert _is_metric_value("string") is False
    assert _is_metric_value(["list"]) is False
    assert _is_metric_value({"dict": "value"}) is False
    assert _is_metric_value(None) is False


# ---------------------------------------------------------------------------
# Tests: _get_user_input_truncated
# ---------------------------------------------------------------------------


def test_get_user_input_truncated_short_input():
    assert _get_user_input_truncated("Short question") == "Short question"


def test_get_user_input_truncated_exact_length():
    exact_input = "a" * 50
    assert _get_user_input_truncated(exact_input) == exact_input


def test_get_user_input_truncated_long_input():
    long_input = "a" * 100
    result = _get_user_input_truncated(long_input)
    assert len(result) == 53  # 50 chars + "..."
    assert result.endswith("...")


def test_get_user_input_truncated_custom_length():
    result = _get_user_input_truncated("This is a longer question", max_length=10)
    assert result == "This is a ..."


# ---------------------------------------------------------------------------
# Tests: MetricsPublisher (via run())
# ---------------------------------------------------------------------------


def _mock_otel(monkeypatch):
    """Set up common OTel mocks. Returns (create_gauge_calls, set_calls, force_flush_calls, shutdown_calls, exporter_calls)."""
    create_gauge_calls: list[dict] = []
    set_calls: list[dict] = []
    force_flush_calls: list[bool] = []
    shutdown_calls: list[bool] = []
    exporter_calls: list[dict] = []

    class MockGauge:
        def __init__(self, name):
            self.name = name

        def set(self, value, attributes):
            set_calls.append({"name": self.name, "value": value, "attributes": attributes})

    class MockMeter:
        def create_gauge(self, name, unit=None, description=None):
            create_gauge_calls.append({"name": name, "unit": unit, "description": description})
            return MockGauge(name)

    mock_meter = MockMeter()

    def mock_get_meter(*args, **kwargs):
        return mock_meter

    class MockProvider:
        def force_flush(self):
            force_flush_calls.append(True)
            return True

        def shutdown(self):
            shutdown_calls.append(True)

    def mock_provider_init(**kwargs):
        return MockProvider()

    class MockExporter:
        _preferred_temporality = {}
        _preferred_aggregation = {}

    def mock_exporter_init(endpoint):
        exporter_calls.append({"endpoint": endpoint})
        return MockExporter()

    monkeypatch.setattr("publish.metrics.get_meter", mock_get_meter)
    monkeypatch.setattr("publish.MeterProvider", mock_provider_init)
    monkeypatch.setattr("publish.OTLPMetricExporter", mock_exporter_init)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4318")

    return create_gauge_calls, set_calls, force_flush_calls, shutdown_calls, exporter_calls


@pytest.mark.asyncio
async def test_creates_gauge_for_metrics(tmp_path, monkeypatch):
    """A single testbench_evaluation_metric gauge is created."""
    create_gauge_calls, _, _, _, _ = _mock_otel(monkeypatch)

    experiment = _make_evaluated_experiment(
        scenarios=[
            _make_scenario(
                "s1",
                [
                    _make_step(
                        "Q1",
                        step_id="stp_1",
                        evaluations=[("faithfulness", 0.85, "pass", 0.8), ("answer_relevancy", 0.90, "pass", 0.8)],
                    )
                ],
            )
        ]
    )
    file_path = _write_experiment(tmp_path, experiment)

    publisher = MetricsPublisher(file_path, "test-workflow", "exec-123", 42)
    await publisher.run()

    assert len(create_gauge_calls) == 1
    assert create_gauge_calls[0]["name"] == "testbench_evaluation_metric"


@pytest.mark.asyncio
async def test_sets_per_step_gauge_values(tmp_path, monkeypatch):
    """Gauge.set is called for each evaluation with correct attributes."""
    _, set_calls, _, _, _ = _mock_otel(monkeypatch)

    long_question = "This is a very long question that exceeds fifty characters in length"
    experiment = _make_evaluated_experiment(
        scenarios=[
            _make_scenario(
                "s1",
                [
                    _make_step("Question 1", step_id="stp_1", evaluations=[("faithfulness", 0.85, "pass", 0.8)]),
                    _make_step(long_question, step_id="stp_2", evaluations=[("faithfulness", 0.80, "pass", 0.8)]),
                ],
                trace_id="d4e5f6a7b8c9012345678901234567dd",
            )
        ]
    )
    file_path = _write_experiment(tmp_path, experiment)

    publisher = MetricsPublisher(file_path, "test-workflow", "exec-123", 42)
    await publisher.run()

    assert len(set_calls) == 2

    # First step: short question
    assert set_calls[0]["value"] == 0.85
    assert set_calls[0]["attributes"]["workflow_name"] == "test-workflow"
    assert set_calls[0]["attributes"]["execution_id"] == "exec-123"
    assert set_calls[0]["attributes"]["execution_number"] == 42
    assert set_calls[0]["attributes"]["experiment_id"] == "exp_test123"
    assert set_calls[0]["attributes"]["scenario_id"] == "scn_1"
    assert set_calls[0]["attributes"]["scenario_name"] == "s1"
    assert set_calls[0]["attributes"]["step_index"] == "0"
    assert set_calls[0]["attributes"]["trace_id"] == "d4e5f6a7b8c9012345678901234567dd"
    assert set_calls[0]["attributes"]["step_id"] == "stp_1"
    assert set_calls[0]["attributes"]["threshold"] == "0.8"
    assert set_calls[0]["attributes"]["result"] == "pass"
    assert set_calls[0]["attributes"]["user_input_truncated"] == "Question 1"

    # Second step: long question (truncated)
    assert set_calls[1]["value"] == 0.80
    assert set_calls[1]["attributes"]["step_id"] == "stp_2"
    assert set_calls[1]["attributes"]["step_index"] == "1"
    assert set_calls[1]["attributes"]["user_input_truncated"] == _get_user_input_truncated(long_question)


@pytest.mark.asyncio
async def test_pushes_via_otlp(tmp_path, monkeypatch):
    """OTLPMetricExporter is initialised with the correct endpoint."""
    _, _, force_flush_calls, shutdown_calls, exporter_calls = _mock_otel(monkeypatch)

    experiment = _make_evaluated_experiment()
    file_path = _write_experiment(tmp_path, experiment)

    publisher = MetricsPublisher(file_path, "test-workflow", "exec-123", 42)
    await publisher.run()

    assert len(exporter_calls) == 1
    assert exporter_calls[0]["endpoint"] == "http://localhost:4318/v1/metrics"
    assert len(force_flush_calls) == 1
    assert len(shutdown_calls) == 1


@pytest.mark.asyncio
async def test_handles_push_error(tmp_path, monkeypatch):
    """RuntimeError raised when force_flush returns False."""
    shutdown_calls: list[bool] = []

    class _OtelMockMeter:
        def create_gauge(self, name, **kwargs):
            return _OtelMockGauge()

    class _OtelMockGauge:
        def set(self, value, attributes=None):
            pass

    def mock_get_meter(*args, **kwargs):
        return _OtelMockMeter()

    class MockProvider:
        def force_flush(self):
            return False

        def shutdown(self):
            shutdown_calls.append(True)

    def mock_provider_init(**kwargs):
        return MockProvider()

    class MockExporter:
        _preferred_temporality = {}
        _preferred_aggregation = {}

    monkeypatch.setattr("publish.metrics.get_meter", mock_get_meter)
    monkeypatch.setattr("publish.MeterProvider", mock_provider_init)
    monkeypatch.setattr("publish.OTLPMetricExporter", lambda endpoint: MockExporter())
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4318")

    experiment = _make_evaluated_experiment()
    file_path = _write_experiment(tmp_path, experiment)

    publisher = MetricsPublisher(file_path, "test-workflow", "exec-123", 42)

    with pytest.raises(RuntimeError, match="Failed to flush metrics"):
        await publisher.run()

    # shutdown still called in finally block
    assert len(shutdown_calls) == 1


@pytest.mark.asyncio
async def test_skips_steps_without_evaluations(tmp_path, monkeypatch):
    """Steps with no evaluations are skipped."""
    _, set_calls, _, _, _ = _mock_otel(monkeypatch)

    experiment = _make_evaluated_experiment(
        scenarios=[
            _make_scenario(
                "s1",
                [
                    _make_step("Q1", step_id="stp_1", evaluations=None),
                    _make_step("Q2", step_id="stp_2", evaluations=[("faithfulness", 0.9, "pass", 0.8)]),
                ],
            )
        ]
    )
    file_path = _write_experiment(tmp_path, experiment)

    publisher = MetricsPublisher(file_path, "test-workflow", "exec-123", 42)
    await publisher.run()

    assert len(set_calls) == 1
    assert set_calls[0]["attributes"]["step_id"] == "stp_2"


# ---------------------------------------------------------------------------
# Tests: publish_metrics
# ---------------------------------------------------------------------------


def test_publish_metrics_calls_publisher(tmp_path, monkeypatch):
    """publish_metrics loads the file and runs the MetricsPublisher."""
    _, set_calls, _, _, _ = _mock_otel(monkeypatch)

    experiment = _make_evaluated_experiment()
    file_path = _write_experiment(tmp_path, experiment)

    publish_metrics(str(file_path), "test-workflow", "exec-123", 42)

    assert len(set_calls) == 1
    assert set_calls[0]["attributes"]["workflow_name"] == "test-workflow"
    assert set_calls[0]["attributes"]["execution_id"] == "exec-123"
    assert set_calls[0]["attributes"]["execution_number"] == 42


@pytest.mark.asyncio
async def test_publish_metrics_multiple_scenarios(tmp_path, monkeypatch):
    """MetricsPublisher handles multiple scenarios with multiple steps."""
    _, set_calls, _, _, _ = _mock_otel(monkeypatch)

    experiment = _make_evaluated_experiment(
        scenarios=[
            _make_scenario(
                "s1",
                [
                    _make_step("Q1", step_id="stp_1", evaluations=[("faithfulness", 0.85, "pass", 0.8)]),
                    _make_step("Q2", step_id="stp_2", evaluations=[("answer_relevancy", 0.90, "pass", 0.8)]),
                ],
                trace_id="trace_a",
            ),
            _make_scenario(
                "s2",
                [
                    _make_step("Q3", step_id="stp_3", evaluations=[("faithfulness", 0.70, "fail", 0.8)]),
                ],
                trace_id="trace_b",
                scenario_id="scn_2",
            ),
        ]
    )
    file_path = _write_experiment(tmp_path, experiment)

    publisher = MetricsPublisher(file_path, "weather-test", "exec-456", 3)
    await publisher.run()

    assert len(set_calls) == 3
    assert set_calls[0]["attributes"]["name"] == "faithfulness"
    assert set_calls[0]["attributes"]["scenario_name"] == "s1"
    assert set_calls[0]["attributes"]["scenario_id"] == "scn_1"
    assert set_calls[0]["attributes"]["step_index"] == "0"
    assert set_calls[1]["attributes"]["name"] == "answer_relevancy"
    assert set_calls[1]["attributes"]["scenario_name"] == "s1"
    assert set_calls[1]["attributes"]["step_index"] == "1"
    assert set_calls[2]["attributes"]["name"] == "faithfulness"
    assert set_calls[2]["attributes"]["trace_id"] == "trace_b"
    assert set_calls[2]["attributes"]["scenario_name"] == "s2"
    assert set_calls[2]["attributes"]["scenario_id"] == "scn_2"
    assert set_calls[2]["attributes"]["step_index"] == "0"


@pytest.mark.asyncio
async def test_step_index_resets_per_scenario(tmp_path, monkeypatch):
    """step_index resets to 0 at the start of each scenario."""
    _, set_calls, _, _, _ = _mock_otel(monkeypatch)

    experiment = _make_evaluated_experiment(
        scenarios=[
            _make_scenario(
                "scenario-a",
                [
                    _make_step("Q1", step_id="stp_1", evaluations=[("faithfulness", 0.9, "pass", 0.8)]),
                    _make_step("Q2", step_id="stp_2", evaluations=[("faithfulness", 0.8, "pass", 0.8)]),
                ],
                scenario_id="scn_a",
            ),
            _make_scenario(
                "scenario-b",
                [
                    _make_step("Q3", step_id="stp_3", evaluations=[("faithfulness", 0.7, "fail", 0.8)]),
                ],
                scenario_id="scn_b",
            ),
        ]
    )
    file_path = _write_experiment(tmp_path, experiment)

    publisher = MetricsPublisher(file_path, "wf", "exec-1", 1)
    await publisher.run()

    assert len(set_calls) == 3
    # Scenario A: step_index 0, 1
    assert set_calls[0]["attributes"]["step_index"] == "0"
    assert set_calls[0]["attributes"]["scenario_name"] == "scenario-a"
    assert set_calls[1]["attributes"]["step_index"] == "1"
    assert set_calls[1]["attributes"]["scenario_name"] == "scenario-a"
    # Scenario B: step_index resets to 0
    assert set_calls[2]["attributes"]["step_index"] == "0"
    assert set_calls[2]["attributes"]["scenario_name"] == "scenario-b"


@pytest.mark.asyncio
async def test_threshold_and_result_attributes(tmp_path, monkeypatch):
    """Threshold is stringified and result is passed through."""
    _, set_calls, _, _, _ = _mock_otel(monkeypatch)

    experiment = _make_evaluated_experiment(
        scenarios=[
            _make_scenario(
                "s1",
                [
                    _make_step(
                        "Q1",
                        step_id="stp_1",
                        evaluations=[
                            ("faithfulness", 0.5, "fail", 0.8),
                            ("relevancy", 0.95, "pass"),
                        ],
                    ),
                ],
            )
        ]
    )
    file_path = _write_experiment(tmp_path, experiment)

    publisher = MetricsPublisher(file_path, "wf", "exec-1", 1)
    await publisher.run()

    assert len(set_calls) == 2
    # With threshold
    assert set_calls[0]["attributes"]["threshold"] == "0.8"
    assert set_calls[0]["attributes"]["result"] == "fail"
    # Without threshold
    assert set_calls[1]["attributes"]["threshold"] == ""
    assert set_calls[1]["attributes"]["result"] == "pass"
