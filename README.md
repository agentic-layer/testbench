# Testbench

Kubernetes-native agent evaluation system that executes test datasets via the A2A protocol, scores responses with pluggable metrics (RAGAS by default), and publishes scores via OpenTelemetry.

📖 **Documentation:** https://docs.agentic-layer.ai/testbench/

## Run standalone

For evaluating an agent without deploying into Kubernetes / Testkube:

```shell
pip install agentic-layer-testbench
testworkflow config.yaml
```

See [`config.example.yaml`](./config.example.yaml) for the available configuration options.

## Development

### Prerequisites

- **Python**
- **uv**
- **Tilt** and a local Kubernetes cluster (e.g. kind)
- **[Testkube CLI](https://docs.testkube.io/articles/install/cli)**
- **`GOOGLE_API_KEY`** for LLM-as-a-judge evaluation via Gemini

### Build and run locally

```shell
# Install Python dependencies
uv sync
# Provide the LLM-as-a-judge API key
echo "GOOGLE_API_KEY=<key>" > .env
# Start the local stack (AI gateway, OTLP collector, sample agents, Testkube)
tilt up
```

### Test

```shell
uv run poe ruff      # format and lint
uv run poe mypy      # static type checking
uv run poe bandit    # security scanning
uv run poe test      # unit tests
uv run poe check     # all of the above
uv run poe test_e2e  # E2E tests (requires `tilt up`)
```

E2E defaults target the Tilt environment. Override with `E2E_DATASET_URL`, `E2E_AGENT_URL`, `E2E_MODEL` if needed.

### Verify the local deploy

Run the example workflow against the sample weather agent:

```shell
kubectl testkube run tw example-workflow --watch
```

The full walkthrough — defining experiments, configuring metrics, viewing reports — is in the [first-workflow how-to](https://docs.agentic-layer.ai/testbench/how-to/first-workflow.html).

## Contributing

See the [Contribution Guide](https://github.com/agentic-layer/testbench?tab=contributing-ov-file).
