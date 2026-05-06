# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Repository Purpose

Kubernetes-native agent evaluation system that executes test datasets via A2A protocol, evaluates responses using a generic metrics framework (with RAGAS as the default adapter), and publishes metrics via OTLP. Part of the Agentic Layer platform for automated agent testing and quality assurance.

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
# Phase 1: Download and convert dataset to Experiment JSON
uv run python3 testbench/setup.py "http://localhost:11020/dataset.csv"

# Phase 2: Execute queries through agent via A2A protocol
uv run python3 testbench/run.py "http://localhost:11010" "my-workflow"

# Phase 3: Evaluate responses using metrics (with model override)
uv run python3 testbench/evaluate.py --model gemini-2.5-flash-lite

# Phase 4: Publish metrics to OTLP endpoint
OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318" uv run python3 testbench/publish.py "experiment-name" "exec-001" 1

# Optional: Generate HTML visualization report
uv run python3 testbench/visualize.py "weather-assistant-test" "exec-001" 1
```

### HTML Visualization

Generate a comprehensive HTML dashboard from evaluation results for local viewing and sharing.

```shell
# Basic usage (after running evaluate.py)
uv run python3 testbench/visualize.py weather-assistant-test exec-001 1

# Custom input/output paths
uv run python3 testbench/visualize.py weather-assistant-test exec-001 1 \
  --input data/experiments/evaluated_experiment.json \
  --output reports/exec-001.html
```

**Required Arguments:**
- `experiment_name` - Name of the test experiment (e.g., 'weather-assistant-test')
- `execution_id` - Testkube execution ID for this workflow run
- `execution_number` - Testkube execution number for this workflow run

**Optional Arguments:**
- `--input` - Path to evaluated experiment JSON (default: `data/experiments/evaluated_experiment.json`)
- `--output` - Path for output HTML file (default: `data/results/evaluation_report.html`)

**Features:**
- **Summary Cards**: Total samples, metrics count, scenario overview
- **Workflow Metadata**: Displays workflow name, execution ID, and execution number
- **Overall Scores Chart**: Horizontal bar chart showing mean score per metric
- **Metric Distributions**: Histograms showing score distributions with statistics
- **Detailed Results Table**: All steps with evaluations, searchable and sortable
- **Multi-Turn Support**: Chat-bubble visualization for conversational datasets
- **Self-Contained HTML**: Single file with embedded Chart.js, works offline
- **Responsive Design**: Works on desktop and tablet, print-friendly

### Testkube Execution

```shell
# Run complete evaluation workflow in Kubernetes
kubectl testkube run testworkflow ragas-evaluation-workflow \
    --config datasetUrl="http://data-server.data-server:8000/dataset.csv" \
    --config agentUrl="http://weather-agent.sample-agents:8000" \
    --config model="gemini-2.5-flash-lite" \
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

**Core Concept**: Sequential pipeline where each phase reads input from previous phase's output via shared `/app/data` volume. Uses typed Pydantic models (`Experiment` → `ExecutedExperiment` → `EvaluatedExperiment`) with JSON serialisation.

**Phase 1: Setup** (`testbench/setup.py`)
- **Input**: Dataset URL (CSV, JSON, or Parquet)
- **Output**: `data/datasets/experiment.json` (Experiment model)
- **Purpose**: Downloads external dataset, maps rows to `Step` objects with `input`, `reference`, and `custom_values` fields

**Phase 2: Run** (`testbench/run.py`)
- **Input**: `data/datasets/experiment.json` + Agent URL + experiment name
- **Output**: `data/experiments/executed_experiment.json` (ExecutedExperiment model)
- **Purpose**: Sends queries to agent via A2A protocol using `A2AStepClient`, records agent responses as `Turn` objects
- **Pattern**: Uses `ExperimentRuntime` with hooks (`before_scenario`, `on_step`, `after_scenario`)
- **Tracing**: Creates OpenTelemetry spans per scenario with trace IDs

**Phase 3: Evaluate** (`testbench/evaluate.py`)
- **Input**: `data/experiments/executed_experiment.json` + optional `--model` override
- **Output**: `data/experiments/evaluated_experiment.json` (EvaluatedExperiment model)
- **Purpose**: Calculates metrics using LLM-as-a-judge via generic metrics framework
- **Pattern**: Uses `ExperimentRuntime` with `MetricEvaluator` hooks
- **Metrics**: Configured via `Metric` objects on each step; uses `GenericMetricsRegistry` with RAGAS adapter

