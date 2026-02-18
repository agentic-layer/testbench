"""
Unit tests for visualize.py

Tests the HTML visualization generation functionality.
"""

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "testbench"))

from visualize import (
    _format_multi_turn_conversation,
    _get_score_class,
    _is_multi_turn_conversation,
    _is_valid_metric_value,
    calculate_metric_statistics,
    load_evaluation_data,
    main,
    prepare_chart_data,
)


# Fixtures
@pytest.fixture
def evaluated_experiment_file(tmp_path):
    """Create test evaluated_experiment.json file"""
    test_file = tmp_path / "evaluated_experiment.json"

    # Create EvaluatedExperiment structure
    experiment_data = {
        "scenarios": [
            {
                "name": "scenario_1",
                "id": "scenario_1",
                "trace_id": "a1b2c3d4e5f6",
                "steps": [
                    {
                        "input": "What is the weather?",
                        "id": "step_1",
                        "reference": {"response": "Expected answer"},
                        "evaluations": [
                            {"metric": {"metric_name": "faithfulness"}, "result": {"score": 0.85}},
                            {"metric": {"metric_name": "answer_relevancy"}, "result": {"score": 0.90}},
                            {"metric": {"metric_name": "context_recall"}, "result": {"score": 0.80}},
                        ],
                        "custom_values": {"response": "It is sunny."},
                    }
                ],
            },
            {
                "name": "scenario_2",
                "id": "scenario_2",
                "trace_id": "b2c3d4e5f6a7",
                "steps": [
                    {
                        "input": "What is the time?",
                        "id": "step_2",
                        "reference": {"response": "Expected answer"},
                        "evaluations": [
                            {"metric": {"metric_name": "faithfulness"}, "result": {"score": 0.80}},
                            {"metric": {"metric_name": "answer_relevancy"}, "result": {"score": 0.95}},
                            {"metric": {"metric_name": "context_recall"}, "result": {"score": 0.85}},
                        ],
                        "custom_values": {"response": "It is noon."},
                    }
                ],
            },
        ]
    }

    with open(test_file, "w") as f:
        json.dump(experiment_data, f)

    return test_file


@pytest.fixture
def empty_evaluated_experiment_file(tmp_path):
    """Create empty evaluated_experiment.json file"""
    test_file = tmp_path / "empty_evaluated_experiment.json"

    # Empty experiment with no scenarios
    experiment_data = {"scenarios": []}

    with open(test_file, "w") as f:
        json.dump(experiment_data, f)

    return test_file


# Test _is_valid_metric_value
def test_is_valid_metric_value_with_float():
    """Test valid floats are recognized"""
    assert _is_valid_metric_value(0.85) is True
    assert _is_valid_metric_value(1.0) is True
    assert _is_valid_metric_value(0.0) is True


def test_is_valid_metric_value_with_int():
    """Test valid integers are recognized"""
    assert _is_valid_metric_value(1) is True
    assert _is_valid_metric_value(0) is True


def test_is_valid_metric_value_with_nan():
    """Test NaN is not recognized as valid"""
    assert _is_valid_metric_value(float("nan")) is False
    assert _is_valid_metric_value(math.nan) is False


def test_is_valid_metric_value_with_non_numeric():
    """Test non-numeric values are not valid"""
    assert _is_valid_metric_value("string") is False
    assert _is_valid_metric_value(None) is False
    assert _is_valid_metric_value([]) is False
    assert _is_valid_metric_value({}) is False


# Test load_evaluation_data
def test_loads_evaluation_data(evaluated_experiment_file):
    """Test loading evaluation data from EvaluatedExperiment JSON"""
    data = load_evaluation_data(str(evaluated_experiment_file))

    assert len(data.individual_results) == 2
    assert len(data.metric_names) == 3
    assert "faithfulness" in data.metric_names
    assert "answer_relevancy" in data.metric_names
    assert "context_recall" in data.metric_names
    # Token and cost tracking not available in new format
    assert data.total_tokens["input_tokens"] == 0
    assert data.total_tokens["output_tokens"] == 0
    assert data.total_cost == 0.0
    # Overall scores calculated from individual results
    assert data.overall_scores["faithfulness"] == 0.825  # Mean of 0.85 and 0.80


