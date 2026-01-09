"""
Unit tests for publish.py

Tests the OpenTelemetry OTLP metrics publishing functionality.
"""

import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from publish import (
    EvaluationData,
    _get_user_input_hash,
    _get_user_input_truncated,
    _is_metric_value,
    create_and_push_metrics,
    load_evaluation_data,
    publish_metrics,
)


# Mock classes for OpenTelemetry meter provider (used by HTTPXClientInstrumentor)
# Use underscore prefix to avoid naming conflicts with test-specific mock classes
class _OtelMockMeter:
    """Mock meter for instrumentation"""

    def create_counter(self, name, **kwargs):
        return _OtelMockCounter()

    def create_histogram(self, name, **kwargs):
        return _OtelMockHistogram()

    def create_gauge(self, name, **kwargs):
        return _OtelMockGauge()


class _OtelMockCounter:
    def add(self, amount, attributes=None):
        pass


class _OtelMockHistogram:
    def record(self, amount, attributes=None):
        pass


class _OtelMockGauge:
    def set(self, value, attributes=None):
        pass


# Fixtures
@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests"""
    tmp = tempfile.mkdtemp()
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def evaluation_scores_file(temp_dir):
    """Create a test evaluation scores file with individual results"""
    test_file = Path(temp_dir) / "evaluation_scores.json"
    test_data = {
        "overall_scores": {"faithfulness": 0.85, "answer_relevancy": 0.90},
        "individual_results": [
            {
                "user_input": "What is the weather?",
                "response": "It is sunny.",
                "faithfulness": 0.85,
                "answer_relevancy": 0.90,
                "trace_id": "a1b2c3d4e5f6789012345678901234aa",
            },
            {
                "user_input": "What is the time?",
                "response": "It is noon.",
                "faithfulness": 0.80,
                "answer_relevancy": 0.95,
                "trace_id": "b2c3d4e5f6a7890123456789012345bb",
            },
        ],
        "total_tokens": {"input_tokens": 1000, "output_tokens": 200},
        "total_cost": 0.05,
    }

    with open(test_file, "w") as f:
        json.dump(test_data, f)

    return test_file


@pytest.fixture
def realistic_scores_file(temp_dir):
    """Create a realistic evaluation scores file"""
    test_file = Path(temp_dir) / "evaluation_scores.json"
    test_data = {
        "overall_scores": {
            "faithfulness": 0.8523,
            "answer_relevancy": 0.9012,
            "context_precision": 0.7845,
            "context_recall": 0.8234,
        },
        "individual_results": [
            {
                "user_input": "What is the weather?",
                "response": "It is sunny.",
                "faithfulness": 0.85,
                "answer_relevancy": 0.90,
                "context_precision": 0.78,
                "context_recall": 0.82,
                "trace_id": "c3d4e5f6a7b8901234567890123456cc",
            }
        ],
        "total_tokens": {"input_tokens": 500, "output_tokens": 100},
        "total_cost": 0.025,
    }

    with open(test_file, "w") as f:
        json.dump(test_data, f, indent=2)

    return test_file


# Test _is_metric_value
def test_is_metric_value_with_float():
    """Test that valid floats are recognized as metric values"""
    assert _is_metric_value(0.85) is True
    assert _is_metric_value(1.0) is True
    assert _is_metric_value(0.0) is True


def test_is_metric_value_with_int():
    """Test that integers are recognized as metric values"""
    assert _is_metric_value(1) is True
    assert _is_metric_value(0) is True


def test_is_metric_value_with_nan():
    """Test that NaN is not recognized as a metric value"""
    assert _is_metric_value(float("nan")) is False
    assert _is_metric_value(math.nan) is False


def test_is_metric_value_with_non_numeric():
    """Test that non-numeric values are not recognized as metric values"""
    assert _is_metric_value("string") is False
    assert _is_metric_value(["list"]) is False
    assert _is_metric_value({"dict": "value"}) is False
    assert _is_metric_value(None) is False


# Test _get_user_input_hash
def test_get_user_input_hash_returns_12_char_hex():
    """Test that _get_user_input_hash returns a 12-character hex string"""
    result = _get_user_input_hash("What is the weather?")
    assert len(result) == 12
    assert all(c in "0123456789abcdef" for c in result)


def test_get_user_input_hash_is_deterministic():
    """Test that _get_user_input_hash returns the same hash for the same input"""
    input_text = "What is the weather in New York?"
    assert _get_user_input_hash(input_text) == _get_user_input_hash(input_text)


def test_get_user_input_hash_different_for_different_inputs():
    """Test that _get_user_input_hash returns different hashes for different inputs"""
    hash1 = _get_user_input_hash("Question 1")
    hash2 = _get_user_input_hash("Question 2")
    assert hash1 != hash2


# Test _get_user_input_truncated
def test_get_user_input_truncated_short_input():
    """Test that short inputs are returned unchanged"""
    short_input = "Short question"
    assert _get_user_input_truncated(short_input) == short_input


def test_get_user_input_truncated_exact_length():
    """Test that inputs exactly at max_length are returned unchanged"""
    exact_input = "a" * 50
    assert _get_user_input_truncated(exact_input) == exact_input


def test_get_user_input_truncated_long_input():
    """Test that long inputs are truncated with ellipsis"""
    long_input = "a" * 100
    result = _get_user_input_truncated(long_input)
    assert len(result) == 53  # 50 chars + "..."
    assert result.endswith("...")


def test_get_user_input_truncated_custom_length():
    """Test that custom max_length is respected"""
    input_text = "This is a longer question"
    result = _get_user_input_truncated(input_text, max_length=10)
    assert result == "This is a ..."


# Test load_evaluation_data
def test_loads_evaluation_data(evaluation_scores_file):
    """Test that load_evaluation_data loads all required fields"""
    data = load_evaluation_data(str(evaluation_scores_file))

    assert len(data.individual_results) == 2
    assert data.total_tokens["input_tokens"] == 1000
    assert data.total_tokens["output_tokens"] == 200
    assert data.total_cost == 0.05


def test_file_not_found(temp_dir):
    """Test behavior when file doesn't exist"""
    with pytest.raises(FileNotFoundError):
        load_evaluation_data(str(Path(temp_dir) / "nonexistent.json"))


