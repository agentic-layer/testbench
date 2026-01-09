# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Repository Purpose

Kubernetes-native RAGAS-based agent evaluation system that executes test datasets via A2A protocol and publishes metrics via OTLP. Part of the Agentic Layer platform for automated agent testing and quality assurance.

---

## Common Commands

### Development Workflow

```shell
# Install dependencies
uv sync

# Run all quality checks (tests, mypy, bandit, ruff)
uv run poe check

# Run unit tests only
uv run poe test

# Run end-to-end tests (requires Tilt environment running)
uv run poe test_e2e

# Code formatting and linting
uv run poe format    # Format with Ruff
uv run poe lint      # Lint and auto-fix with Ruff
uv run poe ruff      # Both format and lint

# Type checking and security
uv run poe mypy      # Static type checking
uv run poe bandit    # Security vulnerability scanning
```

### Local Development Environment

```shell
# Start full Kubernetes environment (operators, agents, observability)
tilt up

# Stop environment
tilt down

# Required environment variable for local testing
export OPENAI_API_BASE="http://localhost:11001"  # AI Gateway endpoint
export GOOGLE_API_KEY="your-api-key"            # Required for Gemini models
```

### Running the 4-Phase Pipeline Locally

```shell
# Phase 1: Download and convert dataset to RAGAS format
uv run python3 scripts/setup.py "http://localhost:11020/dataset.csv"

# Phase 2: Execute queries through agent via A2A protocol
uv run python3 scripts/run.py "http://localhost:11010"

# Phase 3: Evaluate responses using RAGAS metrics (uses default config)
uv run python3 scripts/evaluate.py gemini-2.5-flash-lite

# Or specify a custom config
# uv run python3 scripts/evaluate.py gemini-2.5-flash-lite --metrics-config examples/metrics_advanced.json

# Phase 4: Publish metrics to OTLP endpoint (requires execution_id and execution_number)
OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318" uv run python3 scripts/publish.py "workflow-name" "exec-001" 1

# Optional: Generate HTML visualization report (requires workflow metadata)
uv run python3 scripts/visualize.py "weather-assistant-test" "exec-001" 1
```

### HTML Visualization

Generate a comprehensive HTML dashboard from evaluation results for local viewing and sharing.

**BREAKING CHANGE:** visualize.py now requires workflow metadata as mandatory positional arguments (matching publish.py pattern).

```shell
# Basic usage (after running evaluate.py)
uv run python3 scripts/visualize.py weather-assistant-test exec-001 1

# Custom input/output paths
uv run python3 scripts/visualize.py weather-assistant-test exec-001 1 \
  --input data/results/evaluation_scores.json \
  --output reports/exec-001.html

# Complete pipeline example
uv run python3 scripts/evaluate.py gemini-2.5-flash-lite
uv run python3 scripts/visualize.py weather-agent exec-123 5
```

**Required Arguments:**
- `workflow_name` - Name of the test workflow (e.g., 'weather-assistant-test')
- `execution_id` - Testkube execution ID for this workflow run
- `execution_number` - Testkube execution number for this workflow run

**Optional Arguments:**
- `--input` - Path to evaluation_scores.json (default: `data/results/evaluation_scores.json`)
- `--output` - Path for output HTML file (default: `data/results/evaluation_report.html`)

**Features:**
- **Summary Cards**: Total samples, metrics count, token usage, cost
- **Workflow Metadata**: Displays workflow name, execution ID, and execution number
- **Overall Scores Chart**: Horizontal bar chart showing mean score per metric
- **Metric Distributions**: Histograms showing score distributions with statistics
- **Detailed Results Table**: All samples with metrics, searchable and sortable
- **Multi-Turn Support**: Chat-bubble visualization for conversational datasets
- **Self-Contained HTML**: Single file with embedded Chart.js, works offline
- **Responsive Design**: Works on desktop and tablet, print-friendly

