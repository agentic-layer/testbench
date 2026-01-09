# Agentic Layer Test Bench - Automated Agent Evaluation System

A **Kubernetes** native, automated evaluation and testing system for AI agents based on **Testkube** and using the **RAGAS**
framework. This system downloads test datasets, executes queries through agents via the **A2A** protocol, evaluates
responses using configurable metrics, and publishes results to **OpenTelemetry** for monitoring.

----

## Overview

This project provides a complete pipeline for evaluating AI agent performance:

- **Cloud-Native**: Easily deployable to your Kubernetes cluster
- **Local Support**: Test and evaluate agents locally
- **Automated Testing**: Run predefined test queries through your agents
- **Multi-Format Support**: Support for datasets in CSV, JSON & Parquet formats
- **Flexible Evaluation**: Evaluate agent replies using Ragas Metrics
- **Observability**: Publish metrics to OpenTelemetry endpoints for monitoring and analysis

### Example Output:

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
----

## Table of Contents

- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
  - [Setup with Testkube](#setup-with-testkube)
  - [Local Setup](#local-setup)
- [Detailed Usage & Troubleshooting](#detailed-usage--troubleshooting)
- [Dataset Requirements](#dataset-requirements)
- [Testing](#testing)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

----

## Architecture

```
Input Dataset (user_input, retrieved_contexts, reference)
        |
        v
 [1. setup.py] - Downloads & converts to RAGAS JSONL format
        |
        v
data/datasets/ragas_dataset.jsonl
        |
        v
 [2. run.py] - Executes queries via A2A protocol, adds responses
        |              ^
        |              |
        |         Agent URL
        v
data/experiments/ragas_experiment.jsonl
        |
        v
 [3. evaluate.py] - Calculates RAGAS metrics
        |              ^
        |              |
        |         LLM Model
        v
data/results/evaluation_scores.json
        |
        v
 [4. publish.py] - Publishes to OTLP endpoint
        |
        v
OpenTelemetry Collector
```

----

## Prerequisites

### Setup with Testkube

- **Testkube CLI**
- **Kubernetes Cluster**: either cloud-deployed or locally (e.g. kind)
- **Docker**
- **API Key**: `GOOGLE_API_KEY` environment variable
- **OTLP Endpoint**: Optional, defaults to `localhost:4318`

### Local Setup

- **Python 3.13+**
- **API Key**: `GOOGLE_API_KEY` environment variable
- **OTLP Endpoint**: Optional, defaults to `localhost:4318`

----

## Getting Started

1. Create a `.env` file in the root directory
2. Set the `GOOGLE_API_KEY=` variable in the `.env`
3. Use Tilt to spin up all the required backends:

```shell
# Start Tilt in the project root to set up the local Kubernetes environment:
tilt up
```

### Setup with Testkube

Run the RAGAS evaluation workflow with minimal setup:

```shell
kubectl testkube run testworkflow ragas-evaluation-workflow \
    --config datasetUrl="http://data-server.data-server:8000/dataset.csv" \
    --config agentUrl="http://agent-gateway-krakend.agent-gateway-krakend:10000/weather-agent" \
    --config metrics="nv_accuracy context_recall" \
    --config image="ghcr.io/agentic-layer/testbench/testworkflows:latest" \
    --config otlpEndpoint="http://lgtm.monitoring:4318" \
    -n testkube
```

Run the RAGAS evaluation workflow with all optional parameters:

```shell
kubectl testkube run testworkflow ragas-evaluation-workflow \
    --config datasetUrl="http://data-server.data-server:8000/dataset.csv" \
    --config agentUrl="http://agent-gateway-krakend.agent-gateway-krakend:10000/weather-agent" \
    --config metrics="nv_accuracy context_recall" \
    --config image="ghcr.io/agentic-layer/testbench/testworkflows:latest" \
    --config model="gemini/gemini-2.5-flash" \
    --config otlpEndpoint="http://otlp-endpoint:4093" \
    -n testkube
```

### Local Setup

#### Dependencies & Environment Setup

```shell
# Install dependencies with uv
uv sync

# Required for evaluation - routes requests through our AI Gateway
export OPENAI_API_BASE="http://localhost:11001"
export OPENAI_API_KEY="dummy-key-for-litellm"
```

#### Run the complete evaluation pipeline in 4 steps:

```shell
# 1. Download and prepare dataset
uv run python3 scripts/setup.py "http://localhost:11020/dataset.csv"

# 2. Execute queries through your agent
uv run python3 scripts/run.py "http://localhost:11010"

# 3. Evaluate responses with RAGAS metrics
uv run python3 scripts/evaluate.py gemini-2.5-flash-lite faithfulness answer_relevancy

# 4. Publish metrics to OpenTelemetry (workflow_name, execution_id, execution_number)
# Set OTLP endpoint via environment variable (defaults to http://localhost:4318 if not set)
OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318" uv run python3 scripts/publish.py "my-agent-evaluation" "local-exec-001" 1
```

----

## Detailed Usage & Troubleshooting

See [Detailed Usage & Troubleshooting](DetailedUsageAndTroubleshooting.md)

----

## Dataset Requirements

### Schema

Your input dataset must contain these columns:

```
{
    "user_input": str,  # Test question/prompt
    "retrieved_contexts": [str],  # List of context strings (must be array type) (Optional but required by many metrics)
    "reference": str  # Ground truth answer
}
```

### Format-Specific Notes

**CSV Files:**

- `retrieved_contexts` must be formatted as quoted array strings
- Example: `"['Context 1', 'Context 2', 'Context 3']"`
- The system automatically parses these strings into Python lists

**JSON Files:**

```json
[
  {
    "user_input": "What is the capital of France?",
    "retrieved_contexts": [
      "Paris is a city in France.",
      "France is in Europe."
    ],
    "reference": "Paris"
  }
]
```

**Parquet Files:**

- Use native list/array columns for `retrieved_contexts`

### Example Dataset

```csv
user_input,retrieved_contexts,reference
"What is Python?","['Python is a programming language', 'Python was created by Guido van Rossum']","Python is a high-level programming language"
"What is AI?","['AI stands for Artificial Intelligence', 'AI systems can learn from data']","AI is the simulation of human intelligence by machines"
```

----

## Testing

### Unit Tests

Run all unit tests:

```shell
uv run poe test
```

### End-to-End Tests

The E2E Test (found at `tests_e2e/test_e2e.py`) runs a complete pipeline integration test - from setup.py to publish.py.
The E2E Test can be run using the `poe` task runner:

```shell
uv run poe test_e2e
```

To use custom endpoints, evaluation models or metrics you can set the following environment variables before running the E2E Test:

**Configuration via Environment Variables:**

```shell
export E2E_DATASET_URL="http://data-server.data-server:8000/dataset.csv"
export E2E_AGENT_URL="http://agent-gateway-krakend.agent-gateway-krakend:10000/weather-agent"
export E2E_MODEL="gemini-2.5-flash-lite"
export E2E_METRICS="faithfulness,answer_relevancy"
export E2E_WORKFLOW_NAME="Test Workflow"
export E2E_OTLP_ENDPOINT="localhost:4318"

uv run pytest tests_e2e/test_e2e.py -v
```

----

## Development

### Deployment Structure

```
deploy/
  base/                    # Shared resources for all environments
    templates/             # Testkube TestWorkflowTemplates
    grafana-dashboards/    # Dashboard ConfigMaps (auto-discovered via grafana_dashboard label)
  local/                   # Local Tilt environment (uses LGTM all-in-one)
  dev/                     # Dev cluster environment (uses Grafana sidecar for dashboard discovery)
```


## Code Quality Standards

### Code Style:

- **Linting**: Ruff with 120 character line limit
- **Type Checking**: mypy for static type analysis
- **Security**: Bandit for security vulnerability detection
- **Import Organization**: import-linter for dependency management

### Development Commands:

This project uses `poethepoet` for task automation:

```shell
# Run all quality checks
uv run poe check

# Individual checks
uv run poe mypy          # Type checking
uv run poe ruff          # Linting and formatting
uv run poe bandit        # Security analysis
uv run poe lint-imports  # Import dependency validation
uv run poe test          # Execute test suite
uv run poe test_e2e      # Execute end-to-end tests

# Auto-formatting
uv run poe format        # Code formatting
uv run poe lint          # Auto-fix linting issues
```

----

## Contributing

See [Contribution Guide](https://github.com/agentic-layer/testbench?tab=contributing-ov-file) for details on
contribution, and the process for submitting pull requests.
