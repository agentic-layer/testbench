# Unified Testbench Installer Design

**Date:** 2026-05-05
**Status:** Proposed

## Problem

Installing the testbench in a Kubernetes cluster currently requires two separate steps with two different tools:

1. `helm upgrade --install testbench oci://ghcr.io/agentic-layer/charts/testbench` — installs the `TestWorkflowTemplate` CRs (5 phases) and the Grafana dashboard ConfigMap.
2. `kubectl apply -k operator/config/default` (or `make deploy`) — installs the operator's CRDs, RBAC, controller manager Deployment, and metrics service.

The two pieces ship via different mechanisms, land in different namespaces, and have different release cadences. Users have to learn both. Helm's CRD lifecycle (no upgrade for `crds/`, ownership weirdness in `templates/`) is a known weak spot for an operator that owns a CRD.

## Goal

A single command installs the entire testbench:

```shell
kubectl apply -f https://github.com/agentic-layer/testbench/releases/download/v<version>/installer.yaml
```

`installer.yaml` is a fully rendered, version-pinned manifest published as a GitHub Release asset. The Helm chart is retired in the same release.

## Non-Goals

- Adopting existing Helm-installed deployments in place. Existing users run `helm uninstall` then `kubectl apply -f installer.yaml` (hard cutover).
- Operator-managed runtime reconciliation of TestWorkflowTemplates or the dashboard ConfigMap. They remain static manifests in `installer.yaml`.
- A `latest`-floating install URL. Every documented install pins a version.

## Design

### Distribution model

Standard kubebuilder operator-distribution shape: kustomize tree → `make build-installer` renders to one YAML → CI uploads as a GitHub Release asset.

The kustomize tree is rooted at `operator/config/default`. It already includes the operator's CRDs, RBAC, manager Deployment, and metrics service. We extend it to also include the TestWorkflowTemplates and the Grafana dashboard ConfigMap, so a single `kustomize build operator/config/default` produces the full install.

### Namespace layout (unchanged from today)

| Resource                     | Namespace                    | Created by installer? |
|------------------------------|------------------------------|-----------------------|
| Operator manager Deployment, ServiceAccount, metrics Service | `testbench-operator-system` | Yes |
| Operator CRDs, ClusterRole(Binding) | cluster-scoped               | Yes (cluster-scoped)  |
| `TestWorkflowTemplate` CRs (5 phases) | `testkube`                   | No (must pre-exist)   |
| Grafana dashboard ConfigMap  | `monitoring`                 | No (must pre-exist)   |

Rationale:
- `testbench-operator-system` is the testbench's own namespace; the installer is responsible for creating it.
- `testkube` is owned by the Testkube install. `TestWorkflowTemplate` CRs must live there to be picked up by the Testkube controller.
- `monitoring` is owned by whoever installed Grafana. Assumed to pre-exist.

### Repo layout changes

**Added:**

- `operator/config/testworkflows/` — kustomize directory holding the five templates, ported from `chart/templates/`:
  - `setup-template.yaml`
  - `run-template.yaml`
  - `evaluate-template.yaml`
  - `publish-template.yaml`
  - `visualize-template.yaml`
  - `kustomization.yaml` (sets `namespace: testkube` and lists the five resources)

  All Helm interpolation (`{{ .Values.image.repository }}`, `{{ .Values.image.tag | default .Chart.AppVersion }}`, etc.) is replaced with literal values that kustomize `images:` transforms can rewrite at build time.