**Output:** `data/results/evaluation_report.html` (default)
```

### Metrics Configuration

**BREAKING CHANGE:** Metrics must now be specified via configuration file using `--metrics-config`.

#### Quick Start

**Using Default Config:**
```shell
# Uses examples/metrics_simple.json by default
uv run python3 scripts/evaluate.py gemini-2.5-flash-lite
```

**Using Custom Config:**
```shell
# Simple metrics (pre-configured instances)
uv run python3 scripts/evaluate.py gemini-2.5-flash-lite --metrics-config examples/metrics_simple.json

# Advanced metrics (custom AspectCritic definitions)
uv run python3 scripts/evaluate.py gemini-2.5-flash-lite --metrics-config examples/metrics_advanced.json
```

#### Configuration File Format

Both JSON and YAML formats are supported:

**JSON Example** (`examples/metrics_simple.json`):
```json
{
  "version": "1.0",
  "metrics": [
    {"type": "instance", "name": "faithfulness"},
    {"type": "instance", "name": "answer_relevancy"},
    {"type": "instance", "name": "context_precision"}
  ]
}
```

**Advanced Configuration** (`examples/metrics_advanced.json`):
```json
{
  "version": "1.0",
  "metrics": [
    {
      "type": "instance",
      "name": "faithfulness"
    },
    {
      "type": "class",
      "class_name": "AspectCritic",
      "parameters": {
        "name": "harmfulness",
        "definition": "Does this contain harmful content?"
      }
    }
  ]
}
```

#### Available Metrics

**Pre-configured Instances** (type: `instance`):
- `faithfulness` - Measures factual consistency with contexts
- `answer_relevancy` - Measures relevance of response to query
- `answer_correctness` - Measures correctness vs reference
- `answer_similarity` - Semantic similarity to reference
- `context_precision` - Precision of retrieved contexts
- `context_recall` - Recall of retrieved contexts
- `context_entity_recall` - Entity-level context recall
- `multimodal_faithness` - Faithfulness for multimodal content
- `multimodal_relevance` - Relevance for multimodal content
- `summarization_score` - Quality of summarization

**Configurable Classes** (type: `class`):
- `AspectCritic` - Custom aspect-based evaluation (REQUIRES: `name`, `definition`)
- `Faithfulness` - Configurable faithfulness (OPTIONAL: `strictness`, `max_retries`)
- `AnswerRelevancy` - Configurable relevancy (OPTIONAL: `strictness`)
- Plus 30+ other classes

To see all available metrics:
```shell
uv run python3 scripts/evaluate.py --help
```

#### Migration from Old CLI

Old usage (NO LONGER WORKS):
```shell
# This will fail
uv run python3 scripts/evaluate.py gemini-2.5-flash-lite faithfulness answer_relevancy
```

New usage:
```shell
# Create config file
cat > my_metrics.json << EOF
{
  "version": "1.0",
  "metrics": [
    {"type": "instance", "name": "faithfulness"},
    {"type": "instance", "name": "answer_relevancy"}
  ]
}
EOF

# Use config file
uv run python3 scripts/evaluate.py gemini-2.5-flash-lite --metrics-config my_metrics.json
```

### Testkube Execution

```shell
# Run complete evaluation workflow in Kubernetes
kubectl testkube run testworkflow ragas-evaluation-workflow \
    --config datasetUrl="http://data-server.data-server:8000/dataset.csv" \
    --config agentUrl="http://weather-agent.sample-agents:8000" \
    --config metrics="nv_accuracy context_recall" \
    -n testkube

# Watch workflow execution
kubectl testkube watch testworkflow ragas-evaluation-workflow -n testkube

# Get workflow logs
kubectl testkube logs testworkflow ragas-evaluation-workflow -n testkube
```

### Docker Build

```shell
# Build Docker image locally
make build

