"""
Unit tests for visualize.py

Tests the HTML visualization generation functionality.
"""

import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

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
def temp_dir():
    """Create a temporary directory for tests"""
    tmp = tempfile.mkdtemp()
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def evaluation_scores_file(temp_dir):
    """Create test evaluation_scores.json file"""
    test_file = Path(temp_dir) / "evaluation_scores.json"
    test_data = {
        "overall_scores": {"faithfulness": 0.85, "answer_relevancy": 0.90, "context_recall": 0.80},
        "individual_results": [
            {
                "user_input": "What is the weather?",
                "response": "It is sunny.",
                "retrieved_contexts": ["Weather context"],
                "reference": "Expected answer",
                "faithfulness": 0.85,
                "answer_relevancy": 0.90,
                "context_recall": 0.80,
                "trace_id": "a1b2c3d4e5f6",
            },
            {
                "user_input": "What is the time?",
                "response": "It is noon.",
                "retrieved_contexts": ["Time context"],
                "reference": "Expected answer",
                "faithfulness": 0.80,
                "answer_relevancy": 0.95,
                "context_recall": 0.85,
                "trace_id": "b2c3d4e5f6a7",
            },
        ],
        "total_tokens": {"input_tokens": 1000, "output_tokens": 200},
        "total_cost": 0.05,
    }

    with open(test_file, "w") as f:
        json.dump(test_data, f)

    return test_file


@pytest.fixture
def empty_evaluation_scores_file(temp_dir):
    """Create evaluation_scores.json with empty results"""
    test_file = Path(temp_dir) / "empty_evaluation_scores.json"
    test_data = {
        "overall_scores": {},
        "individual_results": [],
        "total_tokens": {"input_tokens": 0, "output_tokens": 0},
        "total_cost": 0.0,
    }

    with open(test_file, "w") as f:
        json.dump(test_data, f)

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
def test_loads_evaluation_data(evaluation_scores_file):
    """Test loading evaluation data from JSON"""
    data = load_evaluation_data(str(evaluation_scores_file))

    assert len(data.individual_results) == 2
    assert len(data.metric_names) == 3
    assert "faithfulness" in data.metric_names
    assert "answer_relevancy" in data.metric_names
    assert "context_recall" in data.metric_names
    assert data.total_tokens["input_tokens"] == 1000
    assert data.total_tokens["output_tokens"] == 200
    assert data.total_cost == 0.05
    assert data.overall_scores["faithfulness"] == 0.85


def test_loads_empty_evaluation_data(empty_evaluation_scores_file):
    """Test loading empty evaluation data"""
    data = load_evaluation_data(str(empty_evaluation_scores_file))

    assert len(data.individual_results) == 0
    assert len(data.metric_names) == 0
    assert data.total_tokens["input_tokens"] == 0
    assert data.total_cost == 0.0


def test_file_not_found_error(temp_dir):
    """Test error when file doesn't exist"""
    with pytest.raises(FileNotFoundError):
        load_evaluation_data(str(Path(temp_dir) / "nonexistent.json"))


def test_handles_invalid_json(temp_dir):
    """Test error when file is not valid JSON"""
    invalid_file = Path(temp_dir) / "invalid.json"
    with open(invalid_file, "w") as f:
        f.write("{invalid json content")

    with pytest.raises(json.JSONDecodeError):
        load_evaluation_data(str(invalid_file))


def test_handles_missing_fields(temp_dir):
    """Test error when required fields are missing"""
    invalid_file = Path(temp_dir) / "missing_fields.json"
    with open(invalid_file, "w") as f:
        json.dump({"overall_scores": {}}, f)  # Missing other required fields

    with pytest.raises(ValueError, match="Missing required field"):
        load_evaluation_data(str(invalid_file))


def test_discovers_metric_names_correctly(temp_dir):
    """Test metric name discovery from individual results"""
    test_file = Path(temp_dir) / "test.json"
    test_data = {
        "overall_scores": {"metric1": 0.5},
        "individual_results": [
            {
                "user_input": "test",
                "response": "answer",
                "metric1": 0.5,
                "metric2": 0.7,
                "trace_id": "abc",
            }
        ],
        "total_tokens": {"input_tokens": 0, "output_tokens": 0},
        "total_cost": 0.0,
    }

    with open(test_file, "w") as f:
        json.dump(test_data, f)

    data = load_evaluation_data(str(test_file))
    assert set(data.metric_names) == {"metric1", "metric2"}