def test_loads_empty_evaluation_data(empty_evaluated_experiment_file):
    """Test loading empty evaluation data"""
    data = load_evaluation_data(str(empty_evaluated_experiment_file))

    assert len(data.individual_results) == 0
    assert len(data.metric_names) == 0
    assert data.total_tokens["input_tokens"] == 0
    assert data.total_cost == 0.0


def test_file_not_found_error(tmp_path):
    """Test error when file doesn't exist"""
    with pytest.raises(FileNotFoundError):
        load_evaluation_data(str(tmp_path / "nonexistent.json"))


def test_handles_invalid_json(tmp_path):
    """Test error when file is not valid JSON"""
    from pydantic import ValidationError

    invalid_file = tmp_path / "invalid.json"
    with open(invalid_file, "w") as f:
        f.write("{invalid json content")

    with pytest.raises((json.JSONDecodeError, ValidationError)):
        load_evaluation_data(str(invalid_file))


def test_handles_missing_evaluations(tmp_path):
    """Test handling of steps without evaluations"""
    test_file = tmp_path / "missing_evaluations.json"

    experiment_data = {
        "scenarios": [
            {
                "name": "scenario_1",
                "id": "scenario_1",
                "trace_id": "trace_1",
                "steps": [
                    {
                        "input": "test",
                        "id": "step_1",
                        # No evaluations
                    }
                ],
            },
            {
                "name": "scenario_2",
                "id": "scenario_2",
                "trace_id": "trace_2",
                "steps": [
                    {
                        "input": "test2",
                        "id": "step_2",
                        "evaluations": [{"metric": {"metric_name": "metric1"}, "result": {"score": 0.5}}],
                    }
                ],
            },
        ]
    }

    with open(test_file, "w") as f:
        json.dump(experiment_data, f)

    data = load_evaluation_data(str(test_file))
    # Both steps are included, one has no metrics
    assert len(data.individual_results) == 2


def test_discovers_metric_names_correctly(tmp_path):
    """Test metric name discovery from evaluations"""
    test_file = tmp_path / "test.json"

    experiment_data = {
        "scenarios": [
            {
                "name": "scenario_1",
                "id": "scenario_1",
                "trace_id": "trace_1",
                "steps": [
                    {
                        "input": "test",
                        "id": "step_1",
                        "evaluations": [
                            {"metric": {"metric_name": "metric1"}, "result": {"score": 0.5}},
                            {"metric": {"metric_name": "metric2"}, "result": {"score": 0.7}},
                        ],
                    }
                ],
            }
        ]
    }

    with open(test_file, "w") as f:
        json.dump(experiment_data, f)

    data = load_evaluation_data(str(test_file))
    assert set(data.metric_names) == {"metric1", "metric2"}


def test_extracts_custom_values(tmp_path):
    """Test that custom_values are added to individual results"""
    test_file = tmp_path / "test.json"

    experiment_data = {
        "scenarios": [
            {
                "name": "scenario_1",
                "id": "scenario_1",
                "trace_id": "trace_1",
                "steps": [
                    {
                        "input": "test",
                        "id": "step_1",
                        "custom_values": {"response": "custom response", "custom_field": "custom value"},
                        "evaluations": [{"metric": {"metric_name": "metric1"}, "result": {"score": 0.5}}],
                    }
                ],
            }
        ]
    }

    with open(test_file, "w") as f:
        json.dump(experiment_data, f)

    data = load_evaluation_data(str(test_file))
    result = data.individual_results[0]
    assert result["response"] == "custom response"
    assert result["custom_field"] == "custom value"


# Test calculate_metric_statistics
def test_calculates_statistics_correctly():
    """Test metric statistics calculation"""
    results = [{"faithfulness": 0.85}, {"faithfulness": 0.90}, {"faithfulness": 0.80}]

    stats = calculate_metric_statistics(results, "faithfulness")

    assert stats is not None
    assert stats["min"] == 0.80
    assert stats["max"] == 0.90
    assert abs(stats["mean"] - 0.85) < 0.01
    assert stats["median"] == 0.85
    assert stats["valid_count"] == 3
    assert "std" in stats


