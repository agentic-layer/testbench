"""
Unit tests for visualize.py

Tests the HTML visualization generation functionality.
"""

import json
import math

import pytest

from testbench.visualize import (
    VisualizationData,
    _format_multi_turn_conversation,
    _get_score_class,
    _is_multi_turn_conversation,
    _is_valid_metric_value,
    calculate_metric_statistics,
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
        "llm_as_a_judge_model": "gemini-2.5-flash-lite",
        "default_threshold": 0.8,
        "scenarios": [
            {
                "name": "scenario_1",
                "id": "scenario_1",
                "trace_id": "a1b2c3d4e5f6",
                "steps": [
                    {
                        "input": "What is the weather?",
                        "id": "step_1",
                        "reference": {
                            "response": "Expected answer",
                            "tool_calls": [{"name": "get_weather", "args": {"city": "NYC"}}],
                            "topics": ["weather", "forecasting"],
                        },
                        "evaluations": [
                            {
                                "metric": {"metric_name": "faithfulness", "threshold": 0.8},
                                "result": {"score": 0.85, "result": "pass"},
                            },
                            {
                                "metric": {"metric_name": "answer_relevancy", "threshold": 0.9},
                                "result": {
                                    "score": 0.90,
                                    "result": "pass",
                                    "details": {"reason": "Relevant answer"},
                                },
                            },
                            {
                                "metric": {"metric_name": "context_recall", "threshold": 0.85},
                                "result": {"score": 0.80, "result": "fail"},
                            },
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
                            {
                                "metric": {"metric_name": "faithfulness", "threshold": 0.8},
                                "result": {"score": 0.80, "result": "pass"},
                            },
                            {
                                "metric": {"metric_name": "answer_relevancy", "threshold": 0.9},
                                "result": {"score": 0.95, "result": "pass"},
                            },
                            {
                                "metric": {"metric_name": "context_recall", "threshold": 0.85},
                                "result": {"score": 0.85, "result": "pass"},
                            },
                        ],
                        "custom_values": {"response": "It is noon."},
                    }
                ],
            },
        ],
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


@pytest.fixture
def sample_viz_data():
    """Create sample VisualizationData for testing pure functions."""
    return VisualizationData(
        overall_scores={"faithfulness": 0.825, "answer_relevancy": 0.925, "context_recall": 0.825},
        individual_results=[
            {
                "user_input": "What is the weather?",
                "step_id": "step_1",
                "trace_id": "a1b2c3d4e5f6",
                "response": "It is sunny.",
                "faithfulness": 0.85,
                "answer_relevancy": 0.90,
                "context_recall": 0.80,
            },
            {
                "user_input": "What is the time?",
                "step_id": "step_2",
                "trace_id": "b2c3d4e5f6a7",
                "response": "It is noon.",
                "faithfulness": 0.80,
                "answer_relevancy": 0.95,
                "context_recall": 0.85,
            },
        ],
        total_tokens={"input_tokens": 0, "output_tokens": 0},
        total_cost=0.0,
        metric_names=["answer_relevancy", "context_recall", "faithfulness"],
    )


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
def test_prepares_chart_data_structure(sample_viz_data):
    """Test chart data structure is correct"""
    chart_data = prepare_chart_data(sample_viz_data)

    assert "overall_scores" in chart_data
    assert "metric_distributions" in chart_data
    assert "samples" in chart_data
    assert "tokens" in chart_data
    assert "cost" in chart_data


def test_chart_data_has_correct_overall_scores(sample_viz_data):
    """Test overall scores are correctly calculated"""
    chart_data = prepare_chart_data(sample_viz_data)

    assert chart_data["overall_scores"]["faithfulness"] == 0.825  # Mean of 0.85 and 0.80
    assert chart_data["overall_scores"]["answer_relevancy"] == 0.925  # Mean of 0.90 and 0.95


def test_chart_data_has_metric_distributions(sample_viz_data):
    """Test metric distributions are calculated"""
    chart_data = prepare_chart_data(sample_viz_data)

    assert "faithfulness" in chart_data["metric_distributions"]
    assert "values" in chart_data["metric_distributions"]["faithfulness"]
    assert "stats" in chart_data["metric_distributions"]["faithfulness"]


def test_chart_data_has_samples(sample_viz_data):
    """Test samples are prepared correctly"""
    chart_data = prepare_chart_data(sample_viz_data)

    assert len(chart_data["samples"]) == 2
    assert chart_data["samples"][0]["index"] == 1
    assert chart_data["samples"][0]["user_input"] == "What is the weather?"
    assert "metrics" in chart_data["samples"][0]


def test_handles_empty_individual_results():
    """Test handling of empty individual results"""
    empty_viz_data = VisualizationData(
        overall_scores={},
        individual_results=[],
        total_tokens={"input_tokens": 0, "output_tokens": 0},
        total_cost=0.0,
        metric_names=[],
    )
    chart_data = prepare_chart_data(empty_viz_data)

    assert chart_data["samples"] == []
    assert chart_data["metric_distributions"] == {}
    assert chart_data["overall_scores"] == {}


def test_handles_missing_trace_ids():
    """Test handling of missing trace_ids"""
    viz_data = VisualizationData(
        overall_scores={"metric1": 0.5},
        individual_results=[
            {
                "user_input": "test",
                "step_id": "step_1",
                "trace_id": "",
                "metric1": 0.5,
            }
        ],
        total_tokens={"input_tokens": 0, "output_tokens": 0},
        total_cost=0.0,
        metric_names=["metric1"],
    )
    chart_data = prepare_chart_data(viz_data)

    # Empty string trace_id is falsy, so it gets replaced
    assert chart_data["samples"][0]["trace_id"] == "missing-trace-0"


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


# Test HTML generation (via main, which now uses ReportGenerator)
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
    assert "Experiment: weather-agent" in html_content
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
    assert '<div class="message agent">' in html
    assert "HUMAN:" in html
    assert "AGENT:" in html
    assert "What is the weather?" in html
    assert "It is sunny." in html


def test_prepare_chart_data_with_multi_turn():
    """Test chart data preparation with multi-turn conversations"""
    viz_data = VisualizationData(
        overall_scores={"metric1": 0.5},
        individual_results=[
            {
                "user_input": "Multi-turn conversation",
                "step_id": "step_1",
                "trace_id": "abc123",
                "turns": [
                    {"content": "Hello", "type": "human"},
                    {"content": "Hi", "type": "agent"},
                ],
                "metric1": 0.5,
            }
        ],
        total_tokens={"input_tokens": 0, "output_tokens": 0},
        total_cost=0.0,
        metric_names=["metric1"],
    )
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
    assert '<div class="message agent">' in html

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


def test_prepare_chart_data_with_tool_calls():
    """Test prepare_chart_data handles tool calls in turns"""
    viz_data = VisualizationData(
        overall_scores={"metric1": 0.85},
        individual_results=[
            {
                "user_input": "Test with tool calls",
                "step_id": "step_1",
                "trace_id": "trace1",
                "turns": [
                    {"content": "test", "type": "human"},
                    {"content": "", "type": "agent", "tool_calls": [{"name": "tool1", "args": {}}]},
                ],
                "metric1": 0.85,
            }
        ],
        total_tokens={"input_tokens": 0, "output_tokens": 0},
        total_cost=0.0,
        metric_names=["metric1"],
    )
    chart_data = prepare_chart_data(viz_data)

    # Verify sample has is_multi_turn and formatted HTML
    assert len(chart_data["samples"]) == 1
    sample = chart_data["samples"][0]
    assert sample["is_multi_turn"] is True
    assert "tool-call" in sample["user_input_formatted"]


# Test _get_score_class with threshold parameter
def test_get_score_class_with_threshold_high():
    """Test high score with custom threshold"""
    assert _get_score_class(0.9, threshold=0.9) == "high"
    assert _get_score_class(1.0, threshold=0.8) == "high"


def test_get_score_class_with_threshold_medium():
    """Test medium score with custom threshold"""
    # threshold=0.8 → medium boundary = 0.8 * 0.75 ≈ 0.6
    assert _get_score_class(0.7, threshold=0.8) == "medium"
    assert _get_score_class(0.65, threshold=0.8) == "medium"


def test_get_score_class_with_threshold_low():
    """Test low score with custom threshold"""
    # threshold=0.8 → medium boundary = 0.6, so below that is low
    assert _get_score_class(0.5, threshold=0.8) == "low"
    assert _get_score_class(0.0, threshold=0.8) == "low"


# Test pass rate card
def test_html_contains_pass_rate_card(evaluated_experiment_file, tmp_path):
    """Test pass rate card is present when pass/fail data exists"""
    output_file = tmp_path / "report.html"

    main(str(evaluated_experiment_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert "Pass Rate" in html_content
    assert "passed" in html_content
    assert "failed" in html_content


# Test scenario group headers
def test_html_contains_scenario_headers(evaluated_experiment_file, tmp_path):
    """Test scenario group headers appear in the results table"""
    output_file = tmp_path / "report.html"

    main(str(evaluated_experiment_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert "scenario-header" in html_content
    assert "scenario_1" in html_content
    assert "scenario_2" in html_content


# Test reference details (tool_calls and topics)
def test_html_contains_reference_details(evaluated_experiment_file, tmp_path):
    """Test reference tool_calls and topics appear in the report"""
    output_file = tmp_path / "report.html"

    main(str(evaluated_experiment_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert "reference-details" in html_content
    assert "Expected tool calls" in html_content
    assert "get_weather" in html_content
    assert "Expected topics" in html_content
    assert "weather" in html_content
    assert "forecasting" in html_content


# Test llm_as_a_judge_model in header
def test_html_contains_llm_model_in_header(evaluated_experiment_file, tmp_path):
    """Test llm_as_a_judge_model appears in the report header"""
    output_file = tmp_path / "report.html"

    main(str(evaluated_experiment_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert "LLM-as-a-Judge Model" in html_content
    assert "gemini-2.5-flash-lite" in html_content


# Test pass/fail badges in metric cells
def test_html_contains_pass_fail_badges(evaluated_experiment_file, tmp_path):
    """Test pass/fail badges appear in metric cells"""
    output_file = tmp_path / "report.html"

    main(str(evaluated_experiment_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert 'class="badge pass"' in html_content
    assert 'class="badge fail"' in html_content
    assert "PASS" in html_content
    assert "FAIL" in html_content


# Test eval details collapsible
def test_html_contains_eval_details(evaluated_experiment_file, tmp_path):
    """Test evaluation details appear as collapsible sections"""
    output_file = tmp_path / "report.html"

    main(str(evaluated_experiment_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert "eval-details" in html_content
    assert "Relevant answer" in html_content