def test_filters_reserved_fields_from_metrics(temp_dir):
    """Test that reserved fields are not considered metrics"""
    test_file = Path(temp_dir) / "test.json"
    test_data = {
        "overall_scores": {},
        "individual_results": [
            {
                "user_input": "test",
                "response": "answer",
                "retrieved_contexts": ["context"],
                "reference": "ref",
                "trace_id": "abc",
                "actual_metric": 0.5,
            }
        ],
        "total_tokens": {"input_tokens": 0, "output_tokens": 0},
        "total_cost": 0.0,
    }

    with open(test_file, "w") as f:
        json.dump(test_data, f)

    data = load_evaluation_data(str(test_file))
    assert data.metric_names == ["actual_metric"]
    assert "user_input" not in data.metric_names
    assert "response" not in data.metric_names


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
def test_prepares_chart_data_structure(evaluation_scores_file):
    """Test chart data structure is correct"""
    viz_data = load_evaluation_data(str(evaluation_scores_file))
    chart_data = prepare_chart_data(viz_data)

    assert "overall_scores" in chart_data
    assert "metric_distributions" in chart_data
    assert "samples" in chart_data
    assert "tokens" in chart_data
    assert "cost" in chart_data


def test_chart_data_has_correct_overall_scores(evaluation_scores_file):
    """Test overall scores are correctly transferred"""
    viz_data = load_evaluation_data(str(evaluation_scores_file))
    chart_data = prepare_chart_data(viz_data)

    assert chart_data["overall_scores"]["faithfulness"] == 0.85
    assert chart_data["overall_scores"]["answer_relevancy"] == 0.90


def test_chart_data_has_metric_distributions(evaluation_scores_file):
    """Test metric distributions are calculated"""
    viz_data = load_evaluation_data(str(evaluation_scores_file))
    chart_data = prepare_chart_data(viz_data)

    assert "faithfulness" in chart_data["metric_distributions"]
    assert "values" in chart_data["metric_distributions"]["faithfulness"]
    assert "stats" in chart_data["metric_distributions"]["faithfulness"]


def test_chart_data_has_samples(evaluation_scores_file):
    """Test samples are prepared correctly"""
    viz_data = load_evaluation_data(str(evaluation_scores_file))
    chart_data = prepare_chart_data(viz_data)

    assert len(chart_data["samples"]) == 2
    assert chart_data["samples"][0]["index"] == 1
    assert chart_data["samples"][0]["user_input"] == "What is the weather?"
    assert "metrics" in chart_data["samples"][0]


def test_handles_empty_individual_results(empty_evaluation_scores_file):
    """Test handling of empty individual results"""
    viz_data = load_evaluation_data(str(empty_evaluation_scores_file))
    chart_data = prepare_chart_data(viz_data)

    assert chart_data["samples"] == []
    assert chart_data["metric_distributions"] == {}
    assert chart_data["overall_scores"] == {}


def test_handles_missing_trace_ids(temp_dir):
    """Test handling of missing trace_ids"""
    test_file = Path(temp_dir) / "no_trace.json"
    test_data = {
        "overall_scores": {"metric1": 0.5},
        "individual_results": [
            {"user_input": "test", "response": "answer", "metric1": 0.5}  # No trace_id
        ],
        "total_tokens": {"input_tokens": 0, "output_tokens": 0},
        "total_cost": 0.0,
    }

    with open(test_file, "w") as f:
        json.dump(test_data, f)

    viz_data = load_evaluation_data(str(test_file))
    chart_data = prepare_chart_data(viz_data)

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


# Test HTML generation
def test_generates_valid_html_file(evaluation_scores_file, temp_dir):
    """Test HTML file is generated with correct structure"""
    output_file = Path(temp_dir) / "report.html"

    main(str(evaluation_scores_file), str(output_file), "test-workflow", "test-exec-001", 1)

    assert output_file.exists()

    # Read and validate HTML structure
    html_content = output_file.read_text()
    assert "<!DOCTYPE html>" in html_content
    assert "test-workflow" in html_content
    assert "chart.js" in html_content  # CDN reference
    assert "overallScoresChart" in html_content  # Chart canvas
    assert "faithfulness" in html_content  # Metric name
    assert "trace_id" in html_content  # Table column


