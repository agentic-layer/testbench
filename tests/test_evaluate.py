"""
Unit tests for testbench/evaluate.py module.

This file provides basic import and structure validation.
Comprehensive functional tests are in test_evaluate_experiment.py.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from evaluate import MetricEvaluator, main  # noqa: E402


def test_metric_evaluator_import():
    """MetricEvaluator can be imported from evaluate module."""
    assert MetricEvaluator is not None
    assert hasattr(MetricEvaluator, "__init__")


def test_main_import():
    """main function can be imported from evaluate module."""
    assert main is not None
    assert callable(main)


def test_metric_evaluator_initialization(tmp_path):
    """MetricEvaluator can be instantiated with input and output paths."""
    input_file = tmp_path / "input.json"
    output_file = tmp_path / "output.json"

    evaluator = MetricEvaluator(str(input_file), str(output_file))

    assert evaluator.input_path == str(input_file)
    assert evaluator.output_path == str(output_file)


def test_metric_evaluator_has_registry(tmp_path):
    """MetricEvaluator has a _registry attribute."""
    evaluator = MetricEvaluator(str(tmp_path / "in.json"), str(tmp_path / "out.json"))

    assert hasattr(evaluator, "_registry")
    assert evaluator._registry is not None


def test_metric_evaluator_has_expected_attributes(tmp_path):
    """MetricEvaluator has all expected internal attributes."""
    evaluator = MetricEvaluator(str(tmp_path / "in.json"), str(tmp_path / "out.json"))

    # Check critical internal state
    assert hasattr(evaluator, "_model")
    assert hasattr(evaluator, "_cli_model")
    assert hasattr(evaluator, "_default_threshold")
    assert hasattr(evaluator, "_current_steps")

    # Check default values
    assert evaluator._default_threshold == 0.9
    assert evaluator._cli_model is None
    assert evaluator._model == ""
    assert evaluator._current_steps == []


def test_metric_evaluator_has_hooks(tmp_path):
    """MetricEvaluator implements required runtime hooks."""
    evaluator = MetricEvaluator(str(tmp_path / "in.json"), str(tmp_path / "out.json"))

    # Verify hook methods exist
    assert hasattr(evaluator, "before_run")
    assert hasattr(evaluator, "before_scenario")
    assert hasattr(evaluator, "after_scenario")
    assert hasattr(evaluator, "on_step")

    # Verify all hooks are callable
    assert callable(evaluator.before_run)
    assert callable(evaluator.before_scenario)
    assert callable(evaluator.after_scenario)
    assert callable(evaluator.on_step)


def test_metric_evaluator_has_run_method(tmp_path):
    """MetricEvaluator has public run() method."""
    evaluator = MetricEvaluator(str(tmp_path / "in.json"), str(tmp_path / "out.json"))

    assert hasattr(evaluator, "run")
    assert callable(evaluator.run)


@pytest.mark.asyncio
async def test_main_signature():
    """main() accepts input_path, output_path, and optional model."""
    import inspect

    sig = inspect.signature(main)
    params = list(sig.parameters.keys())

    assert "input_path" in params
    assert "output_path" in params
    assert "model" in params

    # Check model is optional
    assert sig.parameters["model"].default is None
