# Red-Teaming Workflow — Design Spec

**Date:** 2026-05-06
**Status:** Draft

## Overview

A separate red-teaming workflow that exercises an agent under test with adversarial inputs and grades the agent's defenses. Implemented as a standalone Python entry point (`scripts/redteam.py`) and a Testkube `TestWorkflowTemplate`, parallel to — and independent of — the existing functional evaluation pipeline (`scripts/pipeline.py`).

The workflow targets a pluggable backend through a `RedteamAdapter` abstraction. v1 ships one adapter for [promptfoo](https://github.com/promptfoo/promptfoo). The abstraction is designed so a second backend (e.g., garak, PyRIT) can be added without changes to `redteam.py` or its config schema.

## Goals

- Add adversarial / red-team testing of agents to the testbench.
- Keep the red-team workflow fully separate from the functional evaluation pipeline. They share the agent target and (optionally) the OTLP backend; otherwise no coupling.
- Expose a backend-agnostic config and adapter interface so promptfoo is replaceable.
- Surface findings as first-class OTLP metrics so vulnerabilities show up in Grafana alongside functional metrics.
- Preserve each backend's native report (e.g., promptfoo's HTML) for human investigation.
- Run locally (`uv run python3 scripts/redteam.py …`) and in Testkube using the same Docker image.

## Non-Goals

- Integrating red-team findings into the existing `Experiment` / `EvaluatedExperiment` schema. Adversarial test cases do not have user-curated `reference` data and use plugin-specific graders, not RAGAS metrics.
- Running multiple backends in a single invocation.
- Authoring custom plugins. Users select from what the configured backend ships.
- Auto-remediation suggestions or finding diffing across runs (Grafana handles trends).
- Replacing or duplicating the backend's native report UI in our own visualization.

## Architecture

### Repository layout

```
scripts/
  redteam.py                # entry point — mirrors pipeline.py shape
  redteam/
    __init__.py
    adapter.py              # RedteamAdapter Protocol + shared models
    registry.py             # backend lookup by name (lazy import)
    promptfoo/
      __init__.py
      adapter.py            # PromptfooAdapter
      config_translator.py  # RedteamRunConfig → promptfooconfig.yaml
    publish.py              # OTLP emitter for findings
    report.py               # thin summary index linking the native report
  schema/
    redteam_config.py       # Pydantic config model (RedteamConfig + sub-models)

deploy/local/testkube/
  redteam-template.yaml     # TestWorkflowTemplate
  redteam-workflow.yaml     # concrete TestWorkflow combining the template

tests/
  redteam/
    test_redteam_config.py
    test_config_translator.py
    test_promptfoo_adapter.py
    test_publish.py
    test_redteam_entry.py
tests_e2e/
  test_redteam_e2e.py
```

### Workflow placement

```
                                       agent (A2A)
                                          ▲
                                          │
config.yaml ── pipeline.py ──── run ──── │ ──── evaluate ── publish ── visualize
                                          │
redteam-config.yaml ── redteam.py ────────┘ ─── RedteamAdapter (PromptfooAdapter v1)
                                                    │
                                                    ├── data/redteam/findings.json
                                                    ├── data/redteam/native-report.html
                                                    └── OTLP (redteam_* metrics)
```

Two parallel entry points. Both pure Python, both shellable from `uv run`, both wrappable in a Testkube template. They share only:

- The agent target (same A2A URL).
- Optionally the OTLP endpoint and labels (`experiment_name`, `execution_id`, `execution_number`).
- The `data/` output directory convention.

No code-level coupling. `pipeline.py` is untouched.

### Promptfoo invocation model

The `PromptfooAdapter` shells out to `npx promptfoo@<pinned-version>`. Node.js is not added to `pyproject.toml`; it is a system dependency:

- **Testkube image:** the existing `Dockerfile` is extended to install Node.js ≥18.
- **Local dev:** users need Node.js ≥18 on PATH. The adapter prints a clear error if `npx` is missing.

This avoids polluting the Python dependency surface with a Node.js toolchain.

## Components

### 1. `scripts/schema/redteam_config.py` — Pydantic config