**Phase 4: Publish** (`testbench/publish.py`)
- **Input**: `data/experiments/evaluated_experiment.json` + experiment name + execution ID + execution number
- **Output**: Metrics published to OTLP endpoint (configured via `OTEL_EXPORTER_OTLP_ENDPOINT` environment variable)
- **Purpose**: Sends per-step evaluation scores to observability backend (LGTM/Grafana) via OpenTelemetry

**Optional: Visualize** (`testbench/visualize.py`)
- **Input**: `data/experiments/evaluated_experiment.json`
- **Output**: `data/results/evaluation_report.html` (self-contained HTML dashboard)
- **Purpose**: Generates comprehensive HTML report with charts, tables, and statistics
- **Note**: Runs independently of Phase 4, can be used for local development without OTLP backend

### Data Flow

```
External Dataset (CSV/JSON/Parquet)
  ↓ [setup.py]
data/datasets/experiment.json  (Experiment)
  ↓ [run.py + A2AStepClient]
data/experiments/executed_experiment.json  (ExecutedExperiment)
  ↓ [evaluate.py + GenericMetricsRegistry]
data/experiments/evaluated_experiment.json  (EvaluatedExperiment)
  ├─→ [publish.py + OTLP]
  │   Observability Backend (Grafana)
  └─→ [visualize.py]
      data/results/evaluation_report.html (Local Visualization)
```

### Pydantic Model Hierarchy

```
Step(input, reference, custom_values, metrics)
  └→ ExecutedStep(+id, turns)
       └→ EvaluatedStep(+evaluations: list[Evaluation])

Scenario(name, steps)
  └→ ExecutedScenario(+id, trace_id)
       └→ EvaluatedScenario(+evaluations)

Experiment(llm_as_a_judge_model, default_threshold, scenarios)
  └→ ExecutedExperiment(+id)
       └→ EvaluatedExperiment
```

### Kubernetes Integration (Testkube)

**Orchestration Pattern**: Each phase is a reusable `TestWorkflowTemplate` CRD that executes the same Docker image with different script arguments.

**Shared State**: All phases mount the same `emptyDir` volume at `/app/data`, enabling stateless containers with persistent data flow between steps.

**Template Files**:
- `operator/config/testworkflows/setup-template.yaml` - Phase 1
- `operator/config/testworkflows/run-template.yaml` - Phase 2
- `operator/config/testworkflows/evaluate-template.yaml` - Phase 3
- `operator/config/testworkflows/publish-template.yaml` - Phase 4
- `operator/config/testworkflows/visualize-template.yaml` - Optional visualization phase
- `deploy/local/ragas-evaluation-workflow.yaml` - Combines all templates into complete workflow

**Key Workflow Parameters**:
- `datasetUrl` - HTTP URL to test dataset
- `agentUrl` - A2A endpoint of agent to evaluate
- `model` - LLM model for evaluation (e.g., `gemini-2.5-flash-lite`)
- `otlpEndpoint` - OpenTelemetry collector URL (default: `http://lgtm.monitoring:4318`)
- `image` - Docker image to use (default: `ghcr.io/agentic-layer/testbench/testworkflows:latest`)

---

## Key Technology Integrations

### Generic Metrics Framework
- **Architecture**: `FrameworkAdapter` base class with pluggable implementations
- **Registry**: `GenericMetricsRegistry` lazily loads framework adapters
- **Default Adapter**: RAGAS (`metrics/ragas/adapter.py`) — translates `ExecutedStep` into RAGAS `EvaluationDataset` samples
- **Protocol**: `MetricCallable` protocol and `MetricResult` dataclass in `metrics/protocol.py`
- **LLM Access**: Routes through AI Gateway (LiteLLM) configured via `OPENAI_API_BASE` environment variable

### A2A Protocol (Agent-to-Agent)
- **Purpose**: Platform-agnostic JSON-RPC protocol for agent communication
- **Client Library**: `a2a-sdk` Python package, wrapped by `schema/a2a_client.py` (`A2AStepClient`)
- **Usage in Testbench**: `run.py` uses `A2AStepClient.send_step()` to query agents
- **Response Handling**: Agent responses recorded as `Turn` objects with `content` and `type`
- **Context Management**: A2A `context_id` field maintains conversation state across multiple turns

### ExperimentRuntime
- **Purpose**: Generic runtime that iterates `Experiment.scenarios[].steps[]` and calls user-provided hooks
- **Hooks**: `before_run`, `before_scenario`, `on_step`, `after_scenario`
- **Location**: `schema/runtime.py`
- **Used by**: Both `run.py` (`A2AExecutor`) and `evaluate.py` (`MetricEvaluator`)

