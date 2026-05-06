# Unified Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dual Helm-chart + operator-kustomize install with a single rendered `operator/dist/install.yaml` published as a GitHub Release asset.

**Architecture:** Port the five `TestWorkflowTemplate` resources and the Grafana dashboard ConfigMap from `chart/` into the operator's kustomize tree under `operator/config/testworkflows/` and `operator/config/dashboards/`. Wire both into `operator/config/default` so `make build-installer` renders one complete `install.yaml`. Update the release workflow to drop the Helm chart job. Delete the `chart/` directory.

**Tech Stack:** Kustomize (kubebuilder layout), Tilt, Testkube `TestWorkflowTemplate` CRD, GitHub Actions.

**Spec:** [docs/superpowers/specs/2026-05-05-unified-installer-design.md](../specs/2026-05-05-unified-installer-design.md)

---

## Conventions

- All file paths are repo-relative unless they start with `/`.
- All shell commands run from the repo root unless a "Run from:" note says otherwise.
- Verify each `kustomize build` invocation by piping into `kubectl apply --dry-run=client -f -` to catch schema errors.
- Commit after every task. Each task is a self-contained, working state.

---

## Task 1: Create the testworkflows kustomize directory with the five templates ported to plain YAML

**Files:**
- Create: `operator/config/testworkflows/kustomization.yaml`
- Create: `operator/config/testworkflows/setup-template.yaml`
- Create: `operator/config/testworkflows/run-template.yaml`
- Create: `operator/config/testworkflows/evaluate-template.yaml`
- Create: `operator/config/testworkflows/publish-template.yaml`
- Create: `operator/config/testworkflows/visualize-template.yaml`
- Create: `operator/config/testworkflows/kustomizeconfig.yaml`

**Background:** The chart used Helm helpers (`testbench.image`, `testbench.namespace`, `testbench.labels`, `testbench.workflowLabels`) to template each TestWorkflowTemplate. After porting, the templates are plain YAML. The image is set literally and rewritten at build time via `kustomize edit set image`. A custom `kustomizeconfig.yaml` is required because the image lives at `spec.steps[].run.image` (not the standard `spec.containers[].image`), so kustomize's default image transformer doesn't pick it up.

