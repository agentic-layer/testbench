## Detailed Usage

### 1. setup.py - Dataset Preparation

Downloads and converts test datasets to RAGAS-native JSONL format.

**Syntax:**

```shell
python3 scripts/setup.py <dataset_url>
```

**Arguments:**

- `dataset_url` (required): URL to dataset file (`.csv`, `.json`, or `.parquet`)

**Required Dataset Schema:**

- See [Dataset Requirements](#dataset-requirements)

**Output:**

- `data/datasets/ragas_dataset.jsonl` - RAGAS Dataset in JSONL format

---

### 2. run.py - Agent Query Execution

Executes test queries through an agent using the A2A protocol and collects responses.

**Syntax:**

```shell
python3 scripts/run.py <agent_url>
```

**Arguments:**

- `agent_url` (required): URL to the agent's A2A endpoint

**Input:**

- `data/datasets/ragas_dataset.jsonl` (loaded automatically)

**Output:**

- `data/experiments/ragas_experiment.jsonl` - Agent responses with preserved context

**Output Schema:**

```jsonl
{"user_input": "What is X?", "retrieved_contexts": ["Context about X"], "reference": "X is...", "response": "Agent's answer"}
```

**Notes:**

- Uses asynchronous A2A client for efficient communication
- Preserves all original dataset fields
- Automatically handles response streaming

---

### 3. evaluate.py - RAGAS Metric Evaluation

Evaluates agent responses using configurable RAGAS metrics and calculates costs.

**Syntax:**

```shell
python3 scripts/evaluate.py <model> <metric1> [metric2 ...] [--cost-per-input COST] [--cost-per-output COST]
```

**Arguments:**

- `model` (required): Model name for evaluation (e.g., `gemini-2.5-flash-lite`, `gpt-4`)
- `metrics` (required): One or more RAGAS metric names
- `--cost-per-input` (optional): Cost per input token (default: 0.000005, i.e., $5 per 1M tokens)
- `--cost-per-output` (optional): Cost per output token (default: 0.000015, i.e., $15 per 1M tokens)

### **Available Metrics:**

| Metric                                    | Special required columns |
|-------------------------------------------|--------------------------|
| `faithfulness`                            | retrieved_contexts       |
| `context_precision`                       | retrieved_contexts       |
| `context_recall`                          | retrieved_contexts       |
| `context_entity_recall`                   | retrieved_contexts       |
| `context_utilization`                     | retrieved_contexts       |
| `llm_context_precision_with_reference`    | retrieved_contexts       |
| `llm_context_precision_without_reference` | retrieved_contexts       |
| `faithful_rate`                           | retrieved_contexts       |
| `relevance_rate`                          | retrieved_contexts       |
| `noise_sensitivity`                       | retrieved_contexts       |
| `factual_correctness`                     |                          |
| `domain_specific_rubrics`                 |                          |
| `nv_accuracy`                             |                          |
| `nv_context_relevance`                    | retrieved_contexts       |
| `nv_response_groundedness`                | retrieved_contexts       |
| `string_present`                          |                          |
| `exact_match`                             |                          |
| `summary_score`                           | reference_contexts       |
| `llm_sql_equivalence_with_reference`      | reference_contexts       |

**Input:**

- `data/experiments/ragas_experiment.jsonl` (loaded automatically)

**Examples:**

```shell
# Single metric
python3 scripts/evaluate.py gemini-2.5-flash-lite faithfulness

# Multiple metrics
python3 scripts/evaluate.py gemini-2.5-flash-lite faithfulness answer_relevancy context_precision

# Custom token costs
python3 scripts/evaluate.py gpt-4 faithfulness answer_correctness \
  --cost-per-input 0.00003 \
  --cost-per-output 0.00006
```

**Output:**

- `results/evaluation_scores.json` - Evaluation results with metrics, token usage, and costs

**Output Format:**

```json
{
  "overall_scores": {
    "faithfulness": 0.95,
    "answer_relevancy": 0.98
  },
  "individual_results": [
    {
      "user_input": "What is the capital of France?",
      "response": "Paris is the capital of France.",
      "faithfulness": 0.95,
      "answer_relevancy": 0.98
    }
  ],
  "total_tokens": {
    "input_tokens": 1500,
    "output_tokens": 500
  },
  "total_cost": 0.015
}
```

**Notes:**

- Currently only support **SingleTurnSample** Metrics (see [Available Metrics](#available-metrics))
- Dynamically discovers available metrics from `ragas.metrics` module
- Invalid metric names will show available options
- Token costs can be customized per model pricing

---

### 4. publish.py - Metrics Publishing

Publishes evaluation metrics to an OpenTelemetry OTLP endpoint for monitoring.

**Syntax:**

```shell
OTEL_EXPORTER_OTLP_ENDPOINT=<endpoint_url> python3 scripts/publish.py <workflow_name> <execution_id> <execution_number>
```

**Arguments:**

- `workflow_name` (required): Name of the test workflow (used as metric label)
- `execution_id` (required): Testkube execution ID for this workflow run
- `execution_number` (required): Numeric execution number for this workflow run (used as X-axis in Grafana)

**Environment Variables:**

- `OTEL_EXPORTER_OTLP_ENDPOINT` (optional): OTLP HTTP endpoint URL (default: `http://localhost:4318`)

**Input:**

- `results/evaluation_scores.json` (loaded automatically)

**Published Metrics:**

Three gauge types are published to the OTLP endpoint:

| Gauge Name | Description | Attributes |
|------------|-------------|------------|
| `testbench_evaluation_metric` | Per-sample evaluation scores | `name`, `workflow_name`, `execution_id`, `execution_number`, `trace_id`, `user_input_hash`, `user_input_truncated` |
| `testbench_evaluation_token_usage` | Token counts from evaluation | `type` (input_tokens/output_tokens), `workflow_name`, `execution_id`, `execution_number` |
| `testbench_evaluation_cost` | Total evaluation cost in USD | `workflow_name`, `execution_id`, `execution_number` |

**Attribute Details:**

- `user_input_hash`: 12-character SHA256 hash of the user input for stable identification across executions
- `user_input_truncated`: First 50 characters of the user input with "..." suffix (for display in Grafana legends)

**Example output:**

```
testbench_evaluation_metric{name="faithfulness", workflow_name="weather-eval", execution_id="exec-123", execution_number=1, trace_id="abc123...", user_input_hash="a1b2c3d4e5f6", user_input_truncated="What is the weather like in New York?"} = 0.85
testbench_evaluation_metric{name="context_recall", workflow_name="weather-eval", execution_id="exec-123", execution_number=1, trace_id="abc123...", user_input_hash="a1b2c3d4e5f6", user_input_truncated="What is the weather like in New York?"} = 1.0
testbench_evaluation_token_usage{type="input_tokens", workflow_name="weather-eval", execution_id="exec-123", execution_number=1} = 1500
testbench_evaluation_token_usage{type="output_tokens", workflow_name="weather-eval", execution_id="exec-123", execution_number=1} = 500
testbench_evaluation_cost{workflow_name="weather-eval", execution_id="exec-123", execution_number=1} = 0.015
```

**Notes:**

- Sends metrics to `/v1/metrics` endpoint
- Uses resource with `service.name="ragas-evaluation"`
- The `trace_id` attribute links metrics to distributed traces for debugging
- Forces flush to ensure delivery before exit


----

## Troubleshooting

### "Source dataset is missing required columns"

**Problem**: Dataset doesn't have the required schema.

**Solution**:

- Verify your dataset has columns: `user_input`, `retrieved_contexts`, and `reference`
- Check that column names match exactly (case-sensitive)
- Ensure `retrieved_contexts` is formatted as a list (see Dataset Requirements)

Example fix for CSV:

```csv
# Wrong (missing columns)
question,context,answer

# Correct
user_input,retrieved_contexts,reference
```

### "No results found in experiment"

**Problem**: `evaluate.py` can't find experiment results.

**Solution**:

- Check if `data/experiments/ragas_experiment.jsonl` exists
- Verify `run.py` completed successfully without errors
- Ensure the agent URL was accessible during execution
- Check file permissions on the `data/` directory

### CSV List Conversion Issues

**Problem**: `retrieved_contexts` not parsing correctly from CSV.

**Solution**:

- Ensure lists are formatted as Python array strings: `"['item1', 'item2']"`
- Use proper quoting in CSV: wrap the entire array string in double quotes
- Consider using JSON or Parquet format for complex data types

Example:

```csv
user_input,retrieved_contexts,reference
"What is X?","['Context about X', 'More context']","X is..."
```

### Evaluation Metrics Fail

**Problem**: Certain metrics fail during evaluation.

**Solution**:

- Some metrics require the `reference` field (e.g., `context_precision`, `context_recall`)
- Verify your dataset includes all required fields for the metrics you're using
- Check the RAGAS documentation for metric-specific requirements

----