# Run container locally
make run
```

---

## Architecture Overview

### 4-Phase Evaluation Pipeline

**Core Concept**: Sequential pipeline where each phase reads input from previous phase's output via shared `/app/data` volume.

**Phase 1: Setup** (`scripts/setup.py`)
- **Input**: Dataset URL (CSV, JSON, or Parquet)
- **Output**: `data/datasets/ragas_dataset.jsonl` (RAGAS format)
- **Purpose**: Downloads external dataset, converts to RAGAS schema with `user_input`, `retrieved_contexts`, `reference` fields

**Phase 2: Run** (`scripts/run.py`)
- **Input**: `data/datasets/ragas_dataset.jsonl` + Agent URL
- **Output**: `data/experiments/ragas_experiment.jsonl` (adds `response` field for single-turn, full conversation for multi-turn)
- **Purpose**: Sends queries to agent via A2A protocol using `a2a-sdk`, records agent responses
- **Auto-Detection**: Detects single-turn vs multi-turn format and routes to appropriate experiment function
- **Multi-Turn Support**: For conversational datasets, sequentially queries agent for each user message while maintaining context_id

**Phase 3: Evaluate** (`scripts/evaluate.py`)
- **Input**: `data/experiments/ragas_experiment.jsonl` + LLM model + metrics list
- **Output**: `data/results/evaluation_scores.json`
- **Purpose**: Calculates RAGAS metrics using LLM-as-a-judge via AI Gateway, tracks tokens and costs

**Phase 4: Publish** (`scripts/publish.py`)
- **Input**: `data/results/evaluation_scores.json` + workflow name + execution ID + execution number
- **Output**: Metrics published to OTLP endpoint (configured via `OTEL_EXPORTER_OTLP_ENDPOINT` environment variable)
- **Purpose**: Sends evaluation results to observability backend (LGTM/Grafana) via OpenTelemetry

**Optional: Visualize** (`scripts/visualize.py`)
- **Input**: `data/results/evaluation_scores.json`
- **Output**: `data/results/evaluation_report.html` (self-contained HTML dashboard)
- **Purpose**: Generates comprehensive HTML report with charts, tables, and statistics for local viewing and sharing
- **Features**: Summary cards, bar charts, metric distributions, searchable results table
- **Note**: Runs independently of Phase 4 (publish.py), can be used for local development without OTLP backend

### Data Flow

```
External Dataset (CSV/JSON/Parquet)
  ↓ [setup.py]
data/datasets/ragas_dataset.jsonl
  ↓ [run.py + A2A Client]
data/experiments/ragas_experiment.jsonl
  ↓ [evaluate.py + RAGAS + AI Gateway]
data/results/evaluation_scores.json
  ├─→ [publish.py + OTLP]
  │   Observability Backend (Grafana)
  └─→ [visualize.py]
      data/results/evaluation_report.html (Local Visualization)
```

### Kubernetes Integration (Testkube)

**Orchestration Pattern**: Each phase is a reusable `TestWorkflowTemplate` CRD that executes the same Docker image with different script arguments.

**Shared State**: All phases mount the same `emptyDir` volume at `/app/data`, enabling stateless containers with persistent data flow between steps.

**Template Files**:
- `deploy/base/templates/setup-template.yaml` - Phase 1
- `deploy/base/templates/run-template.yaml` - Phase 2
- `deploy/base/templates/evaluate-template.yaml` - Phase 3
- `deploy/base/templates/publish-template.yaml` - Phase 4
- `deploy/local/ragas-evaluation-workflow.yaml` - Combines all templates into complete workflow

**Key Workflow Parameters**:
- `datasetUrl` - HTTP URL to test dataset
- `agentUrl` - A2A endpoint of agent to evaluate
- `model` - LLM model for RAGAS evaluation (e.g., `gemini-2.5-flash-lite`)
- `metrics` - Space-separated RAGAS metrics (e.g., `faithfulness context_recall`)
- `otlpEndpoint` - OpenTelemetry collector URL (default: `http://lgtm.monitoring:4318`)
- `image` - Docker image to use (default: `ghcr.io/agentic-layer/testbench/testworkflows:latest`)