# TestCreateAndPushMetrics tests
def test_creates_gauges_for_each_metric(monkeypatch):
    """Test that a Gauge is created for each metric plus token/cost gauges"""
    evaluation_data = EvaluationData(
        individual_results=[
            {"user_input": "Question 1", "faithfulness": 0.85, "answer_relevancy": 0.90, "trace_id": "trace1"},
            {"user_input": "Question 2", "faithfulness": 0.80, "answer_relevancy": 0.95, "trace_id": "trace2"},
        ],
        total_tokens={"input_tokens": 1000, "output_tokens": 200},
        total_cost=0.05,
    )

    # Mock the meter and gauge
    create_gauge_calls = []

    class MockGauge:
        def set(self, value, attributes):
            pass

    class MockMeter:
        def create_gauge(self, name, unit=None, description=None):
            create_gauge_calls.append({"name": name, "unit": unit, "description": description})
            return MockGauge()

    mock_meter = MockMeter()

    def mock_get_meter(*args, **kwargs):
        return mock_meter

    # Mock the provider
    class MockProvider:
        def force_flush(self):
            return True

        def shutdown(self):
            pass

        def get_meter(self, name, version=None, schema_url=None, attributes=None):
            """Return a mock meter that HTTPXClientInstrumentor can use"""
            return _OtelMockMeter()

    def mock_provider_init(**kwargs):
        return MockProvider()

    # Mock the exporter
    class MockExporter:
        _preferred_temporality = {}
        _preferred_aggregation = {}

    def mock_exporter_init(endpoint):
        return MockExporter()

    monkeypatch.setattr("publish.metrics.get_meter", mock_get_meter)
    monkeypatch.setattr("publish.MeterProvider", mock_provider_init)
    monkeypatch.setattr("publish.OTLPMetricExporter", mock_exporter_init)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4318")

    create_and_push_metrics(
        evaluation_data=evaluation_data,
        workflow_name="test-workflow",
        execution_id="exec-test-123",
        execution_number=42,
    )

    # Verify gauges created: 1 metric gauge + 1 token gauge + 1 cost gauge = 3
    assert len(create_gauge_calls) == 3

    # Verify gauge names
    gauge_names = [call["name"] for call in create_gauge_calls]
    assert "testbench_evaluation_metric" in gauge_names
    assert "testbench_evaluation_token_usage" in gauge_names
    assert "testbench_evaluation_cost" in gauge_names


