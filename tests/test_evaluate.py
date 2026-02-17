"""
Unit tests for evaluate.py

Tests the RAGAS evaluation functionality.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from evaluate import (
    format_experiment_results,
    instantiate_metric,
    load_metrics_config,
    main,
)
from metrics import GenericMetricsRegistry


# Fixtures
@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests"""
    tmp = tempfile.mkdtemp()
    original_cwd = Path.cwd()
    yield tmp, original_cwd
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def experiment_data(temp_dir):
    """Create test experiment JSONL file"""
    tmp, original_cwd = temp_dir

    # Create test experiment JSONL
    experiment_dir = Path(tmp) / "data" / "experiments"
    experiment_dir.mkdir(parents=True, exist_ok=True)

    experiment_file = experiment_dir / "ragas_experiment.jsonl"
    test_data = [
        {
            "user_input": "What is the weather?",
            "retrieved_contexts": ["Context about weather"],
            "reference": "Expected answer",
            "response": "The weather is sunny.",
            "sample_hash": "abc123def456",
            "trace_id": "a1b2c3d4e5f6789012345678901234ab",
        }
    ]

    with open(experiment_file, "w") as f:
        for item in test_data:
            f.write(json.dumps(item) + "\n")

    return tmp, original_cwd, experiment_file


@pytest.fixture
def default_registry():
    """Fixture providing a default GenericMetricsRegistry."""
    return GenericMetricsRegistry.create_default()


# TestFormatExperimentResults tests
def test_format_experiment_results_basic(tmp_path):
    """Test format_experiment_results with basic experiment output"""
    # Create experiment results file
    experiment_file = tmp_path / "ragas_evaluation.jsonl"
    test_data = [
        {
            "user_input": "Q1",
            "response": "A1",
            "faithfulness": 0.9,
            "answer_relevancy": 0.85,
            "trace_id": "trace1",
        },
        {
            "user_input": "Q2",
            "response": "A2",
            "faithfulness": 0.8,
            "answer_relevancy": 0.75,
            "trace_id": "trace2",
        },
    ]
    with open(experiment_file, "w") as f:
        for item in test_data:
            f.write(json.dumps(item) + "\n")

    # Create metric definitions
    metric_definitions = [
        {"type": "class", "class_name": "faithfulness"},
        {"type": "class", "class_name": "answer_relevancy"},
    ]

    # Format results
    formatted = format_experiment_results(
        experiment_file=str(experiment_file),
        metric_definitions=metric_definitions,
    )

    # Verify overall scores (means)
    assert abs(formatted.overall_scores["faithfulness"] - 0.85) < 0.01
    assert abs(formatted.overall_scores["answer_relevancy"] - 0.80) < 0.01

    # Verify individual results preserved
    assert len(formatted.individual_results) == 2
    assert formatted.individual_results[0]["trace_id"] == "trace1"
    assert formatted.individual_results[1]["trace_id"] == "trace2"

    # Verify token usage (currently returns 0 - Phase 4 TODO)
    assert formatted.total_tokens["input_tokens"] == 0
    assert formatted.total_tokens["output_tokens"] == 0
    assert formatted.total_cost == 0.0