---

## Key Technology Integrations

### RAGAS Framework
- **Purpose**: LLM-as-a-judge evaluation framework for RAG systems
- **Evaluation Approach**: Uses LLM to assess quality metrics beyond simple exact-match comparison
- **Available Metrics**: `faithfulness`, `answer_relevancy`, `context_precision`, `context_recall`, `nv_accuracy`
- **Cost Tracking**: Automatically tracks token usage and calculates evaluation costs
- **LLM Access**: Routes through AI Gateway (LiteLLM) configured via `OPENAI_API_BASE` environment variable

### A2A Protocol (Agent-to-Agent)
- **Purpose**: Platform-agnostic JSON-RPC protocol for agent communication
- **Client Library**: `a2a-sdk` Python package
- **Usage in Testbench**: `run.py` uses `A2AClient` to send `user_input` prompts to agent's A2A endpoint
- **Response Handling**: Agent responses stored in `response` field of experiment JSONL
- **Context Management**: A2A `context_id` field maintains conversation state across multiple turns

### Multi-Turn Conversation Support
- **Purpose**: Evaluate agents in conversational scenarios with multiple back-and-forth exchanges
- **Detection**: `run.py` automatically detects dataset type by inspecting `user_input` field type (string = single-turn, list = multi-turn)
- **Experiment Functions**:
  - `single_turn_experiment()`: Handles traditional question-answer format
  - `multi_turn_experiment()`: Handles conversational interactions
- **Sequential Query Strategy**: For each human message in the conversation:
  1. Send message to agent via A2A protocol
  2. Capture agent's response and extract `context_id`
  3. Use `context_id` in subsequent messages to maintain conversation context
  4. After final turn, extract full conversation history from `task.history`
- **Data Format**: Multi-turn datasets use list of message dicts: `[{"content": "...", "type": "human"}, {"content": "...", "type": "ai"}, ...]`
- **Tool Calls**: Extracts tool call information from A2A `message.metadata` if available
- **Observability**: Creates parent span for conversation with child spans for each turn

### OpenTelemetry (OTLP)
- **Purpose**: Standard protocol for publishing observability data
- **Transport**: HTTP/protobuf to OTLP collector endpoint (port 4318)
- **Metrics Published**: Overall scores, individual results, token counts, costs
- **Labeling**: Each metric labeled with `workflowName` for filtering in Grafana

### Tilt (Local Development)
- **Purpose**: Local Kubernetes development environment
- **What Gets Deployed**:
  - Core operators: `agent-runtime` (v0.16.0), `ai-gateway-litellm` (v0.3.2), `agent-gateway-krakend` (v0.4.1)
  - Test infrastructure: `testkube` (v2.4.2), sample `weather-agent`, `data-server`
  - Observability: LGTM stack (Grafana, Loki, Tempo, Mimir)
  - TestWorkflow templates and evaluation workflow
- **Port Forwards**: `11001` (AI Gateway), `11010` (Weather Agent), `11000` (Grafana), `11020` (Data Server)

---

## Code Organization

### Core Scripts (scripts/)
All scripts follow same pattern: parse arguments → read input file(s) → process → write output file

- **`setup.py`**: Dataset download and conversion logic
  - Supports CSV (with quoted array parsing), JSON, Parquet formats
  - Validates required fields: `user_input`, `retrieved_contexts`, `reference`
  - Creates parent directories if missing

- **`run.py`**: Agent query execution
  - Uses `A2AClient` from `a2a-sdk` for async HTTP requests
  - Batch processes dataset entries
  - Adds `response` field to each entry

- **`evaluate.py`**: RAGAS metric calculation
  - Configures LangChain OpenAI wrapper to use AI Gateway
  - Instantiates RAGAS `SingleTurnSample` and `EvaluationDataset`
  - Runs selected metrics, computes overall scores
  - Extracts token usage and cost from callback handler