def test_filters_nan_values_in_statistics():
    """Test NaN values are excluded from statistics"""
    results = [{"faithfulness": 0.85}, {"faithfulness": float("nan")}, {"faithfulness": 0.90}]

    stats = calculate_metric_statistics(results, "faithfulness")

    assert stats is not None
    assert stats["valid_count"] == 2
    assert stats["min"] == 0.85
    assert stats["max"] == 0.90


def test_handles_missing_metric():
    """Test behavior when metric doesn't exist in results"""
    results = [{"faithfulness": 0.85}, {"other_metric": 0.90}]

    stats = calculate_metric_statistics(results, "nonexistent_metric")

    assert stats is None


def test_handles_single_value_statistics():
    """Test statistics calculation with single value"""
    results = [{"faithfulness": 0.85}]

    stats = calculate_metric_statistics(results, "faithfulness")

    assert stats is not None
    assert stats["min"] == 0.85
    assert stats["max"] == 0.85
    assert stats["mean"] == 0.85
    assert stats["median"] == 0.85
    assert stats["std"] == 0.0  # No standard deviation for single value


# Test prepare_chart_data
def test_prepares_chart_data_structure(evaluated_experiment_file):
    """Test chart data structure is correct"""
    viz_data = load_evaluation_data(str(evaluated_experiment_file))
    chart_data = prepare_chart_data(viz_data)

    assert "overall_scores" in chart_data
    assert "metric_distributions" in chart_data
    assert "samples" in chart_data
    assert "tokens" in chart_data
    assert "cost" in chart_data


def test_chart_data_has_correct_overall_scores(evaluated_experiment_file):
    """Test overall scores are correctly calculated"""
    viz_data = load_evaluation_data(str(evaluated_experiment_file))
    chart_data = prepare_chart_data(viz_data)

    # Overall scores are calculated as mean from individual results
    assert chart_data["overall_scores"]["faithfulness"] == 0.825  # Mean of 0.85 and 0.80
    assert chart_data["overall_scores"]["answer_relevancy"] == 0.925  # Mean of 0.90 and 0.95


def test_chart_data_has_metric_distributions(evaluated_experiment_file):
    """Test metric distributions are calculated"""
    viz_data = load_evaluation_data(str(evaluated_experiment_file))
    chart_data = prepare_chart_data(viz_data)

    assert "faithfulness" in chart_data["metric_distributions"]
    assert "values" in chart_data["metric_distributions"]["faithfulness"]
    assert "stats" in chart_data["metric_distributions"]["faithfulness"]


def test_chart_data_has_samples(evaluated_experiment_file):
    """Test samples are prepared correctly"""
    viz_data = load_evaluation_data(str(evaluated_experiment_file))
    chart_data = prepare_chart_data(viz_data)

    assert len(chart_data["samples"]) == 2
    assert chart_data["samples"][0]["index"] == 1
    assert chart_data["samples"][0]["user_input"] == "What is the weather?"
    assert "metrics" in chart_data["samples"][0]


def test_handles_empty_individual_results(empty_evaluated_experiment_file):
    """Test handling of empty individual results"""
    viz_data = load_evaluation_data(str(empty_evaluated_experiment_file))
    chart_data = prepare_chart_data(viz_data)

    assert chart_data["samples"] == []
    assert chart_data["metric_distributions"] == {}
    assert chart_data["overall_scores"] == {}


def test_handles_missing_trace_ids(tmp_path):
    """Test handling of missing trace_ids"""
    test_file = tmp_path / "no_trace.json"

    experiment_data = {
        "scenarios": [
            {
                "name": "scenario_1",
                "id": "scenario_1",
                # No trace_id
                "steps": [
                    {
                        "input": "test",
                        "id": "step_1",
                        "evaluations": [{"metric": {"metric_name": "metric1"}, "result": {"score": 0.5}}],
                    }
                ],
            }
        ]
    }

    with open(test_file, "w") as f:
        json.dump(experiment_data, f)

    viz_data = load_evaluation_data(str(test_file))
    chart_data = prepare_chart_data(viz_data)

    # visualize.py uses "unknown" for missing trace_ids
    assert chart_data["samples"][0]["trace_id"] == "unknown"


# Test _get_score_class
def test_get_score_class_high():
    """Test high score classification"""
    assert _get_score_class(0.85) == "high"
    assert _get_score_class(0.95) == "high"
    assert _get_score_class(1.0) == "high"