The labels collapse to a static set (Helm's `helm.sh/chart`, `app.kubernetes.io/instance`, `app.kubernetes.io/managed-by` were Helm-only and disappear). What remains: `app.kubernetes.io/name: testbench`, `app.kubernetes.io/version: 0.0.1`, `testkube.io/test-category: ragas-evaluation`, `app: testworkflows`. The version label is intentionally a placeholder — release CI rewrites it (or it can be dropped entirely; verify with the team if a version label is required by Testkube — it isn't, but it's nice to keep).

- [ ] **Step 1: Create `operator/config/testworkflows/setup-template.yaml`**

```yaml
apiVersion: testworkflows.testkube.io/v1
kind: TestWorkflowTemplate
metadata:
  name: setup-template
  namespace: testkube
  labels:
    app.kubernetes.io/name: testbench
    app.kubernetes.io/version: "0.0.1"
    testkube.io/test-category: ragas-evaluation
    app: testworkflows
spec:
  config:
    bucket:
      type: string
      description: "S3/MinIO bucket name containing the dataset"
    key:
      type: string
      description: "S3/MinIO object key (path to dataset file in .csv / .json / .parquet format)"
  steps:
    - name: setup
      artifacts:
        paths:
          - "data/datasets/experiment.json"
      run:
        image: ghcr.io/agentic-layer/testbench/testworkflows:0.0.1
        args:
          - setup.py
          - "{{ config.bucket }}"
          - "{{ config.key }}"
```

- [ ] **Step 2: Create `operator/config/testworkflows/run-template.yaml`**

```yaml
apiVersion: testworkflows.testkube.io/v1
kind: TestWorkflowTemplate
metadata:
  name: run-template
  namespace: testkube
  labels:
    app.kubernetes.io/name: testbench
    app.kubernetes.io/version: "0.0.1"
    testkube.io/test-category: ragas-evaluation
    app: testworkflows
spec:
  config:
    agentUrl:
      type: string
      description: "URL to the agent endpoint (A2A protocol)"
    experimentName:
      type: string
      description: "Name of the experiment for OTel labeling"
  steps:
    - name: run
      artifacts:
        paths:
          - "data/experiments/executed_experiment.json"
      run:
        image: ghcr.io/agentic-layer/testbench/testworkflows:0.0.1
        args:
          - run.py
          - "{{ config.agentUrl }}"
          - "{{ config.experimentName }}"
```

- [ ] **Step 3: Create `operator/config/testworkflows/evaluate-template.yaml`**

```yaml
apiVersion: testworkflows.testkube.io/v1
kind: TestWorkflowTemplate
metadata:
  name: evaluate-template
  namespace: testkube
  labels:
    app.kubernetes.io/name: testbench
    app.kubernetes.io/version: "0.0.1"
    testkube.io/test-category: ragas-evaluation
    app: testworkflows
spec:
  config:
    openAiBasePath:
      type: string
      description: "Base path for OpenAI API"
      default: ""
    openAiApiKey:
      type: string
      description: "API Key for OpenAI API"
      default: ""
  steps:
    - name: evaluate-results
      artifacts:
        paths:
          - "data/experiments/evaluated_experiment.json"
      run:
        image: ghcr.io/agentic-layer/testbench/testworkflows:0.0.1
        args:
          - evaluate.py
        env:
          - name: OPENAI_BASE_URL
            value: "{{ config.openAiBasePath }}"
          - name: OPENAI_API_KEY
            value: "{{ config.openAiApiKey }}"
```

- [ ] **Step 4: Create `operator/config/testworkflows/publish-template.yaml`**

```yaml
apiVersion: testworkflows.testkube.io/v1
kind: TestWorkflowTemplate
metadata:
  name: publish-template
  namespace: testkube
  labels:
    app.kubernetes.io/name: testbench
    app.kubernetes.io/version: "0.0.1"
    testkube.io/test-category: ragas-evaluation
    app: testworkflows
spec:
  config:
    experimentName:
      type: string
      description: "Name of the experiment for metric labeling"
  steps:
    - name: publish-metrics
      run:
        image: ghcr.io/agentic-layer/testbench/testworkflows:0.0.1
        args:
          - publish.py
          - "{{ config.experimentName }}"
          - "{{ execution.id }}"
          - "{{ execution.number }}"
```

- [ ] **Step 5: Create `operator/config/testworkflows/visualize-template.yaml`**

```yaml
apiVersion: testworkflows.testkube.io/v1
kind: TestWorkflowTemplate
metadata:
  name: visualize-template
  namespace: testkube
  labels:
    app.kubernetes.io/name: testbench
    app.kubernetes.io/version: "0.0.1"
    testkube.io/test-category: ragas-evaluation
    app: testworkflows
spec:
  config:
    experimentName:
      type: string
      description: "Name of the experiment for report labeling"
  steps:
    - name: visualize-metrics
      artifacts:
        paths:
          - "data/results/evaluation_report.html"
      run:
        image: ghcr.io/agentic-layer/testbench/testworkflows:0.0.1
        args:
          - visualize.py
          - "{{ config.experimentName }}"
          - "{{ execution.id }}"
          - "{{ execution.number }}"
```

- [ ] **Step 6: Create `operator/config/testworkflows/kustomizeconfig.yaml`**

This teaches kustomize where the image lives in a `TestWorkflowTemplate` so `kustomize edit set image testworkflows=...` rewrites the field at build time.

```yaml
images:
  - path: spec/steps/run/image
    kind: TestWorkflowTemplate
```

- [ ] **Step 7: Create `operator/config/testworkflows/kustomization.yaml`**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - setup-template.yaml
  - run-template.yaml
  - evaluate-template.yaml
  - publish-template.yaml
  - visualize-template.yaml

configurations:
  - kustomizeconfig.yaml

images:
  - name: ghcr.io/agentic-layer/testbench/testworkflows
    newTag: 0.0.1
```

- [ ] **Step 8: Verify the directory builds standalone**

Run:

```bash
kustomize build operator/config/testworkflows | kubectl apply --dry-run=client -f -
```

Expected: five lines like `testworkflowtemplate.testworkflows.testkube.io/setup-template created (dry run)` (one per template) and exit code 0.

- [ ] **Step 9: Verify image substitution works**

Run:

```bash
( cd operator/config/testworkflows && kustomize edit set image ghcr.io/agentic-layer/testbench/testworkflows=ghcr.io/agentic-layer/testbench/testworkflows:test-tag )
kustomize build operator/config/testworkflows | grep "image:"
```

Expected: five lines, all `image: ghcr.io/agentic-layer/testbench/testworkflows:test-tag`.

Then revert the kustomization back to `0.0.1`:

```bash
( cd operator/config/testworkflows && kustomize edit set image ghcr.io/agentic-layer/testbench/testworkflows=ghcr.io/agentic-layer/testbench/testworkflows:0.0.1 )
```

Confirm `operator/config/testworkflows/kustomization.yaml` shows `newTag: 0.0.1` again.

- [ ] **Step 10: Commit**

```bash
git add operator/config/testworkflows/
git commit -m "feat(operator): port testworkflow templates from Helm to kustomize"
```

---

## Task 2: Port Grafana dashboard JSONs and create dashboards kustomize directory

**Files:**
- Create: `operator/config/dashboards/kustomization.yaml`
- Create: `operator/config/dashboards/evaluation-dashboard.json` (copied from `chart/dashboards/evaluation-dashboard.json`)
- Create: `operator/config/dashboards/execution-details-dashboard.json` (copied from `chart/dashboards/execution-details-dashboard.json`)
- Create: `operator/config/dashboards/testkube-dashboard.json` (copied from `chart/dashboards/testkube-dashboard.json`)

**Background:** The chart's `grafana-dashboards.yaml` uses Helm's `Files.Get` to inline three JSON files into a ConfigMap. The kustomize equivalent is `configMapGenerator`, which builds the ConfigMap from `files:` entries. Use `disableNameSuffixHash: true` so the ConfigMap name stays stable across builds (matches the documented verification command `kubectl get configmap grafana-testkube-dashboard -n monitoring`).

- [ ] **Step 1: Copy the three dashboard JSON files**

```bash
cp chart/dashboards/evaluation-dashboard.json operator/config/dashboards/evaluation-dashboard.json
cp chart/dashboards/execution-details-dashboard.json operator/config/dashboards/execution-details-dashboard.json
cp chart/dashboards/testkube-dashboard.json operator/config/dashboards/testkube-dashboard.json
```

- [ ] **Step 2: Create `operator/config/dashboards/kustomization.yaml`**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: monitoring

generatorOptions:
  disableNameSuffixHash: true
  labels:
    app.kubernetes.io/name: testbench
    grafana_dashboard: "1"

configMapGenerator:
  - name: grafana-testkube-dashboard
    files:
      - evaluation-dashboard.json
      - execution-details-dashboard.json
      - testkube-dashboard.json
```

- [ ] **Step 3: Verify the directory builds**

Run:

```bash
kustomize build operator/config/dashboards | kubectl apply --dry-run=client -f -
```

Expected: `configmap/grafana-testkube-dashboard created (dry run)` and exit code 0.

- [ ] **Step 4: Verify the labels are applied**

Run:

```bash
kustomize build operator/config/dashboards | grep -A 4 "labels:"
```

Expected: includes both `app.kubernetes.io/name: testbench` and `grafana_dashboard: "1"`.

- [ ] **Step 5: Verify all three JSON keys are present in the ConfigMap data**

Run:

```bash
kustomize build operator/config/dashboards | grep -E "^  (evaluation-dashboard|execution-details-dashboard|testkube-dashboard)\.json:"
```

Expected: three matching lines, one per dashboard.

- [ ] **Step 6: Commit**

```bash
git add operator/config/dashboards/
git commit -m "feat(operator): port grafana dashboard configmap to kustomize"
```

---

## Task 3: Wire testworkflows and dashboards into operator/config/default

**Files:**
- Modify: `operator/config/default/kustomization.yaml`

**Background:** Adding both new directories as `resources:` includes them in every render of `operator/config/default`, which is what `make build-installer` and `make deploy` already use. The existing `namespace: testbench-operator-system` and `namePrefix: operator-` directives only apply to resources that don't pin their own namespace — TestWorkflowTemplates pin `testkube`, the dashboard ConfigMap pins `monitoring`, both via their sub-kustomizations, so they're unaffected.

`namePrefix: operator-` does still apply to the TestWorkflowTemplates and the ConfigMap unless we exclude them. We must exclude them, otherwise template names become `operator-setup-template` and the ConfigMap becomes `operator-grafana-testkube-dashboard`, which breaks the documented verification command and likely breaks any existing TestWorkflows referencing the templates by name. The fix: use the `namePrefix` field on a per-component basis is not directly supported, so we move `namePrefix` and `namespace` from the root kustomization down to a sub-component that only contains the operator's own resources, OR we keep them at root and override per-resource with `transformers`/`patches`. Simpler and idiomatic: introduce an intermediate `operator/config/manager-bundle/kustomization.yaml` that wraps `../crd`, `../rbac`, `../manager`, and the metrics service with the prefix and namespace; then `operator/config/default/kustomization.yaml` references `../manager-bundle`, `../testworkflows`, and `../dashboards` without applying the prefix/namespace at the root.

- [ ] **Step 1: Create the manager-bundle directory by extracting current root content**

Create `operator/config/manager-bundle/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: testbench-operator-system

namePrefix: operator-

resources:
  - ../crd
  - ../rbac
  - ../manager
  - metrics_service.yaml

patches:
  - path: manager_metrics_patch.yaml
    target:
      kind: Deployment
```

- [ ] **Step 2: Move `metrics_service.yaml` and `manager_metrics_patch.yaml` into the manager-bundle directory**

```bash
git mv operator/config/default/metrics_service.yaml operator/config/manager-bundle/metrics_service.yaml
git mv operator/config/default/manager_metrics_patch.yaml operator/config/manager-bundle/manager_metrics_patch.yaml
```

- [ ] **Step 3: Replace `operator/config/default/kustomization.yaml`**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../manager-bundle
  - ../testworkflows
  - ../dashboards
```

(The previous file's commented-out webhook/cert-manager/prometheus blocks were unused — drop them. They live unchanged in `operator/config/manager-bundle/kustomization.yaml` if needed later, but keep that file lean too — only reintroduce the comments if they were known to be referenced in any docs. They aren't, so omit.)

- [ ] **Step 4: Verify the full default tree builds**

Run:

```bash
kustomize build operator/config/default | kubectl apply --dry-run=client -f -
```

Expected: includes `customresourcedefinition.apiextensions.k8s.io/experiments.testbench.agentic-layer.ai`, `serviceaccount/operator-controller-manager`, `clusterrole/...`, `deployment.apps/operator-controller-manager`, `service/operator-controller-manager-metrics-service`, the five `testworkflowtemplate.testworkflows.testkube.io/<name>-template` (no `operator-` prefix), and `configmap/grafana-testkube-dashboard` (no `operator-` prefix). Exit code 0.

- [ ] **Step 5: Verify the operator's own resources still get the `operator-` prefix and `testbench-operator-system` namespace**

Run:

```bash
kustomize build operator/config/default | grep -E "^  name: operator-controller-manager$" | head -1
kustomize build operator/config/default | grep -E "^  namespace: testbench-operator-system$" | head -1
```

Expected: at least one match for each.

- [ ] **Step 6: Verify the testworkflows have no prefix and are in the testkube namespace**

Run:

```bash
kustomize build operator/config/default | grep -E "^  name: (setup|run|evaluate|publish|visualize)-template$"
kustomize build operator/config/default | grep -E "^  namespace: testkube$" | sort -u
```

Expected: five name lines (one per template), and the second command emits `  namespace: testkube` (one line, with `sort -u`).

- [ ] **Step 7: Commit**

```bash
git add operator/config/default/ operator/config/manager-bundle/
git commit -m "refactor(operator): split manager bundle into separate kustomize dir"
```

---

## Task 4: Extend the Makefile with a TESTWORKFLOW_IMG variable

**Files:**
- Modify: `operator/Makefile` (the `build-installer` target)

**Background:** Today's target stamps only the operator image:

```makefile
build-installer: manifests generate kustomize
	mkdir -p dist
	cd config/manager && $(KUSTOMIZE) edit set image controller=${IMG}
	$(KUSTOMIZE) build config/default > dist/install.yaml
```

Add a second `kustomize edit set image` invocation against `config/testworkflows` driven by `TESTWORKFLOW_IMG`. Default `TESTWORKFLOW_IMG` to `ghcr.io/agentic-layer/testbench/testworkflows:$(VERSION)` if `VERSION` exists, otherwise to a sentinel that surfaces a clear error. To stay aligned with the existing `IMG` ergonomics (which has no default — release CI sets it), give `TESTWORKFLOW_IMG` no default either; require both to be set when releasing, and document the local-dev fallback (`make build-installer IMG=... TESTWORKFLOW_IMG=...`).

- [ ] **Step 1: Locate the existing `build-installer` target**

Run:

```bash
grep -n "^build-installer:" operator/Makefile
```

Expected: a line number near the bottom of the file.

- [ ] **Step 2: Replace the target**

Replace these lines in `operator/Makefile`:

```makefile
build-installer: manifests generate kustomize ## Generate a consolidated YAML with CRDs and deployment.
	mkdir -p dist
	cd config/manager && $(KUSTOMIZE) edit set image controller=${IMG}
	$(KUSTOMIZE) build config/default > dist/install.yaml
```

with:

```makefile
build-installer: manifests generate kustomize ## Generate a consolidated YAML with CRDs, operator, testworkflow templates, and dashboards.
	@if [ -z "$(IMG)" ]; then echo "IMG must be set (e.g. IMG=ghcr.io/agentic-layer/testbench/operator:v0.1.0)" >&2; exit 1; fi
	@if [ -z "$(TESTWORKFLOW_IMG)" ]; then echo "TESTWORKFLOW_IMG must be set (e.g. TESTWORKFLOW_IMG=ghcr.io/agentic-layer/testbench/testworkflows:v0.1.0)" >&2; exit 1; fi
	mkdir -p dist
	cd config/manager && $(KUSTOMIZE) edit set image controller=${IMG}
	cd config/testworkflows && $(KUSTOMIZE) edit set image ghcr.io/agentic-layer/testbench/testworkflows=${TESTWORKFLOW_IMG}
	$(KUSTOMIZE) build config/default > dist/install.yaml
```

- [ ] **Step 3: Smoke-test the target locally**

Run:

```bash
make -C operator build-installer IMG=ghcr.io/agentic-layer/testbench/operator:v9.9.9 TESTWORKFLOW_IMG=ghcr.io/agentic-layer/testbench/testworkflows:v9.9.9
```

Expected: `operator/dist/install.yaml` is created, no errors.

- [ ] **Step 4: Verify the operator and testworkflow images are stamped correctly**

Run:

```bash
grep "image: ghcr.io/agentic-layer/testbench/operator" operator/dist/install.yaml
grep "image: ghcr.io/agentic-layer/testbench/testworkflows" operator/dist/install.yaml
```

Expected: at least one operator image line ending in `:v9.9.9`, and exactly five testworkflows image lines all ending in `:v9.9.9`.

- [ ] **Step 5: Verify the rendered install.yaml dry-runs cleanly**

Run:

```bash
kubectl apply --dry-run=client -f operator/dist/install.yaml
```

Expected: every resource reports `created (dry run)`. No errors.

- [ ] **Step 6: Reset the kustomize image edits so the committed defaults stay at `0.0.1`**

```bash
( cd operator/config/manager && kustomize edit set image controller=ghcr.io/agentic-layer/testbench/operator:0.0.1 )
( cd operator/config/testworkflows && kustomize edit set image ghcr.io/agentic-layer/testbench/testworkflows=ghcr.io/agentic-layer/testbench/testworkflows:0.0.1 )
```

Confirm with:

```bash
grep -A 2 "^images:" operator/config/manager/kustomization.yaml
grep -A 2 "^images:" operator/config/testworkflows/kustomization.yaml
```

Both should show `newTag: 0.0.1` (or `newTag: "0.0.1"`).

- [ ] **Step 7: Commit**

```bash
git add operator/Makefile operator/config/manager/kustomization.yaml operator/config/testworkflows/kustomization.yaml
git commit -m "build(operator): require TESTWORKFLOW_IMG in build-installer"
```

---

## Task 5: Update Tiltfile to use the unified kustomize tree

**Files:**
- Modify: `Tiltfile`

**Background:** Today the Tiltfile has two relevant blocks:

```python
# Deploy testbench Helm chart
k8s_yaml(helm(
    'chart',
    name='testbench',
    namespace='testkube',
    values=['chart/values.yaml'],
    set=[
        'image.tag=latest',
    ],
))

# Build and deploy the testbench operator (mirrors `make -C operator deploy`)
docker_build(
    'ghcr.io/agentic-layer/testbench/operator',
    'operator',
    dockerfile='operator/Dockerfile',
)
k8s_yaml(kustomize('operator/config/default'))
```

After this task: one `kustomize` call covers both, and a new `docker_build` for the testworkflows image is added so local code changes flow into Testkube workflow runs (closes a gap that existed under Helm too — the chart referenced `:latest` but Tilt never built that tag locally).

- [ ] **Step 1: Replace the helm block and operator block with a single unified block**

In `Tiltfile`, replace:

```python
# Deploy testbench Helm chart
k8s_yaml(helm(
    'chart',
    name='testbench',
    namespace='testkube',
    values=['chart/values.yaml'],
    set=[
        'image.tag=latest',
    ],
))

# Build and deploy the testbench operator (mirrors `make -C operator deploy`)
docker_build(
    'ghcr.io/agentic-layer/testbench/operator',
    'operator',
    dockerfile='operator/Dockerfile',
)
k8s_yaml(kustomize('operator/config/default'))
```

with:

```python
# Build the testworkflow image locally so code changes flow into Testkube runs.
docker_build(
    'ghcr.io/agentic-layer/testbench/testworkflows',
    '.',
    dockerfile='Dockerfile',
)

# Build the testbench operator image locally.
docker_build(
    'ghcr.io/agentic-layer/testbench/operator',
    'operator',
    dockerfile='operator/Dockerfile',
)

# Deploy the unified testbench install: operator + testworkflow templates + dashboard ConfigMap.
k8s_yaml(kustomize('operator/config/default'))
```

- [ ] **Step 2: Commit**

```bash
git add Tiltfile
git commit -m "feat(tilt): switch to unified kustomize install, build testworkflows image"
```

---

## Task 6: Tilt smoke test

**Files:** none changed.

**Background:** This is a manual verification that the full local environment still works.

- [ ] **Step 1: Run `tilt down` to clear any prior state**

```bash
tilt down --delete-namespaces || true
```

- [ ] **Step 2: Run `tilt up` and wait for green**

```bash
tilt up
```

Wait until the Tilt UI / CLI reports all resources green. Background-friendly: `tilt up` prints `Resources up-to-date`.

- [ ] **Step 3: Verify the operator pod is healthy**

```bash
kubectl get pods -n testbench-operator-system
```

Expected: one pod, `STATUS=Running`, `READY=2/2` (manager + kube-rbac-proxy if present, or `1/1` if metrics is via plain Service — match whatever was running before this change).

- [ ] **Step 4: Verify all five TestWorkflowTemplates exist in `testkube`**

```bash
kubectl get testworkflowtemplates -n testkube
```

Expected:

```
NAME                 AGE
evaluate-template    ...
publish-template     ...
run-template         ...
setup-template       ...
visualize-template   ...
```

(No `operator-` prefix.)

- [ ] **Step 5: Verify the dashboard ConfigMap exists in `monitoring`**

```bash
kubectl get configmap grafana-testkube-dashboard -n monitoring
```

Expected: one row, name `grafana-testkube-dashboard`.

- [ ] **Step 6: Run the example workflow end-to-end**

```bash
kubectl testkube run tw example-workflow --watch
```

Expected: workflow completes successfully (all phases pass).

- [ ] **Step 7: Tear down**

```bash
tilt down
```

- [ ] **Step 8: No commit needed** — this task is verification only. Note in the next commit message if any issues were found and fixed.

---

## Task 7: Add example overlays for documented customization

**Files:**
- Create: `operator/config/samples/overlays/custom-image-tag/kustomization.yaml`
- Create: `operator/config/samples/overlays/custom-image-tag/README.md`
- Create: `operator/config/samples/overlays/custom-dashboard-namespace/kustomization.yaml`
- Create: `operator/config/samples/overlays/custom-dashboard-namespace/README.md`

**Background:** These are user-facing examples linked from `install.adoc`. They demonstrate the kustomize-overlay pattern that replaces Helm's `--set` flags. Each overlay layers on top of a remote reference to the released `install.yaml` (so users can copy-paste without checking out the repo).

For local testing during this task, the overlays reference `../../../default` (a relative kustomize path). The README explains how to switch to the released-asset URL form for production use.

- [ ] **Step 1: Create `operator/config/samples/overlays/custom-image-tag/kustomization.yaml`**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# When using this overlay against a release artifact, replace the resources entry
# with the released install.yaml URL, e.g.:
#
#   resources:
#     - https://github.com/agentic-layer/testbench/releases/download/v0.1.0/install.yaml
#
# For in-tree development, this references the kustomize source directly.
resources:
  - ../../../default

images:
  - name: ghcr.io/agentic-layer/testbench/testworkflows
    newTag: my-custom-tag
```

- [ ] **Step 2: Create `operator/config/samples/overlays/custom-image-tag/README.md`**

```markdown
# Overlay: Custom Testworkflows Image Tag

Use this overlay to install the testbench with a custom testworkflows image tag,
for example when iterating on the pipeline scripts in a fork.

## Usage

Edit `kustomization.yaml`:
- Replace `resources:` with the released `install.yaml` URL for your target version.
- Replace `newTag:` with the tag you want to deploy.

Then apply:

```sh
kubectl apply -k .
```
```

- [ ] **Step 3: Create `operator/config/samples/overlays/custom-dashboard-namespace/kustomization.yaml`**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# When using this overlay against a release artifact, replace the resources entry
# with the released install.yaml URL.
resources:
  - ../../../default

# Move the Grafana dashboard ConfigMap to a custom namespace.
patches:
  - target:
      kind: ConfigMap
      name: grafana-testkube-dashboard
    patch: |
      - op: replace
        path: /metadata/namespace
        value: observability
```

- [ ] **Step 4: Create `operator/config/samples/overlays/custom-dashboard-namespace/README.md`**

```markdown
# Overlay: Custom Dashboard Namespace

Use this overlay when your Grafana sidecar watches a namespace other than
`monitoring`.

## Usage

Edit `kustomization.yaml`:
- Replace `resources:` with the released `install.yaml` URL for your target version.
- Replace `value: observability` with your target namespace.

The target namespace must exist before applying.

Then apply:

```sh
kubectl apply -k .
```
```

- [ ] **Step 5: Verify both overlays render correctly**

```bash
kustomize build operator/config/samples/overlays/custom-image-tag | grep "image: ghcr.io/agentic-layer/testbench/testworkflows" | head -1
```

Expected: `        image: ghcr.io/agentic-layer/testbench/testworkflows:my-custom-tag` (indentation may vary).

```bash
kustomize build operator/config/samples/overlays/custom-dashboard-namespace | grep -A 1 "name: grafana-testkube-dashboard" | grep "namespace:"
```

Expected: `  namespace: observability`.

- [ ] **Step 6: Commit**

```bash
git add operator/config/samples/overlays/
git commit -m "docs(operator): add example kustomize overlays for image tag and dashboard ns"
```

---

## Task 8: Drop the helm-chart job from release.yml; pass TESTWORKFLOW_IMG when building installer

**Files:**
- Modify: `.github/workflows/release.yml`

**Background:** Today the `operator` job runs `make build-installer` without `TESTWORKFLOW_IMG`. After Task 4, that target requires it. The job already builds & pushes the testworkflows image (via `helm-chart`'s `Build and push Docker image` step using `./.github/actions/build-push-image`). After dropping the helm-chart job, that image build moves into the operator job (or a new job that the operator job depends on).

The simplest restructure: collapse the two jobs into one. The `operator` job:
1. Build & push the operator image (Docker buildx).
2. Build & push the testworkflows image (the existing `./.github/actions/build-push-image` action).
3. Run `make build-installer` with both `IMG` and `TESTWORKFLOW_IMG`.
4. Continue with Flux push and release creation.

- [ ] **Step 1: Inspect the existing build-push-image action**

```bash
ls .github/actions/build-push-image/
cat .github/actions/build-push-image/action.yml | head -60
```

Note its `outputs` (`image-tags`) and what it builds. (It builds the testworkflows image at the repo root from `Dockerfile`.)

- [ ] **Step 2: Replace `.github/workflows/release.yml` content**

```yaml
name: Release

on:
  push:
    tags:
      - 'v*.*.*'

jobs:
  release:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      packages: write

    steps:
      - name: Checkout
        uses: 'actions/checkout@v6'
        with:
          fetch-depth: 0

      - name: Set VERSION from tag
        run: echo "VERSION=${GITHUB_REF_NAME#v}" >> $GITHUB_ENV

      - name: Login to GitHub Container Registry
        uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push testworkflows image
        uses: ./.github/actions/build-push-image
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push operator image
        working-directory: operator
        run: |
          make docker-buildx

      - name: Build installer
        working-directory: operator
        env:
          IMG: ghcr.io/agentic-layer/testbench/operator:${{ env.VERSION }}
          TESTWORKFLOW_IMG: ghcr.io/agentic-layer/testbench/testworkflows:${{ env.VERSION }}
        run: |
          make build-installer

      - name: Setup Flux CLI
        uses: fluxcd/flux2/action@main

      - name: Flux build & push
        working-directory: operator
        run: |
          make flux-push

      - name: Flux tag latest
        working-directory: operator
        run: |
          make flux-tag-latest

      - name: Write release notes
        run: |
          cat > /tmp/release-notes.md <<EOF
          ## Breaking change: Helm chart removed

          The Helm chart published to \`oci://ghcr.io/agentic-layer/charts/testbench\` is removed in this release.

          ### Migration

          1. \`helm uninstall testbench -n testkube\`
          2. \`kubectl apply -f https://github.com/agentic-layer/testbench/releases/download/${{ github.ref_name }}/install.yaml\`

          The \`TestWorkflowTemplate\` resources and the Grafana dashboard ConfigMap are recreated by the new install. In-flight TestWorkflows are interrupted.
          EOF

      - name: Create GitHub Release
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          tag: ${{ github.ref_name }}
        run: |
          gh release create "$tag" \
              --repo="$GITHUB_REPOSITORY" \
              --title="${tag#v}" \
              --notes-file /tmp/release-notes.md \
              operator/dist/install.yaml
```

(Note: `--generate-notes` is intentionally dropped in favor of the explicit migration banner for the cutover release. Restore it on subsequent releases by appending `--generate-notes` and removing the migration banner once the helm chart is no longer in living memory.)

- [ ] **Step 3: Verify YAML syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"
```

Expected: no output, exit code 0.

- [ ] **Step 4: Verify the action reference resolves**

```bash
ls .github/actions/build-push-image/action.yml
```

Expected: file exists.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci(release): drop helm chart job, build unified install.yaml"
```

---

## Task 9: Drop the helm-lint job from ci.yml

**Files:**
- Modify: `.github/workflows/ci.yml`

**Background:** Of the four `ci.yml` jobs (`python`, `push`, `helm`, `test-e2e`), only the `helm` job references the chart — and it does only `helm lint chart/`. After deleting `chart/`, that lint command has no target, so the entire `helm` job is dead.

The `test-e2e` job uses `tilt ci`, which picks up the Tiltfile changes from Task 5 automatically — no `ci.yml` change needed there. (Line 107's `helm rollback testkube` / `helm uninstall testkube` is testkube cleanup, not testbench cleanup; testkube continues to be installed via Helm by the Tiltfile, so leave that line untouched.)

- [ ] **Step 1: Delete the entire `helm` job**

In `.github/workflows/ci.yml`, delete lines that define the `helm:` job. The block to remove is:

```yaml
  helm:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: 'actions/checkout@v6'

      - name: Install Helm
        uses: azure/setup-helm@v4
        with:
          version: 'v3.14.0'

      - name: Lint Helm Chart
        run: helm lint chart/
```

The next job (`test-e2e:`) takes its place.

- [ ] **Step 2: Verify YAML syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

Expected: no output, exit code 0.

- [ ] **Step 3: Verify no other `chart/` references remain in ci.yml**

```bash
grep -n "chart/" .github/workflows/ci.yml
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: drop helm-lint job (chart removed)"
```

---

## Task 10: Rewrite install.adoc

**Files:**
- Modify: `docs/modules/how-to/pages/install.adoc`

**Background:** Drop the Helm chart instructions; replace with `kubectl apply -f` and a kustomize-overlay customization section linking the two committed example overlays.

- [ ] **Step 1: Replace the file content**

```asciidoc
= Install the Testbench

This guide walks you through installing the Testbench into an existing Kubernetes cluster with Testkube.

== Prerequisites

* A running Kubernetes cluster with `kubectl` configured
* https://testkube.io/[Testkube] installed in the `testkube` namespace
* (Optional) Grafana with the dashboard sidecar watching the `monitoring` namespace, if you want the bundled dashboards

== Step 1: Apply the installer

Install everything (operator + TestWorkflowTemplates + Grafana dashboard ConfigMap) with one command:

[source,shell]
----
kubectl apply -f https://github.com/agentic-layer/testbench/releases/download/<version>/install.yaml
----

Replace `<version>` with the release tag you want, for example `v0.1.0`.

The installer creates:

* The `testbench-operator-system` namespace and the operator controller manager.
* The `Experiment` Custom Resource Definition.
* Five `TestWorkflowTemplate` resources in the `testkube` namespace.
* A `grafana-testkube-dashboard` ConfigMap in the `monitoring` namespace (if present).

IMPORTANT: The `testkube` and `monitoring` namespaces must already exist. The installer assumes they are owned by your Testkube and Grafana installs.

== Step 2: Customize the installation (optional)

Customization happens via Kustomize overlays. Two examples are committed in the repository under `operator/config/samples/overlays/`:

* link:https://github.com/agentic-layer/testbench/tree/main/operator/config/samples/overlays/custom-image-tag[custom-image-tag] — override the testworkflows image tag.
* link:https://github.com/agentic-layer/testbench/tree/main/operator/config/samples/overlays/custom-dashboard-namespace[custom-dashboard-namespace] — move the dashboard ConfigMap to a different namespace.

Pattern: write a small `kustomization.yaml` that references the released `install.yaml` and adds patches:

[source,yaml]
----
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - https://github.com/agentic-layer/testbench/releases/download/v0.1.0/install.yaml

images:
  - name: ghcr.io/agentic-layer/testbench/testworkflows
    newTag: my-custom-tag
----

Apply with `kubectl apply -k <directory>`.

== Step 3: Verify the installation

Confirm the operator is running:

[source,shell]
----
kubectl get deployment -n testbench-operator-system
----

Confirm all five `TestWorkflowTemplate` resources are present:

[source,shell]
----
kubectl get testworkflowtemplates -n testkube
----

Expected output:

[source]
----
NAME                 AGE
evaluate-template    10s
publish-template     10s
run-template         10s
setup-template       10s
visualize-template   10s
----

== Step 4: Verify Grafana dashboards (optional)

If your Grafana install watches `monitoring` for dashboard ConfigMaps:

[source,shell]
----
kubectl get configmap grafana-testkube-dashboard -n monitoring
----

NOTE: The Grafana sidecar must be configured to watch ConfigMaps with the label `grafana_dashboard: "1"` in the target namespace.

== Migrating from the Helm chart

The Helm chart at `oci://ghcr.io/agentic-layer/charts/testbench` is no longer published. To migrate:

[source,shell]
----
helm uninstall testbench -n testkube
kubectl apply -f https://github.com/agentic-layer/testbench/releases/download/<version>/install.yaml
----

In-flight TestWorkflows are interrupted by the uninstall. Run the migration during a maintenance window if that matters.

== Next steps

With the Testbench installed, proceed to xref:testbench:how-to:first-workflow.adoc[Create Your First TestWorkflow] to define an experiment and run it against an agent.
```

- [ ] **Step 2: Commit**

```bash
git add docs/modules/how-to/pages/install.adoc
git commit -m "docs(install): rewrite install guide for unified install.yaml"
```

---

## Task 11: Update README.md and operator/README.md install snippets

**Files:**
- Modify: `README.md`
- Modify: `operator/README.md`

- [ ] **Step 1: Update `README.md` install snippet**

Locate the "Getting Started" block with `tilt up` (or any install reference) and append/replace the chart-install hint with a link to `install.adoc`. The local-dev `tilt up` flow does not change.

If `README.md` doesn't reference the chart explicitly, no changes needed — confirm with:

```bash
grep -n -i "helm\|chart" README.md
```

If matches exist, edit them to point to the unified install. If no matches, skip to Step 2.

- [ ] **Step 2: Update `operator/README.md`**

Add a short note near the top under "Description" (or wherever `make deploy` is first mentioned):

```markdown
> **For end users:** the recommended install is `kubectl apply -f` of the released `install.yaml`. See [docs/modules/how-to/pages/install.adoc](../docs/modules/how-to/pages/install.adoc). The `make deploy` and `make install` flows below are for operator development.
```

- [ ] **Step 3: Commit**

```bash
git add README.md operator/README.md
git commit -m "docs: point install snippets at the unified install.yaml"
```

---

## Task 12: Delete the chart/ directory

**Files:**
- Delete: `chart/` (entire directory)

**Background:** All content has been ported (templates → `operator/config/testworkflows/`, dashboards → `operator/config/dashboards/`). Helm helpers and NOTES.txt have no analog and are dropped.

- [ ] **Step 1: Delete the directory**

```bash
git rm -r chart/
```

- [ ] **Step 2: Verify nothing references `chart/` anymore**

```bash
grep -r "chart/" . --include="*.yaml" --include="*.yml" --include="*.py" --include="Makefile" --include="*.adoc" --include="*.md" --include="Tiltfile" 2>/dev/null | grep -v "^./docs/superpowers/" | grep -v "^./.git/"
```

Expected: no output (or only intentional references in plan/spec docs, which we exclude).

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: remove chart directory in favor of unified install.yaml"
```

---

## Task 13: Final verification

**Files:** none changed.

**Background:** Confirm the whole flow still works post-cleanup, before opening a PR.

- [ ] **Step 1: Build the installer one more time**

```bash
make -C operator build-installer IMG=ghcr.io/agentic-layer/testbench/operator:v9.9.9 TESTWORKFLOW_IMG=ghcr.io/agentic-layer/testbench/testworkflows:v9.9.9
kubectl apply --dry-run=client -f operator/dist/install.yaml > /tmp/dryrun.txt
echo "Resource count:"
grep -c "created (dry run)" /tmp/dryrun.txt
```

Expected: resource count includes:
- 1 Namespace (testbench-operator-system)
- 1 Experiment CRD
- ServiceAccount, ClusterRole(s), ClusterRoleBinding(s), RoleBinding(s) for the operator
- 1 Service (metrics)
- 1 Deployment (controller-manager)
- 5 TestWorkflowTemplates
- 1 ConfigMap (grafana dashboards)

Roughly 12-15 resources total.

- [ ] **Step 2: Reset the kustomize image edits before committing anything**

(See Task 4 Step 6 for the same sequence — repeat if `dist/install.yaml` was rebuilt with different tags during this task.)

```bash
( cd operator/config/manager && kustomize edit set image controller=ghcr.io/agentic-layer/testbench/operator:0.0.1 )
( cd operator/config/testworkflows && kustomize edit set image ghcr.io/agentic-layer/testbench/testworkflows=ghcr.io/agentic-layer/testbench/testworkflows:0.0.1 )
git status
```

Expected: only `operator/config/manager/kustomization.yaml` and `operator/config/testworkflows/kustomization.yaml` show up if reset was needed; commit if so.

- [ ] **Step 3: Run unit tests and quality checks**

```bash
uv run poe check
```

Expected: all checks pass.

- [ ] **Step 4: (Optional) Re-run the Tilt smoke test from Task 6**

If anything in Tasks 7-12 might have impacted the local environment, re-run the Task 6 smoke test.

- [ ] **Step 5: (Optional) Run the E2E test against the Tilt environment**

```bash
tilt up
# Wait for green
uv run poe test_e2e
tilt down
```

Expected: E2E test passes.

- [ ] **Step 6: Open a PR**

```bash
git push -u origin <branch-name>
gh pr create --title "feat: unify operator + chart into single install.yaml" --body "$(cat <<'EOF'
## Summary

Replaces the dual Helm-chart + operator-kustomize install with a single rendered `install.yaml` published as a GitHub Release asset.

- Ports the five `TestWorkflowTemplate` resources from `chart/templates/` to `operator/config/testworkflows/` (plain YAML kustomize).
- Ports the Grafana dashboard ConfigMap from `chart/templates/grafana-dashboards.yaml` to `operator/config/dashboards/` (`configMapGenerator`).
- Wires both into `operator/config/default` so `make build-installer` produces a complete `dist/install.yaml`.
- Drops the `helm-chart` job from `release.yml` and the `helm` job from `ci.yml`.
- Deletes `chart/`.

Spec: `docs/superpowers/specs/2026-05-05-unified-installer-design.md`
Plan: `docs/superpowers/plans/2026-05-06-unified-installer.md`

## Breaking change

The OCI Helm chart is no longer published. Migration:

```sh
helm uninstall testbench -n testkube
kubectl apply -f https://github.com/agentic-layer/testbench/releases/download/<version>/install.yaml
```

## Test plan

- [x] `make build-installer` produces a complete install.yaml with both operator and testworkflows images stamped.
- [x] `kubectl apply --dry-run=client -f install.yaml` succeeds.
- [x] `tilt up` brings up operator + TestWorkflowTemplates + dashboard ConfigMap.
- [x] `kubectl testkube run tw example-workflow --watch` passes end-to-end.
- [x] `uv run poe check` passes.
- [ ] Manual smoke test on a clean kind cluster.
EOF
)"
```

- [ ] **Step 7: No commit needed** — PR creation closes out the plan.