### OpenTelemetry (OTLP)
- **Purpose**: Standard protocol for publishing observability data
- **Transport**: HTTP/protobuf to OTLP collector endpoint (port 4318)
- **Metrics Published**: Per-step evaluation gauge with metric name, score, and step/scenario attributes
- **Labeling**: Each metric labeled with `experiment_name` for filtering in Grafana

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

### Core Scripts (testbench/)
All scripts follow same pattern: parse arguments → read input file(s) → process → write output file

- **`setup.py`**: Dataset download and conversion logic
  - Supports CSV (with quoted array parsing), JSON, Parquet formats
  - Maps DataFrame rows to `Step` objects with `Reference` and `custom_values`
  - Output: `data/datasets/experiment.json`

- **`run.py`**: Agent query execution via `A2AExecutor`
  - Uses `A2AStepClient` for async A2A protocol requests
  - Creates OpenTelemetry spans per scenario
  - Records agent responses as `Turn` objects in `ExecutedStep`

- **`evaluate.py`**: Metric evaluation via `MetricEvaluator`
  - Uses `GenericMetricsRegistry` to resolve metric callables
  - Supports `--model` CLI arg to override `experiment.llm_as_a_judge_model`
  - Produces `Evaluation` objects (metric + result with score and pass/fail)

- **`publish.py`**: OTLP metric publishing
  - Reads `EvaluatedExperiment`, iterates `scenarios → steps → evaluations`
  - Creates gauge metrics per evaluation with step/scenario attributes
  - Uses experiment name as metric label

- **`visualize.py`**: HTML visualization generation
  - Reads `EvaluatedExperiment` and generates self-contained HTML dashboard
  - Creates summary cards, bar charts, metric distributions, and results table
  - Uses Chart.js via CDN for interactive visualizations

### Schema Package (testbench/schema/)
- **`models.py`**: Full Pydantic model hierarchy (Step → ExecutedStep → EvaluatedStep, etc.)
- **`runtime.py`**: `ExperimentRuntime` — generic hook-based experiment iterator
- **`a2a_client.py`**: `A2AStepClient` — thin wrapper around A2A SDK

### Metrics Package (testbench/metrics/)
- **`protocol.py`**: `MetricCallable` protocol, `MetricResult` dataclass
- **`adapter.py`**: Abstract `FrameworkAdapter` base class
- **`registry.py`**: `GenericMetricsRegistry` (lazy-loads adapters)
- **`ragas/adapter.py`**: RAGAS-specific `RagasFrameworkAdapter`

### Test Organization

**Unit Tests (`tests/`)**:
- One test file per script: `test_setup.py`, `test_run.py`, `test_evaluate.py`, `test_evaluate_experiment.py`, `test_publish.py`, `test_visualize.py`
- Additional: `test_a2a_client.py`, `test_metrics.py`
- Uses pytest with async support (`pytest-asyncio`)
- Mocks external dependencies: A2A client, metrics registry, OTLP
- Uses `tmp_path` fixture for file I/O testing

**E2E Test (`tests_e2e/test_e2e.py`)**:
- Runs complete 4-phase pipeline in sequence
- Configurable via environment variables: `E2E_DATASET_URL`, `E2E_AGENT_URL`, `E2E_MODEL`, etc.
- Validates output files exist after each phase
- Requires Tilt environment running for dependencies

### Deployment Manifests

**Testkube Templates (`operator/config/testworkflows/`)**:
- Each template is a `TestWorkflowTemplate` CRD
- Defines container spec, volume mounts, command arguments
- Parameterized with `config.*` variables (e.g., `{{ config.datasetUrl }}`)
- Bundled into the unified `install.yaml` via `make -C operator build-installer`

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

### Adding New Metrics
Metrics are resolved through the `GenericMetricsRegistry`:
1. Define `Metric(metric_name="...", threshold=0.8)` on each `Step` in the experiment JSON
2. The registry delegates to the appropriate `FrameworkAdapter` (currently RAGAS)
3. Add test cases in `tests/test_evaluate_experiment.py` with mocked metric callables

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
- **Reinstall templates**: `kubectl apply -k operator/config/testworkflows/` (or rebuild & apply `operator/dist/install.yaml`)

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

### Metric Limitations
- LLM-based metrics consume tokens and incur costs
- Evaluation speed depends on AI Gateway throughput and model latency
- Some metrics (e.g., `context_recall`) require `reference` ground truth
- RAGAS-specific metrics may require `retrieved_contexts` in `custom_values`

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
