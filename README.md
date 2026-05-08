# Testbench

Kubernetes-native agent evaluation system that executes test datasets via A2A protocol, evaluates responses using pluggable metrics (RAGAS by default), and publishes scores via OpenTelemetry.

## Documentation

Full documentation is available at [docs.agentic-layer.ai](https://docs.agentic-layer.ai/testbench/).

## Install

Run the testbench standalone (without Kubernetes / Testkube) on any system:

```shell
pip install agentic-layer-testbench
testbench config.yaml
```

See [`config.example.yaml`](./config.example.yaml) for the available configuration options.

## Prerequisites

- **Python 3.12+** and [uv](https://docs.astral.sh/uv/)
- **Kubernetes cluster** (e.g. kind) with [Tilt](https://tilt.dev/)
- **[Testkube CLI](https://docs.testkube.io/articles/install/cli)**
- **`GOOGLE_API_KEY`** for LLM-as-a-judge evaluation via Gemini models

## Getting Started

```shell
# 1. Start local infrastructure (AI Gateway, OTLP collector, sample agents, Testkube)
#    Create a .env file with GOOGLE_API_KEY=your-key first
tilt up

# 2. Run the example evaluation workflow
kubectl testkube run tw example-workflow --watch
```

See the [how-to guide](https://docs.agentic-layer.ai/testbench/how-to/first-workflow.html) for detailed pipeline usage including dataset format, metric configuration, and custom workflows.

## Development

| Command | Description |
|---------|-------------|
| `uv run poe check` | Run all quality checks (tests, mypy, bandit, ruff) |
| `uv run poe test` | Unit tests |
| `uv run poe format` | Format with Ruff |
| `uv run poe lint` | Lint and auto-fix with Ruff |
| `uv run poe ruff` | Both format and lint |
| `uv run poe mypy` | Static type checking |
| `uv run poe bandit` | Security vulnerability scanning |

## E2E Testing

Requires the Tilt environment running (`tilt up`).

```shell
# Configure (optional — defaults target the Tilt environment)
export E2E_DATASET_URL="http://data-server.data-server:8000/dataset.csv"
export E2E_AGENT_URL="http://weather-agent.sample-agents:8000"
export E2E_MODEL="gemini-2.5-flash-lite"

# Run
uv run poe test_e2e
```

## Contributing

See [Contribution Guide](https://github.com/agentic-layer/testbench?tab=contributing-ov-file) for details on contributing and the process for submitting pull requests.