- `operator/config/dashboards/` — kustomize directory holding the Grafana dashboard ConfigMap:
  - `evaluation-dashboard.json`, `execution-details-dashboard.json`, `testkube-dashboard.json` (relocated from `chart/dashboards/`).
  - `kustomization.yaml` — uses a `configMapGenerator` to bundle the three JSON files into a single ConfigMap named `grafana-testkube-dashboard`, applies the `grafana_dashboard: "1"` label, and sets `namespace: monitoring`. `generatorOptions.disableNameSuffixHash: true` keeps the ConfigMap name stable across builds (Grafana's sidecar matches by label, not name, but the stable name preserves the documented verification command).

- `operator/config/samples/overlays/custom-image-tag/` — example overlay showing how to override the testworkflows image tag via `kustomize edit set image` or an `images:` patch.
- `operator/config/samples/overlays/custom-dashboard-namespace/` — example overlay showing how to retarget the dashboard ConfigMap to a different namespace.
- `docs/modules/how-to/pages/install.adoc` — rewritten (see Documentation section).

**Modified:**

- `operator/config/default/kustomization.yaml`:
  - Add `../testworkflows` and `../dashboards` to `resources:`.
  - Add an `images:` block so `make build-installer IMG=... TESTWORKFLOW_IMG=...` stamps both the operator and the testworkflows image tags.
  - Keep `namespace: testbench-operator-system`. This only applies to resources without an explicit namespace — the TestWorkflowTemplates and dashboard ConfigMap pin their own via their sub-`kustomization.yaml`.

- `operator/Makefile` — extend the `build-installer` target to accept a `TESTWORKFLOW_IMG` variable (alongside the existing `IMG`) and apply both image transforms before rendering. Output stays at `operator/dist/installer.yaml`.

- `Tiltfile`:
  - Remove the `k8s_yaml(helm('chart', ...))` block.
  - Replace the existing `k8s_yaml(kustomize('operator/config/default'))` with the same call — but now it covers everything.
  - Add `docker_build('ghcr.io/agentic-layer/testbench/testworkflows', '.', dockerfile='Dockerfile')` so local code changes flow into Testkube workflow runs. (This closes a small existing gap and is in scope for this change.)

- `docs/modules/how-to/pages/install.adoc` — rewritten around `kubectl apply -f`; the Helm `--set` table is replaced by a kustomize-overlay section linking the two committed examples.

- `README.md` — install snippet updated to the `kubectl apply -f installer.yaml` form.

- CI workflow that publishes the OCI Helm chart — replaced by a step that uploads `operator/dist/installer.yaml` as a GitHub Release asset on tag push.

**Deleted:**

- `chart/` — entire directory, including `Chart.yaml`, `values.yaml`, `templates/`, `dashboards/`.
- Any CI step that pushes to `oci://ghcr.io/agentic-layer/charts/testbench`.

### Customization

Without Helm values, customization moves to documented kustomize overlays. Two example overlays are committed under `operator/config/samples/overlays/` as copy-paste starting points:

- `custom-image-tag/` — overrides the testworkflows image tag.
- `custom-dashboard-namespace/` — moves the dashboard ConfigMap to a non-default namespace.

`install.adoc` documents the pattern: write a small `kustomization.yaml` whose `resources:` references the released `installer.yaml`, then add the desired patches.

### Build & release

Per release tag `v<x.y.z>`:

1. CI builds and pushes the operator image to `ghcr.io/agentic-layer/testbench/operator:v<x.y.z>`.
2. CI builds and pushes the testworkflows image to `ghcr.io/agentic-layer/testbench/testworkflows:v<x.y.z>`.
3. CI runs `make -C operator build-installer IMG=...:v<x.y.z> TESTWORKFLOW_IMG=...:v<x.y.z>`, producing `operator/dist/installer.yaml` with both tags pinned.
4. CI uploads `operator/dist/installer.yaml` as an asset on the GitHub Release for the tag.
5. The OCI Helm chart push step is removed.

No `latest` floating asset is published. Every documented install URL pins a version.

### Tilt development flow

After the change, the Tilt environment installs everything from one kustomize tree:

- Operator image: `docker_build('ghcr.io/agentic-layer/testbench/operator', 'operator', dockerfile='operator/Dockerfile')` (unchanged).
- Testworkflows image: new `docker_build('ghcr.io/agentic-layer/testbench/testworkflows', '.', dockerfile='Dockerfile')`.
- Manifests: `k8s_yaml(kustomize('operator/config/default'))` replaces the previous helm + kustomize pair.

The previous `helm_resource` plumbing for the testbench chart is removed. Testkube and the platform operators continue to install via their existing Tilt extensions.

### Migration

Hard cutover. The release notes for the cutover version include a breaking-change banner:

> The Helm chart is removed in v<version>. Run `helm uninstall testbench -n testkube` before applying `installer.yaml`. The five `TestWorkflowTemplate` CRs and the Grafana dashboard ConfigMap will be recreated by the new install. In-flight TestWorkflows will be interrupted.

No adopt-in-place script.

### Documentation updates

- `docs/modules/how-to/pages/install.adoc`:
  - Prerequisites unchanged (Kubernetes + Testkube + Grafana stack for the dashboard).
  - Step 1: replace `helm upgrade --install` with `kubectl apply -f https://github.com/agentic-layer/testbench/releases/download/v<version>/installer.yaml`.
  - Step 2: replace the Helm `--set` table with a "Customizing the installation" section showing the kustomize-overlay pattern; link the two committed example overlays.
  - Verification steps (`kubectl get testworkflowtemplates -n testkube`, `kubectl get configmap -n monitoring`) unchanged.
- `README.md`: one-line install snippet update.
- `operator/README.md`: clarify that `make deploy` and `make install` remain valid for operator-developer iteration; production users follow `install.adoc`.

## Testing

- **Static check (CI):** after `make build-installer`, run `kubectl apply --dry-run=client -f operator/dist/installer.yaml` to catch broken YAML or schema regressions before publishing.
- **Overlay smoke (CI):** `kustomize build operator/config/samples/overlays/custom-image-tag` and `... /custom-dashboard-namespace` produce non-empty output and are valid YAML.
- **E2E:** the existing `tests_e2e/test_e2e.py` exercises the full 4-phase pipeline via Testkube against the Tilt environment, which now installs everything from the unified kustomize tree. A green `uv run poe test_e2e` validates the integration end to end.
- **Manual smoke:** on a clean kind cluster, `tilt down && tilt up` brings everything up; confirm:
  - Operator pod healthy in `testbench-operator-system`.
  - Five `TestWorkflowTemplate` resources present in `testkube`.
  - `grafana-testkube-dashboard` ConfigMap present in `monitoring`.
  - `kubectl testkube run tw example-workflow --watch` runs to completion.

## Open Questions

None — all design decisions captured above.

## Out of Scope

- Operator-managed runtime reconciliation of the TestWorkflowTemplates or dashboard ConfigMap (option C from the brainstorm; rejected as a bigger change with no immediate UX win once `installer.yaml` exists).
- Republishing the chart in parallel for a deprecation window (option C from the migration brainstorm; rejected because the project is pre-1.0 with a small known user base).
- A `latest` floating install URL.