# TestMain tests
@pytest.mark.asyncio
async def test_main_no_config(experiment_data):
    """Test main function with missing metrics config file"""

    tmp, original_cwd, experiment_file = experiment_data
    os.chdir(tmp)

    try:
        # When config file doesn't exist, should raise FileNotFoundError
        with pytest.raises(FileNotFoundError):
            await main(
                model="gemini-flash-latest",
                metrics_config="nonexistent_config.json",
            )
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_main_successful_execution(experiment_data, monkeypatch, tmp_path):
    """Test main function successful execution with config file."""
    from pathlib import Path

    tmp, original_cwd, experiment_file = experiment_data
    os.chdir(tmp)

    try:
        # Create config file
        config_file = tmp_path / "test_metrics.json"
        config = {"version": "1.0", "metrics": [{"type": "class", "class_name": "test_metric"}]}

        with open(config_file, "w") as f:
            json.dump(config, f)

        # Create experiment results directory and file for the experiment load
        experiment_results_dir = Path(tmp) / "data" / "experiments"
        experiment_results_dir.mkdir(parents=True, exist_ok=True)
        ragas_experiment_file = experiment_results_dir / "ragas_experiment.jsonl"

        # Write test experiment input (this is what Experiment.load reads)
        test_input = {"user_input": "Q1", "response": "A1", "retrieved_contexts": ["C1"], "reference": "R1"}
        with open(ragas_experiment_file, "w") as f:
            f.write(json.dumps(test_input) + "\n")

        # Mock evaluation_experiment.arun with new signature
        async def mock_experiment_arun(dataset, name, metric_definitions, llm, registry):
            # Verify registry is GenericMetricsRegistry
            assert isinstance(registry, GenericMetricsRegistry)

            # Create the evaluation results file that would be created by the experiment
            evaluation_results_file = experiment_results_dir / "ragas_evaluation.jsonl"
            test_result = {
                "user_input": "Q1",
                "response": "A1",
                "individual_results": {"test_metric": 0.85},
                "trace_id": "trace1",
            }
            with open(evaluation_results_file, "w") as f:
                f.write(json.dumps(test_result) + "\n")

        # Mock AsyncOpenAI and llm_factory
        class MockAsyncOpenAI:
            pass

        def mock_async_openai_init(api_key):
            return MockAsyncOpenAI()

        class MockLLM:
            pass

        def mock_llm_factory(model, client):
            return MockLLM()

        monkeypatch.setattr("evaluate.evaluation_experiment.arun", mock_experiment_arun)
        monkeypatch.setattr("evaluate.AsyncOpenAI", mock_async_openai_init)
        monkeypatch.setattr("evaluate.llm_factory", mock_llm_factory)

        # Run main with config file
        await main(
            model="gemini-flash-latest",
            metrics_config=str(config_file),
        )

        # Verify evaluation results file was created by the mock
        evaluation_results_file = experiment_results_dir / "ragas_evaluation.jsonl"
        assert evaluation_results_file.exists(), f"Evaluation results file not found at {evaluation_results_file}"

        # Verify the results file has correct structure
        with open(evaluation_results_file, "r") as f:
            line = f.readline()
            data = json.loads(line)

        assert "individual_results" in data
        assert "test_metric" in data["individual_results"]
    finally:
        os.chdir(original_cwd)


# TestMetricDiscovery tests
def test_metric_discovery(default_registry):
    """Test that metric classes are discovered via GenericMetricsRegistry."""
    metrics = default_registry.list_metrics("ragas")
    assert "ragas" in metrics
    assert len(metrics["ragas"]) > 0


# Test instantiate_metric
def test_instantiate_metric_success(default_registry):
    """Test successful class instantiation returns tuple of (callable, name)."""
    from unittest.mock import MagicMock

    ragas_metrics = default_registry.list_metrics("ragas").get("ragas", [])
    if not ragas_metrics:
        pytest.skip("No metric classes available")

    # Create mock LLM
    mock_llm = MagicMock()

    # Find a class that can be instantiated without parameters
    for class_name in ragas_metrics:
        try:
            metric_def = {"type": "class", "class_name": class_name, "parameters": {}, "framework": "ragas"}
            callable_, name = instantiate_metric(metric_def, mock_llm, default_registry)
            assert callable_ is not None
            assert name == class_name
            return  # Success!
        except (TypeError, ValueError):
            continue  # Try next class
    pytest.skip("No metric classes can be instantiated without parameters")


def test_instantiate_metric_unknown(default_registry):
    """Test error for unknown class."""
    from unittest.mock import MagicMock

    mock_llm = MagicMock()
    metric_def = {"type": "class", "class_name": "NonexistentClass", "parameters": {}, "framework": "ragas"}
    with pytest.raises(ValueError, match="Unknown RAGAS metric class"):
        instantiate_metric(metric_def, mock_llm, default_registry)


def test_instantiate_metric_invalid_params(default_registry):
    """Test error for invalid parameters or LLM validation."""
    from unittest.mock import MagicMock

    ragas_metrics = default_registry.list_metrics("ragas").get("ragas", [])
    if not ragas_metrics:
        pytest.skip("No metric classes available")

    mock_llm = MagicMock()
    class_name = ragas_metrics[0]
    metric_def = {
        "type": "class",
        "class_name": class_name,
        "parameters": {"completely_invalid_param_name_xyz": "value"},
        "framework": "ragas",
    }
    # Should raise ValueError either for invalid parameters or LLM validation
    with pytest.raises(ValueError, match="(Invalid parameters|InstructorLLM)"):
        instantiate_metric(metric_def, mock_llm, default_registry)