Validates `redteam-config.yaml` upfront. Mirrors the shape of `PipelineConfig` so users see a familiar schema. See [Config Schema](#config-schema) below for the model details.

### 2. `scripts/redteam/adapter.py` — abstraction

Pure data + interface. No I/O, no subprocess code, no promptfoo references. This is the contract a second backend must satisfy.

```python
from typing import Protocol, Literal
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Any

class PluginDescriptor(BaseModel):
    name: str                     # backend-namespaced, e.g. "promptfoo:pii"
    severity: Literal["low", "medium", "high", "critical"]
    description: str

class TargetSpec(BaseModel):
    url: str
    protocol: Literal["a2a", "http"] = "a2a"
    timeout_seconds: int = 30

class RedteamRunConfig(BaseModel):
    target: TargetSpec
    plugins: list[str]
    judge_model: str | None = None
    num_tests_per_plugin: int = 10
    output_dir: Path
    backend_options: dict[str, Any] = Field(default_factory=dict)

class Finding(BaseModel):
    plugin: str                   # e.g. "promptfoo:harmful:violent-crime"
    severity: Literal["low", "medium", "high", "critical"]
    test_input: str
    target_response: str
    passed: bool                  # did the agent's defense hold?
    grader_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class RedteamSummary(BaseModel):
    total: int
    passed: int
    failed: int
    by_severity: dict[str, int]   # "critical" -> count, etc.
    by_plugin: dict[str, dict[str, int]]  # plugin -> {"passed": n, "failed": m}

class RedteamResults(BaseModel):
    backend: str
    findings: list[Finding]
    summary: RedteamSummary
    native_report_path: Path | None = None

class RedteamAdapter(Protocol):
    name: str

    def list_plugins(self) -> list[PluginDescriptor]: ...
    def run(self, config: RedteamRunConfig) -> RedteamResults: ...
```

Key choices:

- **Plugins are backend-namespaced strings.** No fake portability layer — `promptfoo:pii` and `garak:lmrc.SlurUsage` are clearly different. Switching backends means re-picking plugins. Honest > leaky.
- **One method does generation + run + grade.** Some backends bundle these; some split them (PyRIT). The split is hidden inside the adapter.
- **`backend_options` escape hatch.** Per-backend tuning lives there, keyed by adapter name. Keeps the core schema stable.
- **Findings are normalized.** Same `Finding` shape regardless of backend — uniform OTLP metrics and a thin testbench summary.

### 3. `scripts/redteam/registry.py` — backend lookup

```python
def get_adapter(name: str) -> RedteamAdapter: ...
def available_backends() -> list[str]: ...
```

Lazy-imports adapter modules so a missing optional dep (e.g., garak not installed) does not crash promptfoo runs. Same pattern as `metrics/registry.py`.

### 4. `scripts/redteam/promptfoo/` — v1 adapter

- `config_translator.py` — pure function: `RedteamRunConfig → dict` matching promptfoo's YAML schema. The single place that knows promptfoo's config shape. Easy to unit-test, easy to update when promptfoo evolves.
- `adapter.py` — `PromptfooAdapter` implementing the Protocol:
  1. Translates run config to a temp `promptfooconfig.yaml`.
  2. Invokes `npx promptfoo@<pinned> redteam run --config <tmp> --output <output_dir>/promptfoo-output.json`.
  3. Captures stdout/stderr to phase logs.
  4. Parses promptfoo's JSON output and normalizes into `Finding` objects + `RedteamSummary`.
  5. Sets `native_report_path` to the HTML report promptfoo produces in `output_dir`.

**A2A target wiring:** promptfoo's built-in `http` provider is configured with a request template that posts the A2A JSON-RPC envelope to `target.url`, and a response template that extracts the assistant content from the A2A reply. If the A2A response shape requires logic beyond promptfoo's templating, fall back to a small custom JS provider stub committed alongside the adapter.

### 5. `scripts/redteam/publish.py` — OTLP emitter

Reads `RedteamResults`, emits gauge metrics in a `redteam_*` namespace:

- `redteam_findings_total{plugin, severity, backend}`
- `redteam_pass_rate{plugin, backend}`
- `redteam_critical_count{backend}`

Labels include `experiment_name`, `execution_id`, `execution_number` so findings line up with functional eval runs in Grafana. Reuses `scripts/otel_setup.py` for OTLP setup.

### 6. `scripts/redteam.py` — entry point

Thin orchestrator, mirrors `pipeline.py`:

```python
def main(config_path: str) -> int:
    config = RedteamConfig.model_validate(yaml.safe_load(open(config_path)))
    adapter = registry.get_adapter(config.backend.name)
    results = adapter.run(_to_run_config(config))
    _write_findings(results, config.output.dir)
    if config.otlp:
        publish.emit(results, config.experiment.name,
                     _resolve_execution_id(config.workflow.execution_id),
                     _resolve_execution_number(config.workflow.execution_number),
                     config.otlp.endpoint)
    report.write_summary_index(results, config.output.dir)
    return _exit_code_for(results, config.fail_on)
```

`--list-plugins` flag: instantiates the configured backend adapter and prints `name | severity | description`.

`_resolve_execution_id` / `_resolve_execution_number` reuse the same helpers (or copies of them) as `pipeline.py` for `auto`/`$GITHUB_RUN_ID` resolution.

## Data Flow

```
redteam-config.yaml
        │
        ▼
┌─────────────────┐
│   redteam.py    │  validate config (Pydantic)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    registry     │  resolve backend name → adapter instance
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│              PromptfooAdapter.run()                     │
│                                                         │
│  RedteamRunConfig                                       │
│        │                                                │
│        ▼                                                │
│  config_translator → /tmp/promptfooconfig.yaml          │
│        │                                                │
│        ▼                                                │
│  subprocess: npx promptfoo redteam run                  │
│      --config /tmp/promptfooconfig.yaml                 │
│      --output data/redteam/promptfoo-output.json        │
│        │                                                │
│        ▼                                                │
│  parse promptfoo-output.json                            │
│        │                                                │
│        ▼                                                │
│  normalize → list[Finding] + RedteamSummary             │
└────────┬────────────────────────────────────────────────┘
         │
         ▼   RedteamResults
┌─────────────────────────────────────────┐
│  write data/redteam/findings.json       │  (normalized, backend-agnostic)
│  keep   data/redteam/native-report.html │  (linked, not parsed downstream)
└────────┬────────────────────────────────┘
         │
         ├──→ redteam/publish.py ──→ OTLP (redteam_* gauges)
         │
         └──→ stdout summary + summary.html

         exit code: 0 if no severity ≥ fail_on threshold, else 1
```

### Output files per run

```
data/redteam/
  findings.json          # normalized RedteamResults — the canonical artifact
  native-report.html     # promptfoo's HTML report — linked, never parsed
  promptfoo-output.json  # raw promptfoo JSON — kept for debugging
  summary.html           # thin index page linking the above
```

`findings.json` is the only artifact downstream consumers (OTLP publisher, future dashboards, CI gates) read. `native-report.html` and `promptfoo-output.json` are promptfoo-specific — preserved for human investigation, never parsed by testbench code outside the adapter.

### Target invocation flow inside promptfoo

```
promptfoo redteam run
   │
   ├── generates adversarial prompts (uses judge_model via OpenAI/Anthropic-compatible API)
   │       └─ routed through OPENAI_API_BASE → AI Gateway (LiteLLM) when set
   │
   ├── for each prompt: HTTP POST → {target.url}/a2a-rpc
   │       └─ request template wraps prompt in A2A JSON-RPC envelope
   │       └─ response template extracts assistant content from A2A reply
   │
   └── grades each (prompt, response) pair with plugin-specific grader
           └─ also via OPENAI_API_BASE → AI Gateway
```

The same `OPENAI_API_BASE` env var that the existing pipeline uses for evaluate-phase LLM calls is reused here. No new auth path.

### OTLP labels

Every `redteam_*` metric carries `experiment_name`, `execution_id`, `execution_number`, `backend`, `plugin`, `severity`. A Grafana panel can filter to "all critical findings for experiment X across the last N runs".

## Config Schema

### `redteam-config.yaml`

```yaml
target:
  url: "http://weather-agent.sample-agents:8000"
  protocol: "a2a"           # a2a | http
  timeout_seconds: 30

backend:
  name: "promptfoo"         # promptfoo (v1); garak/pyrit pluggable later
  version: "0.x.y"          # pinned for reproducibility
  options: {}               # backend-specific escape hatch

plugins:
  - "promptfoo:harmful:violent-crime"
  - "promptfoo:pii"
  - "promptfoo:prompt-injection"
  - "promptfoo:bola"
  - "promptfoo:excessive-agency"
  # `redteam.py --list-plugins` enumerates available plugins per backend

judge:
  model: "gemini-2.5-flash-lite"
  num_tests_per_plugin: 10

output:
  dir: "data/redteam"
  keep_native_report: true

otlp:
  endpoint: "http://lgtm.monitoring:4318"   # optional; OTEL_EXPORTER_OTLP_ENDPOINT also honored

experiment:
  name: "weather-agent-redteam"

workflow:
  execution_id: "auto"      # auto → $GITHUB_RUN_ID || uuid
  execution_number: 1       # auto → $GITHUB_RUN_NUMBER || 1

fail_on:
  severity: "high"          # exit 1 if any finding ≥ this severity. null disables.
```

### Pydantic models

```python
class TargetConfig(BaseModel):
    url: str
    protocol: Literal["a2a", "http"] = "a2a"
    timeout_seconds: int = 30

class BackendConfig(BaseModel):
    name: str
    version: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)

class JudgeConfig(BaseModel):
    model: str | None = None
    num_tests_per_plugin: int = 10

class OutputConfig(BaseModel):
    dir: str = "data/redteam"
    keep_native_report: bool = True

class FailOnConfig(BaseModel):
    severity: Literal["low", "medium", "high", "critical"] | None = "high"

class OtlpConfig(BaseModel):
    endpoint: str

class ExperimentConfig(BaseModel):
    name: str

class WorkflowConfig(BaseModel):
    execution_id: str = "auto"
    execution_number: int = 1

class RedteamConfig(BaseModel):
    target: TargetConfig
    backend: BackendConfig
    plugins: list[str] = Field(min_length=1)
    judge: JudgeConfig = JudgeConfig()
    output: OutputConfig = OutputConfig()
    otlp: OtlpConfig | None = None
    experiment: ExperimentConfig
    workflow: WorkflowConfig = WorkflowConfig()
    fail_on: FailOnConfig = FailOnConfig()
```

### Secrets

Never in YAML. Same env-var model as `PipelineConfig`:

| Variable | Purpose | Required When |
|----------|---------|---------------|
| `GOOGLE_API_KEY` | Gemini judge/generation | Using Gemini models |
| `OPENAI_API_KEY` | OpenAI judge/generation | Using OpenAI models |
| `OPENAI_API_BASE` | AI Gateway routing | Using AI Gateway |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP override | Optional |

## Error Handling

| Failure | Detection | Behavior |
|---|---|---|
| Invalid `redteam-config.yaml` | Pydantic validation in `redteam.py` | Exit 1, print validation errors |
| Unknown backend name | `registry.get_adapter()` raises | Exit 1, list available backends |
| `npx promptfoo` not on PATH | Subprocess `FileNotFoundError` | Exit 2, message: "Node.js ≥18 required, or use the Testkube image" |
| Promptfoo subprocess non-zero exit | Adapter inspects return code + stderr | Exit 2, stderr forwarded to logs, partial findings preserved if any |
| Target unreachable / A2A error | Promptfoo records as test errors in its output | Surfaced as `Finding(passed=False, metadata={"error": ...})`. Run continues |
| OTLP endpoint unreachable | `redteam.publish` uses short timeout, logs warning | Run does not fail. Findings JSON + native report still written |
| Adversarial generation rate-limit | Promptfoo retries internally; if exhausted | Surfaces as test error (above) |
| Findings exceed `fail_on.severity` | Final check after publish | Exit 1 with summary line: "3 critical findings — see data/redteam/findings.json" |

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Completed; no findings ≥ `fail_on.severity` |
| 1 | Config invalid, OR findings exceed threshold (CI-fail signal) |
| 2 | Backend execution failed (infrastructure issue, not a finding) |

CI distinguishes "you have vulnerabilities" (1) from "the scanner broke" (2). Important for triage.

### Logging

Python `logging` with phase-style prefixes: `[redteam]`, `[promptfoo]`, `[publish]`. Start/end timing per phase. Key decisions logged: "OTLP not configured, skipping publish", "fail_on.severity disabled, ignoring threshold check".

## Testing Strategy

### Unit tests (`tests/redteam/`)

- `test_redteam_config.py` — Pydantic validation, default resolution, invalid-config cases.
- `test_config_translator.py` — `RedteamRunConfig → promptfooconfig.yaml` golden-file tests. Pure function, no I/O. Catches drift when promptfoo's schema changes.
- `test_promptfoo_adapter.py` — mocks subprocess. Asserts: correct command-line built, correct config file written, output JSON parsed into `Finding` objects, severities normalized, errors surfaced as failed findings.
- `test_publish.py` — mocks OTLP exporter. Asserts: correct gauge metrics emitted, labels match findings, no metric on empty results.
- `test_redteam_entry.py` — end-to-end at the `redteam.py` level with a mocked adapter. Exercises exit codes for each failure class.

No real promptfoo subprocess in unit tests. A separate fast smoke test gated behind `RUN_REDTEAM_SMOKE=1` runs one plugin against a stub HTTP server to catch wiring regressions.

### E2E test (`tests_e2e/test_redteam_e2e.py`)

- Targets the Tilt weather-agent.
- Runs one cheap plugin (e.g., `promptfoo:harmful:violent-crime` with `num_tests_per_plugin: 2`).
- Asserts: `data/redteam/findings.json` exists and validates as `RedteamResults`; `native-report.html` exists; OTLP metrics observed at the collector.
- Configurable via `E2E_REDTEAM_*` env vars matching the existing E2E pattern.

## Deployment

### Local

```shell
uv run python3 scripts/redteam.py redteam-config.yaml
uv run python3 scripts/redteam.py --list-plugins --backend promptfoo
```

### Docker image

The existing `Dockerfile` is extended to install Node.js ≥18 in a single layer. Same image serves both `pipeline.py` and `redteam.py`.

### Testkube

- `deploy/local/testkube/redteam-template.yaml` — `TestWorkflowTemplate` parameterized with `targetUrl`, `plugins`, `backend`, `model`, `experimentName`, `failOnSeverity`, `otlpEndpoint`.
- `deploy/local/testkube/redteam-workflow.yaml` — concrete `TestWorkflow` consuming the template, mirroring `example-workflow.yaml`'s shape.
- Same `emptyDir` mount at `/app/data` so artifacts persist for the workflow lifetime.

### GitHub Actions

Same shape as the existing pipeline-runner GitHub Actions snippet, invoking `scripts/redteam.py` instead of `scripts/pipeline.py`. Uploads `data/redteam/native-report.html` and `data/redteam/findings.json` as artifacts.

## Out of Scope (v1)

- Multi-backend in a single run.
- Custom user-authored plugins.
- Diffing findings across runs (Grafana over OTLP handles trend; in-tool diffing later).
- Auto-remediation suggestions (promptfoo has this; not exposed in v1).
- Replaying a specific finding deterministically.
- A second adapter implementation (garak, PyRIT). The abstraction is designed for it; the implementation is a follow-up.

## Future Work

- **Second adapter (garak or PyRIT).** Validates the abstraction. Both are Python-native and would not require Node.js in the image.
- **Plugin metadata catalog.** A small generated JSON enumerating each backend's plugins (severity, description) so `--list-plugins` is fast and works without invoking the backend.
- **Trend dashboards.** Predefined Grafana panels for `redteam_*` metrics, similar to the existing functional metric dashboards.
- **Targeted re-runs.** Re-run a specific finding by ID for debugging fixes.