def test_get_score_class_medium():
    """Test medium score classification"""
    assert _get_score_class(0.6) == "medium"
    assert _get_score_class(0.7) == "medium"
    assert _get_score_class(0.79) == "medium"


def test_get_score_class_low():
    """Test low score classification"""
    assert _get_score_class(0.3) == "low"
    assert _get_score_class(0.0) == "low"
    assert _get_score_class(0.49) == "low"


# Test HTML generation
def test_generates_valid_html_file(evaluated_experiment_file, tmp_path):
    """Test HTML file is generated with correct structure"""
    output_file = tmp_path / "report.html"

    main(str(evaluated_experiment_file), str(output_file), "test-workflow", "test-exec-001", 1)

    assert output_file.exists()

    # Read and validate HTML structure
    html_content = output_file.read_text()
    assert "<!DOCTYPE html>" in html_content
    assert "test-workflow" in html_content
    assert "chart.js" in html_content  # CDN reference
    assert "overallScoresChart" in html_content  # Chart canvas
    assert "faithfulness" in html_content  # Metric name
    assert "trace_id" in html_content  # Table column


def test_html_contains_all_metrics(evaluated_experiment_file, tmp_path):
    """Test all metrics appear in HTML"""
    output_file = tmp_path / "report.html"

    main(str(evaluated_experiment_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert "faithfulness" in html_content
    assert "answer_relevancy" in html_content
    assert "context_recall" in html_content


def test_html_contains_summary_cards(evaluated_experiment_file, tmp_path):
    """Test summary cards are generated"""
    output_file = tmp_path / "report.html"

    main(str(evaluated_experiment_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert "Total Samples" in html_content
    assert "Metrics Evaluated" in html_content
    # Tokens and Cost cards are hidden when values are 0 (new format doesn't track these)


def test_html_contains_timestamp(evaluated_experiment_file, tmp_path):
    """Test timestamp is included in HTML"""
    output_file = tmp_path / "report.html"

    main(str(evaluated_experiment_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert "Generated:" in html_content


def test_creates_output_directory(evaluated_experiment_file, tmp_path):
    """Test output directory is created if missing"""
    output_file = tmp_path / "nested" / "dir" / "report.html"

    main(str(evaluated_experiment_file), str(output_file), "test-workflow", "test-exec-001", 1)

    assert output_file.exists()
    assert output_file.parent.exists()


def test_html_has_substantial_content(evaluated_experiment_file, tmp_path):
    """Test HTML file has substantial content"""
    output_file = tmp_path / "report.html"

    main(str(evaluated_experiment_file), str(output_file), "test-workflow", "test-exec-001", 1)

    assert output_file.stat().st_size > 5000  # Should be at least 5KB


def test_html_with_empty_results(empty_evaluated_experiment_file, tmp_path):
    """Test HTML generation with empty results"""
    output_file = tmp_path / "empty_report.html"

    main(str(empty_evaluated_experiment_file), str(output_file), "test-workflow", "test-exec-001", 1)

    assert output_file.exists()
    html_content = output_file.read_text()
    assert "<!DOCTYPE html>" in html_content
    assert "Total Samples" in html_content


# Integration test
def test_end_to_end_html_generation(evaluated_experiment_file, tmp_path):
    """Test complete flow from load to HTML generation"""
    output_file = tmp_path / "final_report.html"

    # Run main function
    main(str(evaluated_experiment_file), str(output_file), "end-to-end-workflow", "exec-e2e-001", 5)

    # Validate file exists and has content
    assert output_file.exists()
    assert output_file.stat().st_size > 1000  # Should be substantial

    # Validate HTML structure
    html_content = output_file.read_text()
    assert "<!DOCTYPE html>" in html_content
    assert "end-to-end-workflow" in html_content
    assert "Execution 5" in html_content
    assert "chart.js" in html_content
    assert "faithfulness" in html_content
    assert "answer_relevancy" in html_content

    # Validate all sections are present
    assert "summary-section" in html_content
    assert "chart-section" in html_content
    assert "distributions-section" in html_content
    assert "table-section" in html_content
    assert "footer" in html_content


def test_html_contains_search_functionality(evaluated_experiment_file, tmp_path):
    """Test table search functionality is included"""
    output_file = tmp_path / "report.html"

    main(str(evaluated_experiment_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert "searchInput" in html_content
    assert "addEventListener" in html_content


def test_html_contains_chart_initialization(evaluated_experiment_file, tmp_path):
    """Test Chart.js initialization code is present"""
    output_file = tmp_path / "report.html"

    main(str(evaluated_experiment_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert "new Chart(" in html_content
    assert "reportData" in html_content


def test_main_with_workflow_metadata(evaluated_experiment_file, tmp_path):
    """Test main function with workflow metadata"""
    output_file = tmp_path / "custom_workflow_report.html"

    main(str(evaluated_experiment_file), str(output_file), "custom-workflow", "custom-exec-123", 42)

    html_content = output_file.read_text()
    assert "custom-workflow" in html_content
    assert "custom-exec-123" in html_content
    assert "Execution 42" in html_content


def test_html_displays_workflow_info_section(evaluated_experiment_file, tmp_path):
    """Test that workflow information appears in metadata section"""
    output_file = tmp_path / "workflow_info_report.html"

    main(str(evaluated_experiment_file), str(output_file), "weather-agent", "exec-w123", 7)

    html_content = output_file.read_text()

    # Check title contains workflow info
    assert "weather-agent - Execution 7 (exec-w123)" in html_content

    # Check metadata section exists
    assert 'class="metadata"' in html_content
    assert 'class="workflow-info"' in html_content

    # Check all parts of workflow info are present
    assert "Workflow: weather-agent" in html_content
    assert "Execution: 7" in html_content
    assert "ID: exec-w123" in html_content


# Test multi-turn conversation support
def test_is_multi_turn_conversation_with_dict_containing_turns():
    """Test detection of multi-turn conversation from result dict"""
    result = {
        "turns": [
            {"content": "Hello", "type": "human"},
            {"content": "Hi there", "type": "agent"},
        ]
    }
    assert _is_multi_turn_conversation(result) is True


def test_is_multi_turn_conversation_without_turns():
    """Test result without turns is not detected as multi-turn"""
    result = {"user_input": "Simple string"}
    assert _is_multi_turn_conversation(result) is False


def test_is_multi_turn_conversation_with_empty_turns():
    """Test empty turns list is not multi-turn"""
    result = {"turns": []}
    assert _is_multi_turn_conversation(result) is False


def test_is_multi_turn_conversation_with_invalid_structure():
    """Test list without proper message structure is not multi-turn"""
    result = {"turns": [{"invalid": "structure"}]}
    assert _is_multi_turn_conversation(result) is False


def test_format_multi_turn_conversation():
    """Test formatting of multi-turn conversation"""
    conversation = [
        {"content": "What is the weather?", "type": "human"},
        {"content": "It is sunny.", "type": "agent"},
    ]

    html = _format_multi_turn_conversation(conversation)

    assert '<div class="conversation">' in html
    assert '<div class="message human">' in html
    assert '<div class="message ai">' in html
    assert "HUMAN:" in html
    assert "AGENT:" in html
    assert "What is the weather?" in html
    assert "It is sunny." in html


def test_prepare_chart_data_with_multi_turn(tmp_path):
    """Test chart data preparation with multi-turn conversations"""
    test_file = tmp_path / "multi_turn.json"

    experiment_data = {
        "scenarios": [
            {
                "name": "scenario_1",
                "id": "scenario_1",
                "trace_id": "abc123",
                "steps": [
                    {
                        "input": "Multi-turn conversation",
                        "id": "step_1",
                        "turns": [
                            {"content": "Hello", "type": "human"},
                            {"content": "Hi", "type": "agent"},
                        ],
                        "evaluations": [{"metric": {"metric_name": "metric1"}, "result": {"score": 0.5}}],
                    }
                ],
            }
        ]
    }

    with open(test_file, "w") as f:
        json.dump(experiment_data, f)

    viz_data = load_evaluation_data(str(test_file))
    chart_data = prepare_chart_data(viz_data)

    assert len(chart_data["samples"]) == 1
    sample = chart_data["samples"][0]
    assert sample["is_multi_turn"] is True
    assert "user_input_formatted" in sample
    assert '<div class="conversation">' in sample["user_input_formatted"]


def test_html_with_multi_turn_conversations(tmp_path):
    """Test HTML generation with multi-turn conversations"""
    test_file = tmp_path / "multi_turn.json"
    output_file = tmp_path / "multi_turn_report.html"

    experiment_data = {
        "scenarios": [
            {
                "name": "scenario_1",
                "id": "scenario_1",
                "trace_id": "test123",
                "steps": [
                    {
                        "input": "Multi-turn question",
                        "id": "step_1",
                        "turns": [
                            {"content": "Question 1", "type": "human"},
                            {"content": "Answer 1", "type": "agent"},
                            {"content": "Question 2", "type": "human"},
                        ],
                        "custom_values": {"response": "Final response"},
                        "evaluations": [{"metric": {"metric_name": "metric1"}, "result": {"score": 0.8}}],
                    }
                ],
            }
        ]
    }

    with open(test_file, "w") as f:
        json.dump(experiment_data, f)

    main(str(test_file), str(output_file), "multi-turn-workflow", "multi-exec-001", 1)

    html_content = output_file.read_text()
    assert '<div class="conversation">' in html_content
    assert "Question 1" in html_content
    assert "Answer 1" in html_content
    assert "Question 2" in html_content
    assert "HUMAN:" in html_content
    assert "AGENT:" in html_content


def test_format_multi_turn_conversation_with_tool_calls():
    """Test formatting conversations with tool calls"""
    conversation = [
        {"content": "What's the weather?", "type": "human"},
        {"content": "", "type": "agent", "tool_calls": [{"name": "get_weather", "args": {"city": "NYC"}}]},
        {"content": "{'status': 'success', 'report': 'Sunny, 72F'}", "type": "tool"},
        {"content": "The weather is sunny.", "type": "agent"},
    ]

    html = _format_multi_turn_conversation(conversation)

    # Verify structure
    assert '<div class="conversation">' in html
    assert '<div class="message human">' in html
    assert '<div class="message tool">' in html
    assert '<div class="message ai">' in html

    # Verify tool call display
    assert "tool-calls-container" in html
    assert "tool-call-name" in html
    assert "get_weather" in html
    assert '"city": "NYC"' in html or "city" in html  # JSON formatting

    # Verify labels
    assert "HUMAN:" in html
    assert "AGENT:" in html
    assert "TOOL:" in html


def test_format_multi_turn_conversation_with_multiple_tool_calls():
    """Test formatting AI message with multiple tool calls"""
    conversation = [
        {"content": "Check weather and time", "type": "human"},
        {
            "content": "",
            "type": "agent",
            "tool_calls": [
                {"name": "get_weather", "args": {"city": "NYC"}},
                {"name": "get_time", "args": {"city": "NYC"}},
            ],
        },
    ]

    html = _format_multi_turn_conversation(conversation)

    # Should have multiple tool call boxes
    assert html.count("tool-call-name") == 2
    assert "get_weather" in html
    assert "get_time" in html


def test_prepare_chart_data_with_tool_calls(tmp_path):
    """Test prepare_chart_data handles tool calls in turns"""
    test_file = tmp_path / "tool_calls.json"

    experiment_data = {
        "scenarios": [
            {
                "name": "scenario_1",
                "id": "scenario_1",
                "trace_id": "trace1",
                "steps": [
                    {
                        "input": "Test with tool calls",
                        "id": "step_1",
                        "turns": [
                            {"content": "test", "type": "human"},
                            {"content": "", "type": "agent", "tool_calls": [{"name": "tool1", "args": {}}]},
                        ],
                        "evaluations": [{"metric": {"metric_name": "metric1"}, "result": {"score": 0.85}}],
                    }
                ],
            }
        ]
    }

    with open(test_file, "w") as f:
        json.dump(experiment_data, f)

    viz_data = load_evaluation_data(str(test_file))
    chart_data = prepare_chart_data(viz_data)

    # Verify sample has is_multi_turn and formatted HTML
    assert len(chart_data["samples"]) == 1
    sample = chart_data["samples"][0]
    assert sample["is_multi_turn"] is True
    assert "tool-call" in sample["user_input_formatted"]
