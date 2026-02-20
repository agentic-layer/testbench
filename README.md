# Testbench — Automated Agent Evaluation

Evaluate AI agents using configurable metrics, publish scores via OpenTelemetry, and visualize results — all orchestrated on Kubernetes with Testkube.

- **Pluggable metrics framework** — generic adapter architecture with RAGAS as the default
- **OpenTelemetry publishing** — per-step evaluation scores pushed via OTLP for Grafana dashboards
- **HTML reports** — self-contained dashboards with charts, distributions, and detailed results tables
- **Kubernetes-native** — Testkube TestWorkflowTemplates with a Helm chart for deployment

---

## Quick Start

You have an agent running locally. Here's how to evaluate it.

### Prerequisites

- **Python 3.12+** and [uv](https://docs.astral.sh/uv/)
- **Kubernetes cluster** (e.g. kind) with [Tilt](https://tilt.dev/)
- **`GOOGLE_API_KEY`** — required for LLM-as-a-judge evaluation via Gemini models

### 1. Install dependencies

```shell
uv sync
```

### 2. Start local infrastructure

Create a `.env` file in the project root with your API key:

```shell
GOOGLE_API_KEY=your-api-key
```

Then start the Tilt environment (AI Gateway, OTLP collector, sample agents, MinIO, Testkube):

```shell
tilt up
```

### 3. Set environment variables

```shell
export OPENAI_API_BASE="http://localhost:11001"
```

### 4. Run the evaluation pipeline

```shell
# Phase 1: Download dataset from S3/MinIO and convert to Experiment JSON
uv run python3 scripts/setup.py "testbench" "dataset.csv"

# Phase 2: Execute queries through agent via A2A protocol
uv run python3 scripts/run.py "http://localhost:11010" "my-workflow"

# Phase 3: Evaluate responses using LLM-as-a-judge metrics
uv run python3 scripts/evaluate.py --model gemini-2.5-flash-lite

# Phase 4: Publish evaluation scores to OTLP endpoint
OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318" \
  uv run python3 scripts/publish.py "my-workflow" "local-exec-001" 1

# Optional: Generate HTML visualization report
uv run python3 scripts/visualize.py "my-workflow" "local-exec-001" 1
```

---

## Architecture

```
Dataset in S3/MinIO
        |
        v
 [1. setup.py] — Download
        |
        v
 data/datasets/experiment.json
        |
        v
 [2. run.py] — Execute queries via A2A protocol
        |              ^
        |              |
        |         Agent URL
        v
 data/experiments/executed_experiment.json
        |
        v
 [3. evaluate.py] — Calculate metrics (LLM-as-a-judge)
        |              ^
        |              |
        |         LLM Model
        v
 data/experiments/evaluated_experiment.json
        |
        ├──→ [4. publish.py] — Push scores via OTLP
        |         |
        |         v
        |    OpenTelemetry Collector → Grafana
        |
        └──→ [5. visualize.py] — Generate HTML dashboard (optional)
                  |
                  v
             data/results/evaluation_report.html
```

Each phase reads the output of the previous phase from the `data/` directory. In Kubernetes, all phases share the same `emptyDir` volume.

---

## Pipeline Phases

### Phase 1: Setup

Downloads a dataset from S3/MinIO.

```
python3 scripts/setup.py <bucket> <key>
```

| Argument | Description |
|----------|-------------|
| `bucket` | S3/MinIO bucket name |
| `key` | Object key (path to `.csv`, `.json`, or `.parquet` file) |

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `MINIO_ENDPOINT` | `http://testkube-minio-service-testkube.testkube:9000` | S3/MinIO endpoint URL |
| `MINIO_ROOT_USER` | `minio` | Access key |
| `MINIO_ROOT_PASSWORD` | `minio123` | Secret key |

**Output:** `data/datasets/experiment.json`

### Phase 2: Run

Sends each step's input to an agent via the A2A protocol and records the responses.

```
python3 scripts/run.py <url> [workflow_name] [--input PATH]
```

| Argument | Description |
|----------|-------------|
| `url` | A2A agent endpoint URL |
| `workflow_name` | Workflow name for OTel labeling (default: `local-test`) |
| `--input` | Path to experiment JSON (default: `data/datasets/experiment.json`) |

**Output:** `data/experiments/executed_experiment.json`

### Phase 3: Evaluate

Calculates metrics for each step using the generic metrics framework (RAGAS adapter by default). Metrics are defined per-step in the experiment JSON via `Metric` objects.

```
python3 scripts/evaluate.py [--model MODEL] [--input PATH] [--output PATH]
```

| Argument | Description |
|----------|-------------|
| `--model` | LLM model for evaluation (overrides experiment's `llm_as_a_judge_model`) |
| `--input` | Path to executed experiment JSON (default: `data/experiments/executed_experiment.json`) |
| `--output` | Path for output (default: `data/experiments/evaluated_experiment.json`) |

**Environment variables:**

| Variable | Description |
|----------|-------------|
| `OPENAI_API_BASE` | AI Gateway endpoint for LLM access (e.g. `http://localhost:11001`) |

**Output:** `data/experiments/evaluated_experiment.json`

### Phase 4: Publish

Publishes per-step evaluation scores as OpenTelemetry gauge metrics.

```
python3 scripts/publish.py <workflow_name> <execution_id> <execution_number> [--input PATH]
```

| Argument | Description |
|----------|-------------|
| `workflow_name` | Name of the test workflow |
| `execution_id` | Testkube execution ID |
| `execution_number` | Testkube execution number |
| `--input` | Path to evaluated experiment JSON (default: `data/experiments/evaluated_experiment.json`) |

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP collector endpoint |

### Phase 5: Visualize (optional)

Generates a self-contained HTML dashboard with summary cards, bar charts, metric distributions, and a detailed results table.

```
python3 scripts/visualize.py <workflow_name> <execution_id> <execution_number> [--input PATH] [--output PATH]
```

| Argument | Description |
|----------|-------------|
| `workflow_name` | Name of the test workflow |
| `execution_id` | Testkube execution ID |
| `execution_number` | Testkube execution number |
| `--input` | Path to evaluated experiment JSON (default: `data/experiments/evaluated_experiment.json`) |
| `--output` | Path for output HTML (default: `data/results/evaluation_report.html`) |

---

## Dataset Format

The pipeline input is an **Experiment JSON** file following the schema defined in [`scripts/schema/experiment.schema.json`](scripts/schema/experiment.schema.json).

### Experiment structure

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `llm_as_a_judge_model` | `string` | No | LLM used to grade responses (e.g., `gpt-4o`, `gemini-2.5-flash-lite`) |
| `default_threshold` | `number` | No | Fallback pass/fail threshold for all metrics (default: `0.9`) |
| `scenarios` | `array` | Yes | List of test scenarios |

### Scenario

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | Yes | Name of the test scenario |
| `steps` | `array` | Yes | List of steps within the scenario |

### Step

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `input` | `string` | Yes | User input to the agent at this step |
| `reference` | `object` | No | Expected reference data for evaluation (see below) |
| `custom_values` | `object` | No | Additional key-value pairs (e.g., `retrieved_contexts` for RAG) |
| `metrics` | `array` | No | List of metric configurations to evaluate this step |

### Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `response` | `string` | No | Expected final response from the agent |
| `tool_calls` | `array` | No | Expected tool calls (`{name, args}`) the agent should make |
| `topics` | `array[string]` | No | Expected topics that should be covered in the response |

### Metric

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metric_name` | `string` | Yes | Registry ID (e.g., `ragas_faithfulness`, `tool_check`) |
| `threshold` | `number` | No | Minimum acceptable score (0.0–1.0), overrides `default_threshold` |
| `parameters` | `object` | No | Arguments passed to the metric adapter |

### Example

```json
{
  "llm_as_a_judge_model": "gemini-2.5-flash-lite",
  "default_threshold": 0.9,
  "scenarios": [
    {
      "name": "weather-qa",
      "steps": [
        {
          "input": "What is the weather like in New York right now?",
          "reference": {
            "response": "The current weather in New York is sunny and 72°F.",
            "tool_calls": [
              {"name": "get_weather", "args": {"city": "New York"}}
            ]
          },
          "custom_values": {
            "retrieved_contexts": ["New York is a city in the United States."]
          },
          "metrics": [
            {"metric_name": "ragas_faithfulness", "threshold": 0.8},
            {"metric_name": "tool_check"}
          ]
        }
      ]
    }
  ]
}
```

---

## Example Output

After evaluation, the `EvaluatedExperiment` JSON contains per-step scores:

```json
{
  "scenarios": [
    {
      "name": "dataset",
      "steps": [
        {
          "input": "What is the capital of France?",
          "evaluations": [
            {
              "metric": {
                "metric_name": "faithfulness",
                "threshold": 0.8
              },
              "result": {
                "result": "pass",
                "score": 0.95
              }
            },
            {
              "metric": {
                "metric_name": "answer_relevancy",
                "threshold": 0.8
              },
              "result": {
                "result": "pass",
                "score": 0.92
              }
            }
          ]
        }
      ]
    }
  ]
}
```

The HTML visualization report includes:
- **Summary cards** — total samples, metrics count, pass rate
- **Overall scores chart** — horizontal bar chart of mean scores per metric
- **Metric distributions** — histograms with min/max/mean/median statistics
- **Detailed results table** — searchable, with per-metric pass/fail badges and score coloring
- **Multi-turn support** — chat-bubble visualization for conversational datasets

---

## Metrics

Metrics are defined per-step in the experiment JSON via `Metric` objects:

```json
{
  "metrics": [
    {"metric_name": "faithfulness", "threshold": 0.8},
    {"metric_name": "answer_relevancy", "threshold": 0.9, "parameters": {}}
  ]
}
```

The generic metrics framework resolves metrics through the `GenericMetricsRegistry`, which delegates to pluggable `FrameworkAdapter` implementations. RAGAS is the default adapter.

**Common RAGAS metrics:**

| Metric | Required fields |
|--------|----------------|
| `faithfulness` | `user_input`, agent response |
| `answer_relevancy` | `user_input`, agent response |
| `context_recall` | `user_input`, `reference`, `retrieved_contexts` |
| `context_precision` | `user_input`, `reference`, `retrieved_contexts` |

Each metric evaluation produces a score between 0 and 1. Steps pass when `score >= threshold` (default threshold: `0.9`, configurable via `default_threshold` on the experiment or per-metric `threshold`).

---

## Kubernetes Deployment (Testkube)

### Helm chart

The `chart/` directory contains a Helm chart that installs Testkube TestWorkflowTemplates and Grafana dashboards:

```shell
helm install testbench ./chart -n testkube
```

### Running a workflow

```shell
kubectl testkube run testworkflow ragas-evaluation-workflow \
    --config bucket="testbench" \
    --config key="dataset.csv" \
    --config agentUrl="http://weather-agent.sample-agents:8000" \
    --config model="gemini-2.5-flash-lite" \
    -n testkube
```

### Workflow templates

| Template | Phase | Config params |
|----------|-------|---------------|
| `ragas-setup-template` | Setup | `bucket`, `key` |
| `ragas-run-template` | Run | `agentUrl` |
| `ragas-evaluate-template` | Evaluate | `model`, `openApiBasePath` |
| `ragas-publish-template` | Publish | _(uses workflow.name, execution.id, execution.number)_ |
| `ragas-visualize-template` | Visualize | _(uses workflow.name, execution.id, execution.number)_ |

### Monitoring workflow execution

```shell
# Watch workflow execution
kubectl testkube watch testworkflow ragas-evaluation-workflow -n testkube

# Get workflow logs
kubectl testkube logs testworkflow ragas-evaluation-workflow -n testkube
```

---

## Local Development

### Tilt environment

`tilt up` deploys the full development stack:

| Component | Port forward | Description |
|-----------|-------------|-------------|
| AI Gateway (LiteLLM) | `localhost:11001` | LLM access for evaluation |
| Weather Agent | `localhost:11010` | Sample A2A agent for testing |
| Grafana (LGTM) | `localhost:11000` | Observability dashboards |
| OTLP Collector | `localhost:4318` | OpenTelemetry metrics ingestion |

Also deployed: cert-manager, agent-runtime operator, agent-gateway-krakend operator, Testkube, MinIO, and all TestWorkflow templates.

### Environment variables

| Variable | Description |
|----------|-------------|
| `GOOGLE_API_KEY` | Required. API key for Gemini models (set in `.env`) |
| `OPENAI_API_BASE` | AI Gateway endpoint (e.g. `http://localhost:11001`) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector endpoint (default: `http://localhost:4318`) |
| `MINIO_ENDPOINT` | S3/MinIO endpoint URL |
| `MINIO_ROOT_USER` | S3/MinIO access key (default: `minio`) |
| `MINIO_ROOT_PASSWORD` | S3/MinIO secret key (default: `minio123`) |

### Development commands

```shell
uv run poe check       # Run all quality checks (tests, mypy, bandit, ruff)
uv run poe test        # Unit tests
uv run poe test_e2e    # End-to-end tests (requires Tilt)
uv run poe format      # Format with Ruff
uv run poe lint        # Lint and auto-fix with Ruff
uv run poe ruff        # Both format and lint
uv run poe mypy        # Static type checking
uv run poe bandit      # Security vulnerability scanning
```

### Project structure

```
scripts/
  setup.py              # Phase 1: dataset download from S3/MinIO
  run.py                # Phase 2: agent execution via A2A
  evaluate.py           # Phase 3: metric evaluation
  publish.py            # Phase 4: OTLP publishing
  visualize.py          # Phase 5: HTML report generation
  schema/
    models.py           # Pydantic model hierarchy
    runtime.py          # ExperimentRuntime (hook-based iterator)
    a2a_client.py       # A2A SDK wrapper
  metrics/
    protocol.py         # MetricCallable protocol, MetricResult
    adapter.py          # Abstract FrameworkAdapter base class
    registry.py         # GenericMetricsRegistry
    ragas/adapter.py    # RAGAS framework adapter
chart/                  # Helm chart for Testkube templates + Grafana dashboards
deploy/local/           # Local development manifests (agents, datasets, LGTM)
tests/                  # Unit tests
tests_e2e/              # End-to-end tests
```

---

## Testing

### Unit tests

```shell
uv run poe test
```

### End-to-end tests

Requires the Tilt environment running. Runs the complete 4-phase pipeline and validates output files.

```shell
uv run poe test_e2e
```

Configure via environment variables:

```shell
export E2E_DATASET_URL="http://data-server.data-server:8000/dataset.csv"
export E2E_AGENT_URL="http://weather-agent.sample-agents:8000"
export E2E_MODEL="gemini-2.5-flash-lite"
export E2E_WORKFLOW_NAME="Test Workflow"
```

### Code quality

```shell
uv run poe check  # runs: test → mypy → bandit → ruff
```

---

## Contributing

See [Contribution Guide](https://github.com/agentic-layer/testbench?tab=contributing-ov-file) for details on contributing and the process for submitting pull requests.