def test_sets_per_sample_gauge_values(monkeypatch):
    """Test that gauge values are set for each sample with all required attributes"""
    evaluation_data = EvaluationData(
        individual_results=[
            {"user_input": "Question 1", "faithfulness": 0.85, "trace_id": "d4e5f6a7b8c9012345678901234567dd"},
            {
                "user_input": "This is a very long question that exceeds fifty characters in length",
                "faithfulness": 0.80,
                "trace_id": "e5f6a7b8c9d0123456789012345678ee",
            },
        ],
        total_tokens={"input_tokens": 0, "output_tokens": 0},
        total_cost=0.0,
    )

    # Mock the meter and gauge
    set_calls = []

    class MockGauge:
        def __init__(self, name):
            self.name = name

        def set(self, value, attributes):
            set_calls.append({"name": self.name, "value": value, "attributes": attributes})

    class MockMeter:
        def create_gauge(self, name, unit=None, description=None):
            return MockGauge(name)

    mock_meter = MockMeter()

    def mock_get_meter(*args, **kwargs):
        return mock_meter

    # Mock the provider
    class MockProvider:
        def force_flush(self):
            return True

        def shutdown(self):
            pass

        def get_meter(self, name, version=None, schema_url=None, attributes=None):
            """Return a mock meter that HTTPXClientInstrumentor can use"""
            return _OtelMockMeter()

    def mock_provider_init(**kwargs):
        return MockProvider()

    # Mock the exporter
    class MockExporter:
        _preferred_temporality = {}
        _preferred_aggregation = {}

    def mock_exporter_init(endpoint):
        return MockExporter()

    monkeypatch.setattr("publish.metrics.get_meter", mock_get_meter)
    monkeypatch.setattr("publish.MeterProvider", mock_provider_init)
    monkeypatch.setattr("publish.OTLPMetricExporter", mock_exporter_init)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4318")

    create_and_push_metrics(
        evaluation_data=evaluation_data,
        workflow_name="test-workflow",
        execution_id="exec-test-123",
        execution_number=42,
    )

    # Filter to faithfulness metric calls only (name attribute = "faithfulness")
    faithfulness_calls = [
        c
        for c in set_calls
        if c["name"] == "testbench_evaluation_metric" and c["attributes"].get("name") == "faithfulness"
    ]
    assert len(faithfulness_calls) == 2

    # Verify gauge.set was called with correct values and all required attributes
    # First sample: short question
    assert faithfulness_calls[0]["value"] == 0.85
    assert faithfulness_calls[0]["attributes"]["workflow_name"] == "test-workflow"
    assert faithfulness_calls[0]["attributes"]["execution_id"] == "exec-test-123"
    assert faithfulness_calls[0]["attributes"]["execution_number"] == 42
    assert faithfulness_calls[0]["attributes"]["trace_id"] == "d4e5f6a7b8c9012345678901234567dd"
    assert faithfulness_calls[0]["attributes"]["user_input_hash"] == _get_user_input_hash("Question 1")
    assert faithfulness_calls[0]["attributes"]["user_input_truncated"] == "Question 1"

    # Second sample: long question (should be truncated)
    long_question = "This is a very long question that exceeds fifty characters in length"
    assert faithfulness_calls[1]["value"] == 0.80
    assert faithfulness_calls[1]["attributes"]["execution_id"] == "exec-test-123"
    assert faithfulness_calls[1]["attributes"]["execution_number"] == 42
    assert faithfulness_calls[1]["attributes"]["trace_id"] == "e5f6a7b8c9d0123456789012345678ee"
    assert faithfulness_calls[1]["attributes"]["user_input_hash"] == _get_user_input_hash(long_question)
    assert faithfulness_calls[1]["attributes"]["user_input_truncated"] == _get_user_input_truncated(long_question)