# Test load_metrics_config
def test_load_metrics_config_json(tmp_path, default_registry):
    """Test loading metrics from JSON config file - skipped as instances are not supported."""
    pytest.skip("Instance-type metrics are no longer supported")


def test_load_metrics_config_with_class(tmp_path, default_registry):
    """Test loading metrics config returns definitions with framework default."""
    ragas_metrics = default_registry.list_metrics("ragas").get("ragas", [])
    if not ragas_metrics:
        pytest.skip("No metric classes available")

    # Use any class name (we're not instantiating, just loading config)
    class_name = ragas_metrics[0]

    config_file = tmp_path / "metrics.json"
    config = {
        "version": "1.0",
        "metrics": [{"type": "class", "class_name": class_name, "parameters": {}}],
    }

    with open(config_file, "w") as f:
        json.dump(config, f)

    # load_metrics_config should return list of dicts with framework default added
    definitions = load_metrics_config(str(config_file))
    assert len(definitions) == 1
    assert isinstance(definitions[0], dict)
    assert definitions[0]["type"] == "class"
    assert definitions[0]["class_name"] == class_name
    assert definitions[0]["parameters"] == {}
    assert definitions[0]["framework"] == "ragas"


def test_load_metrics_config_invalid_format(tmp_path):
    """Test error for invalid file format"""
    config_file = tmp_path / "metrics.txt"
    config_file.write_text("invalid")

    with pytest.raises(ValueError, match="Unsupported config file format"):
        load_metrics_config(str(config_file))


def test_load_metrics_config_missing_metrics_key(tmp_path):
    """Test error for missing 'metrics' key"""
    config_file = tmp_path / "metrics.json"

    with open(config_file, "w") as f:
        json.dump({"version": "1.0"}, f)

    with pytest.raises(ValueError, match="must contain 'metrics' key"):
        load_metrics_config(str(config_file))


def test_load_metrics_config_empty_metrics(tmp_path):
    """Test error for empty metrics list"""
    config_file = tmp_path / "metrics.json"

    config = {"version": "1.0", "metrics": []}

    with open(config_file, "w") as f:
        json.dump(config, f)

    with pytest.raises(ValueError, match="contains no valid metrics"):
        load_metrics_config(str(config_file))


# Test GenericMetricsRegistry
def test_registry_initialization():
    """Test that GenericMetricsRegistry initializes with RAGAS adapter."""
    registry = GenericMetricsRegistry.create_default()

    metrics = registry.list_metrics()
    assert "ragas" in metrics
    assert len(metrics["ragas"]) > 0


def test_registry_get_instance(default_registry):
    """Test getting instances from registry - skipped as instances not supported."""
    pytest.skip("Instance-type metrics are no longer supported")


def test_registry_get_instance_unknown(default_registry):
    """Test error for unknown instance - skipped as instances not supported."""
    pytest.skip("Instance-type metrics are no longer supported")


def test_registry_list_ragas_metrics(default_registry):
    """Test listing RAGAS metrics from registry."""
    metrics = default_registry.list_metrics("ragas")
    assert "ragas" in metrics
    assert len(metrics["ragas"]) > 0


def test_registry_unknown_framework(default_registry):
    """Test error for unknown framework."""
    with pytest.raises(ValueError, match="Unknown framework"):
        default_registry.list_metrics("nonexistent")


def test_registry_get_callable(default_registry):
    """Test getting a callable from registry."""
    from unittest.mock import MagicMock

    ragas_metrics = default_registry.list_metrics("ragas").get("ragas", [])
    if not ragas_metrics:
        pytest.skip("No RAGAS metrics available")

    mock_llm = MagicMock()

    # Find instantiable class
    for class_name in ragas_metrics:
        try:
            callable_ = default_registry.get_metric_callable("ragas", class_name, {}, mock_llm)
            assert callable_ is not None
            return
        except (TypeError, ValueError):
            continue
    pytest.skip("No classes instantiable without params")


def test_registry_load_from_config(tmp_path, default_registry):
    """Test loading config via registry method - skipped as instances not supported."""
    pytest.skip("Instance-type metrics are no longer supported")