def test_html_contains_all_metrics(evaluation_scores_file, temp_dir):
    """Test all metrics appear in HTML"""
    output_file = Path(temp_dir) / "report.html"

    main(str(evaluation_scores_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert "faithfulness" in html_content
    assert "answer_relevancy" in html_content
    assert "context_recall" in html_content


def test_html_contains_summary_cards(evaluation_scores_file, temp_dir):
    """Test summary cards are generated"""
    output_file = Path(temp_dir) / "report.html"

    main(str(evaluation_scores_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert "Total Samples" in html_content
    assert "Metrics Evaluated" in html_content
    assert "Total Tokens" in html_content
    assert "Total Cost" in html_content


def test_html_contains_timestamp(evaluation_scores_file, temp_dir):
    """Test timestamp is included in HTML"""
    output_file = Path(temp_dir) / "report.html"

    main(str(evaluation_scores_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert "Generated:" in html_content


def test_creates_output_directory(evaluation_scores_file, temp_dir):
    """Test output directory is created if missing"""
    output_file = Path(temp_dir) / "nested" / "dir" / "report.html"

    main(str(evaluation_scores_file), str(output_file), "test-workflow", "test-exec-001", 1)

    assert output_file.exists()
    assert output_file.parent.exists()


def test_html_has_substantial_content(evaluation_scores_file, temp_dir):
    """Test HTML file has substantial content"""
    output_file = Path(temp_dir) / "report.html"

    main(str(evaluation_scores_file), str(output_file), "test-workflow", "test-exec-001", 1)

    assert output_file.stat().st_size > 5000  # Should be at least 5KB


def test_html_with_empty_results(empty_evaluation_scores_file, temp_dir):
    """Test HTML generation with empty results"""
    output_file = Path(temp_dir) / "empty_report.html"

    main(str(empty_evaluation_scores_file), str(output_file), "test-workflow", "test-exec-001", 1)

    assert output_file.exists()
    html_content = output_file.read_text()
    assert "<!DOCTYPE html>" in html_content
    assert "Total Samples" in html_content


# Integration test
def test_end_to_end_html_generation(evaluation_scores_file, temp_dir):
    """Test complete flow from load to HTML generation"""
    output_file = Path(temp_dir) / "final_report.html"

    # Run main function
    main(str(evaluation_scores_file), str(output_file), "end-to-end-workflow", "exec-e2e-001", 5)

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


def test_html_contains_search_functionality(evaluation_scores_file, temp_dir):
    """Test table search functionality is included"""
    output_file = Path(temp_dir) / "report.html"

    main(str(evaluation_scores_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert "searchInput" in html_content
    assert "addEventListener" in html_content


def test_html_contains_chart_initialization(evaluation_scores_file, temp_dir):
    """Test Chart.js initialization code is present"""
    output_file = Path(temp_dir) / "report.html"

    main(str(evaluation_scores_file), str(output_file), "test-workflow", "test-exec-001", 1)

    html_content = output_file.read_text()
    assert "new Chart(" in html_content
    assert "reportData" in html_content


def test_main_with_workflow_metadata(evaluation_scores_file, temp_dir):
    """Test main function with workflow metadata"""
    output_file = Path(temp_dir) / "custom_workflow_report.html"

    main(str(evaluation_scores_file), str(output_file), "custom-workflow", "custom-exec-123", 42)

    html_content = output_file.read_text()
    assert "custom-workflow" in html_content
    assert "custom-exec-123" in html_content
    assert "Execution 42" in html_content


def test_html_displays_workflow_info_section(evaluation_scores_file, temp_dir):
    """Test that workflow information appears in metadata section"""
    output_file = Path(temp_dir) / "workflow_info_report.html"

    main(str(evaluation_scores_file), str(output_file), "weather-agent", "exec-w123", 7)

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
def test_is_multi_turn_conversation_with_list():
    """Test detection of multi-turn conversation"""
    conversation = [
        {"content": "Hello", "type": "human"},
        {"content": "Hi there", "type": "ai"},
    ]
    assert _is_multi_turn_conversation(conversation) is True


def test_is_multi_turn_conversation_with_string():
    """Test single-turn string is not detected as multi-turn"""
    assert _is_multi_turn_conversation("Simple string") is False


def test_is_multi_turn_conversation_with_empty_list():
    """Test empty list is not multi-turn"""
    assert _is_multi_turn_conversation([]) is False


def test_is_multi_turn_conversation_with_invalid_structure():
    """Test list without proper message structure is not multi-turn"""
    assert _is_multi_turn_conversation([{"invalid": "structure"}]) is False


def test_format_multi_turn_conversation():
    """Test formatting of multi-turn conversation"""
    conversation = [
        {"content": "What is the weather?", "type": "human"},
        {"content": "It is sunny.", "type": "ai"},
    ]

    html = _format_multi_turn_conversation(conversation)

    assert '<div class="conversation">' in html
    assert '<div class="message human">' in html
    assert '<div class="message ai">' in html
    assert "HUMAN:" in html
    assert "AI:" in html
    assert "What is the weather?" in html
    assert "It is sunny." in html


def test_prepare_chart_data_with_multi_turn(temp_dir):
    """Test chart data preparation with multi-turn conversations"""
    test_file = Path(temp_dir) / "multi_turn.json"
    test_data = {
        "overall_scores": {"metric1": 0.5},
        "individual_results": [
            {
                "user_input": [
                    {"content": "Hello", "type": "human"},
                    {"content": "Hi", "type": "ai"},
                ],
                "response": "Response",
                "metric1": 0.5,
                "trace_id": "abc123",
            }
        ],
        "total_tokens": {"input_tokens": 100, "output_tokens": 50},
        "total_cost": 0.01,
    }

    with open(test_file, "w") as f:
        json.dump(test_data, f)

    viz_data = load_evaluation_data(str(test_file))
    chart_data = prepare_chart_data(viz_data)

    assert len(chart_data["samples"]) == 1
    sample = chart_data["samples"][0]
    assert sample["is_multi_turn"] is True
    assert "user_input_formatted" in sample
    assert '<div class="conversation">' in sample["user_input_formatted"]


def test_html_with_multi_turn_conversations(temp_dir):
    """Test HTML generation with multi-turn conversations"""
    test_file = Path(temp_dir) / "multi_turn.json"
    output_file = Path(temp_dir) / "multi_turn_report.html"

    test_data = {
        "overall_scores": {"metric1": 0.8},
        "individual_results": [
            {
                "user_input": [
                    {"content": "Question 1", "type": "human"},
                    {"content": "Answer 1", "type": "ai"},
                    {"content": "Question 2", "type": "human"},
                ],
                "response": "Final response",
                "metric1": 0.8,
                "trace_id": "test123",
            }
        ],
        "total_tokens": {"input_tokens": 100, "output_tokens": 50},
        "total_cost": 0.01,
    }

    with open(test_file, "w") as f:
        json.dump(test_data, f)

    main(str(test_file), str(output_file), "multi-turn-workflow", "multi-exec-001", 1)

    html_content = output_file.read_text()
    assert '<div class="conversation">' in html_content
    assert "Question 1" in html_content
    assert "Answer 1" in html_content
    assert "Question 2" in html_content
    assert "HUMAN:" in html_content
    assert "AI:" in html_content


def test_format_multi_turn_conversation_with_tool_calls():
    """Test formatting conversations with tool calls"""
    from visualize import _format_multi_turn_conversation

    conversation = [
        {"content": "What's the weather?", "type": "human"},
        {
            "content": "",
            "type": "ai",
            "tool_calls": [{"name": "get_weather", "args": {"city": "NYC"}}]
        },
        {"content": "{'status': 'success', 'report': 'Sunny, 72F'}", "type": "tool"},
        {"content": "The weather is sunny.", "type": "ai"}
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
    assert "AI:" in html
    assert "TOOL:" in html


def test_format_multi_turn_conversation_with_multiple_tool_calls():
    """Test formatting AI message with multiple tool calls"""
    from visualize import _format_multi_turn_conversation

    conversation = [
        {"content": "Check weather and time", "type": "human"},
        {
            "content": "",
            "type": "ai",
            "tool_calls": [
                {"name": "get_weather", "args": {"city": "NYC"}},
                {"name": "get_time", "args": {"city": "NYC"}}
            ]
        }
    ]

    html = _format_multi_turn_conversation(conversation)

    # Should have multiple tool call boxes
    assert html.count("tool-call-name") == 2
    assert "get_weather" in html
    assert "get_time" in html


def test_prepare_chart_data_with_tool_calls():
    """Test prepare_chart_data handles tool calls in user_input"""
    from visualize import prepare_chart_data, VisualizationData

    viz_data = VisualizationData(
        overall_scores={"metric1": 0.85},
        individual_results=[
            {
                "user_input": [
                    {"content": "test", "type": "human"},
                    {"content": "", "type": "ai", "tool_calls": [{"name": "tool1", "args": {}}]}
                ],
                "response": "",
                "metric1": 0.85,
                "trace_id": "trace1"
            }
        ],
        total_tokens={"input_tokens": 100, "output_tokens": 50},
        total_cost=0.01,
        metric_names=["metric1"]
    )

    chart_data = prepare_chart_data(viz_data)

    # Verify sample has is_multi_turn and formatted HTML
    assert len(chart_data["samples"]) == 1
    sample = chart_data["samples"][0]
    assert sample["is_multi_turn"] is True
    assert "tool-call" in sample["user_input_formatted"]