def test_pushes_via_otlp(monkeypatch):
    """Test that metrics are pushed via OTLP"""
    evaluation_data = EvaluationData(
        individual_results=[{"user_input": "Q1", "faithfulness": 0.85, "trace_id": "f6a7b8c9d0e1234567890123456789ff"}],
        total_tokens={"input_tokens": 100, "output_tokens": 50},
        total_cost=0.01,
    )

    # Mock the meter and gauge
    class MockGauge:
        def set(self, value, attributes):
            pass

    class MockMeter:
        def create_gauge(self, name, unit=None, description=None):
            return MockGauge()

    mock_meter = MockMeter()

    def mock_get_meter(*args, **kwargs):
        return mock_meter

    # Mock the provider
    force_flush_calls = []
    shutdown_calls = []

    class MockProvider:
        def force_flush(self):
            force_flush_calls.append(True)
            return True

        def shutdown(self):
            shutdown_calls.append(True)

    def mock_provider_init(**kwargs):
        return MockProvider()

    # Mock the exporter
    class MockExporter:
        _preferred_temporality = {}
        _preferred_aggregation = {}

    exporter_calls = []

    def mock_exporter_init(endpoint):
        exporter_calls.append({"endpoint": endpoint})
        return MockExporter()

    monkeypatch.setattr("publish.metrics.get_meter", mock_get_meter)
    monkeypatch.setattr("publish.MeterProvider", mock_provider_init)
    monkeypatch.setattr("publish.OTLPMetricExporter", mock_exporter_init)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4318")

    create_and_push_metrics(
        evaluation_data=evaluation_data,
        workflow_name="test-workflow",
        execution_id="exec-test-123",
        execution_number=42,
    )

    # Verify OTLPMetricExporter was initialized with correct endpoint
    assert len(exporter_calls) == 1
    assert exporter_calls[0]["endpoint"] == "http://localhost:4318/v1/metrics"

    # Verify force_flush and shutdown were called
    assert len(force_flush_calls) == 1
    assert len(shutdown_calls) == 1


def test_handles_push_error(monkeypatch):
    """Test error handling when OTLP export fails"""
    evaluation_data = EvaluationData(
        individual_results=[{"user_input": "Q1", "faithfulness": 0.85, "trace_id": "a7b8c9d0e1f2345678901234567890aa"}],
        total_tokens={"input_tokens": 0, "output_tokens": 0},
        total_cost=0.0,
    )

    def mock_get_meter(*args, **kwargs):
        return _OtelMockMeter()

    # Mock the provider to return False on force_flush (indicating failure)
    shutdown_calls = []

    class MockProvider:
        def force_flush(self):
            return False

        def shutdown(self):
            shutdown_calls.append(True)

    def mock_provider_init(**kwargs):
        return MockProvider()

    # Mock the exporter
    class MockExporter:
        _preferred_temporality = {}
        _preferred_aggregation = {}

    def mock_exporter_init(endpoint):
        return MockExporter()

    monkeypatch.setattr("publish.metrics.get_meter", mock_get_meter)
    monkeypatch.setattr("publish.MeterProvider", mock_provider_init)
    monkeypatch.setattr("publish.OTLPMetricExporter", mock_exporter_init)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4318")

    with pytest.raises(RuntimeError, match="Failed to flush metrics"):
        create_and_push_metrics(
            evaluation_data=evaluation_data,
            workflow_name="test-workflow",
            execution_id="exec-test-123",
            execution_number=42,
        )

    # Verify shutdown is still called in finally block
    assert len(shutdown_calls) == 1


