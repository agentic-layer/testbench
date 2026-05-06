# Overlay: Custom Dashboard Namespace

Use this overlay when your Grafana sidecar watches a namespace other than
`monitoring`.

## Usage

1. Download the released `install.yaml` into this directory:

   ```sh
   curl -L -o install.yaml \
     https://github.com/agentic-layer/testbench/releases/download/v0.1.0/install.yaml
   ```

2. Edit `kustomization.yaml`:

   - Change `resources:` to `- install.yaml`.
   - Replace `value: observability` with your target namespace.

3. Ensure the target namespace exists.

4. Preview the rendered manifests:

   ```sh
   kustomize build .
   ```

5. Apply:

   ```sh
   kubectl apply -k .
   ```