- **`publish.py`**: OTLP metric publishing
  - Converts evaluation scores to OpenTelemetry metrics
  - Sends via HTTP to OTLP collector
  - Uses workflow name as metric label

- **`visualize.py`**: HTML visualization generation
  - Reads `evaluation_scores.json` and generates self-contained HTML dashboard
  - Creates summary cards, bar charts, metric distributions, and results table
  - Uses Chart.js via CDN for interactive visualizations
  - Inline CSS for single-file distribution
  - Includes search functionality for results table

### Test Organization

**Unit Tests (`tests/`)**:
- One test file per script: `test_setup.py`, `test_run.py`, `test_evaluate.py`, `test_publish.py`, `test_visualize.py`
- Uses pytest with async support (`pytest-asyncio`)
- Mocks external dependencies: HTTP requests (`httpx.AsyncClient`), A2A client, RAGAS framework
- Uses `tmp_path` fixture for file I/O testing
- Test data samples in `tests/test_data/`

**E2E Test (`tests_e2e/test_e2e.py`)**:
- Runs complete 4-phase pipeline in sequence
- Configurable via environment variables: `E2E_DATASET_URL`, `E2E_AGENT_URL`, `E2E_MODEL`, etc.
- Validates output files exist after each phase
- Requires Tilt environment running for dependencies

### Deployment Manifests

**Testkube Templates (`deploy/base/templates/`)**:
- Each template is a `TestWorkflowTemplate` CRD
- Defines container spec, volume mounts, command arguments
- Parameterized with `config.*` variables (e.g., `{{ config.datasetUrl }}`)

**Local Development (`deploy/local/`)**:
- `ragas-evaluation-workflow.yaml` - Complete workflow definition
- `weather-agent.yaml` - Sample Agent CRD for testing
- `lgtm.yaml` - Grafana LGTM observability stack
- `data-server/` - ConfigMap with test datasets + Service for HTTP access

---

## Development Guidelines

### Testing Requirements
- **Never delete failing tests** - Either update tests to match correct implementation or fix code to pass tests
- **Unit tests must mock external dependencies** - No real HTTP calls, A2A clients, or LLM requests
- **E2E test validates file existence** - Doesn't validate content correctness (use unit tests for that)

### Code Quality Standards
- **Line Length**: 120 characters max (Ruff)
- **Type Hints**: Required for all function signatures (mypy enforced)
- **Import Sorting**: Enabled via Ruff (I001 rule)
- **Security Scanning**: Bandit checks for vulnerabilities
- **Naming Conventions**: PEP 8 compliant (Ruff N rule)

### Pre-commit Hooks
- Run automatically before commits via `.pre-commit-config.yaml`
- Enforces: Ruff formatting/linting, mypy, bandit
- Manual run: `pre-commit run --all-files`

### Adding New RAGAS Metrics
1. Add metric import to `scripts/evaluate.py`
2. Update metric validation in argument parsing
3. Add to available metrics list in README
4. Add test cases in `tests/test_evaluate.py` with mocked metric

### Modifying Data Flow
If changing intermediate file formats or locations:
1. Update corresponding script I/O logic
2. Update all dependent scripts (downstream phases)
3. Update TestWorkflowTemplate volume mount paths if needed
4. Update unit test mocks
5. Update E2E test file path validations

---

## Common Debugging Scenarios

### Local Pipeline Failures

**Issue**: `setup.py` fails to download dataset
- **Check**: Dataset URL accessible from local machine
- **Check**: File format is CSV, JSON, or Parquet
- **Check**: Dataset contains required fields: `user_input`, `retrieved_contexts`, `reference`

**Issue**: `run.py` fails to query agent
- **Check**: Agent URL is correct and agent is running (verify with `curl`)
- **Check**: Agent exposes A2A protocol endpoint
- **Check**: Network connectivity between testbench and agent