# TestPublishMetrics tests
def test_publish_metrics_calls_create_and_push(evaluation_scores_file, monkeypatch):
    """Test that publish_metrics calls create_and_push_metrics"""
    create_push_calls = []

    def mock_create_push(evaluation_data, workflow_name, execution_id, execution_number):
        create_push_calls.append(
            {
                "evaluation_data": evaluation_data,
                "workflow_name": workflow_name,
                "execution_id": execution_id,
                "execution_number": execution_number,
            }
        )

    monkeypatch.setattr("publish.create_and_push_metrics", mock_create_push)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4318")

    publish_metrics(
        input_file=str(evaluation_scores_file),
        workflow_name="test-workflow",
        execution_id="exec-test-123",
        execution_number=42,
    )

    # Verify create_and_push_metrics was called
    assert len(create_push_calls) == 1

    # Verify parameters
    assert len(create_push_calls[0]["evaluation_data"].individual_results) == 2
    assert create_push_calls[0]["workflow_name"] == "test-workflow"
    assert create_push_calls[0]["execution_id"] == "exec-test-123"
    assert create_push_calls[0]["execution_number"] == 42


def test_publish_metrics_with_empty_results(temp_dir, monkeypatch):
    """Test behavior when individual_results is empty"""
    # Create file with empty individual_results
    test_data = {
        "overall_scores": {},
        "individual_results": [],
        "total_tokens": {"input_tokens": 0, "output_tokens": 0},
        "total_cost": 0.0,
    }

    empty_file = Path(temp_dir) / "empty_scores.json"
    with open(empty_file, "w") as f:
        json.dump(test_data, f)

    create_push_calls = []

    def mock_create_push(evaluation_data, workflow_name, execution_id, execution_number):
        create_push_calls.append(True)

    monkeypatch.setattr("publish.create_and_push_metrics", mock_create_push)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4318")

    publish_metrics(
        input_file=str(empty_file),
        workflow_name="test-workflow",
        execution_id="exec-test-123",
        execution_number=42,
    )

    # Verify create_and_push_metrics was NOT called
    assert len(create_push_calls) == 0


# TestIntegrationWithTestData tests
def test_publish_realistic_scores(realistic_scores_file, monkeypatch):
    """Test publishing realistic evaluation scores"""
    # Mock the meter and gauge
    create_gauge_calls = []

    class MockGauge:
        def set(self, value, attributes):
            pass

    class MockMeter:
        def create_gauge(self, name, unit=None, description=None):
            create_gauge_calls.append({"name": name})
            return MockGauge()

    mock_meter = MockMeter()

    def mock_get_meter(*args, **kwargs):
        return mock_meter

    # Mock the provider
    class MockProvider:
        def force_flush(self):
            return True

        def shutdown(self):
            pass

        def get_meter(self, name, version=None, schema_url=None, attributes=None):
            """Return a mock meter that HTTPXClientInstrumentor can use"""
            return _OtelMockMeter()

    def mock_provider_init(**kwargs):
        return MockProvider()

    # Mock the exporter
    class MockExporter:
        _preferred_temporality = {}
        _preferred_aggregation = {}

    exporter_calls = []

    def mock_exporter_init(endpoint):
        exporter_calls.append(True)
        return MockExporter()

    monkeypatch.setattr("publish.metrics.get_meter", mock_get_meter)
    monkeypatch.setattr("publish.MeterProvider", mock_provider_init)
    monkeypatch.setattr("publish.OTLPMetricExporter", mock_exporter_init)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4318")

    publish_metrics(
        input_file=str(realistic_scores_file),
        workflow_name="weather-assistant-test",
        execution_id="exec-weather-456",
        execution_number=42,
    )

    # Verify OTLPMetricExporter was called
    assert len(exporter_calls) == 1

    # Verify 3 gauges: 1 metric gauge + 1 token gauge + 1 cost gauge
    assert len(create_gauge_calls) == 3

    gauge_names = [call["name"] for call in create_gauge_calls]
    assert "testbench_evaluation_metric" in gauge_names
    assert "testbench_evaluation_token_usage" in gauge_names
    assert "testbench_evaluation_cost" in gauge_names