**Issue**: `evaluate.py` fails with LLM errors
- **Check**: `OPENAI_API_BASE` points to AI Gateway (e.g., `http://localhost:11001`)
- **Check**: `GOOGLE_API_KEY` environment variable set
- **Check**: AI Gateway has access to specified model (check AI Gateway logs)

**Issue**: `publish.py` fails to send metrics
- **Check**: OTLP endpoint is reachable
- **Check**: OTLP collector is running and accepting HTTP on port 4318
- **Check**: Workflow name is valid (no special characters)

### Testkube Workflow Failures

**Issue**: Workflow stuck in "Queued" state
- **Check**: Testkube controller is running: `kubectl get pods -n testkube`
- **Check**: Sufficient cluster resources for workflow pods

**Issue**: Workflow fails at specific step
- **Check step logs**: `kubectl testkube logs testworkflow ragas-evaluation-workflow -n testkube`
- **Check volume mounts**: Verify previous step wrote output file correctly
- **Check parameter values**: Ensure URLs and names are correct in workflow config

**Issue**: Template not found errors
- **Check templates exist**: `kubectl get testworkflowtemplates -n testkube`
- **Reinstall templates**: `kubectl apply -f deploy/base/templates/ -n testkube`

### Tilt Environment Issues

**Issue**: Tilt fails to start operators
- **Check Kubernetes cluster**: `kubectl cluster-info`
- **Check tilt-extensions version**: Must be v0.6.0 or later in Tiltfile
- **Check .env file**: Must contain `GOOGLE_API_KEY`

**Issue**: Port forward conflicts
- **Check ports available**: 11000, 11001, 11010, 11020
- **Kill conflicting processes**: `lsof -ti:11001 | xargs kill`

**Issue**: Agent not responding on port 11010
- **Check agent status**: `kubectl get pods -n sample-agents`
- **Check agent logs**: `kubectl logs -n sample-agents deployment/weather-agent`

---

## Cross-Repository Dependencies

### Platform Operators (Required at Runtime)
- **agent-runtime-operator** (v0.16.0): Provides `Agent`, `ToolServer`, `AgenticWorkforce` CRDs
- **ai-gateway-litellm-operator** (v0.3.2): Provides `AiGateway` CRD for LLM access during evaluation
- **agent-gateway-krakend-operator** (v0.4.1): Provides `AgentGateway` CRD for routing (optional, only if using gateway)
- **tilt-extensions** (v0.6.0): Custom Tilt helpers for local operator installation

### Version Sync Points
When operators update CRD schemas:
1. Verify YAML manifests in `deploy/local/` still valid
2. Update TestWorkflowTemplate CRDs if volume paths or parameters changed
3. Update Tiltfile with new operator versions
4. Test E2E pipeline with new operator versions

### Agent Integration
Testbench can evaluate any agent that:
1. Exposes A2A protocol endpoint
2. Is deployed via `Agent` CRD or accessible HTTP endpoint
3. Returns text responses to text prompts

Examples: `agent-samples/weather-agent`, showcase agents (`showcase-cross-selling`, `showcase-news`)

---

## Important Constraints

### RAGAS Metric Limitations
- Most metrics require `retrieved_contexts` field in dataset
- LLM-based metrics consume tokens and incur costs
- Evaluation speed depends on AI Gateway throughput and model latency
- Some metrics (e.g., `context_recall`) require `reference` ground truth

### A2A Protocol Requirements
- Agents must implement A2A JSON-RPC specification
- Only supports text-based question-answering (no multi-modal, no streaming in evaluation)
- Response timeout configured in `a2a-sdk` client (default: 30s)

### Kubernetes Resource Requirements
- TestWorkflows create pods that need persistent volume for shared data
- Each phase runs sequentially (no parallel execution of phases)
- Workflow pods cleaned up after completion (data persists in volume temporarily)

### Data Privacy
- Datasets may contain sensitive information - ensure OTLP endpoints are secured
- Evaluation results include full prompts and responses - consider data retention policies
- AI Gateway logs may contain dataset content - review log retention settings
