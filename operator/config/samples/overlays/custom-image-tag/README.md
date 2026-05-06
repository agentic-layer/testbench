# Overlay: Custom Testworkflows Image Tag

Use this overlay to install the testbench with a custom testworkflows image tag,
for example when iterating on the pipeline scripts in a fork. The override
applies to the testworkflow pods that Testkube spawns; it does not change the
operator image.

## Usage

1. Download the released `install.yaml` into this directory:

   ```sh
   curl -L -o install.yaml \
     https://github.com/agentic-layer/testbench/releases/download/v0.1.0/install.yaml
   ```

2. Edit `kustomization.yaml`:

   - Change `resources:` to `- install.yaml`.
   - Replace `newTag:` with the tag you want to deploy.

3. Preview the rendered manifests:

   ```sh
   kustomize build .
   ```

4. Apply:

   ```sh
   kubectl apply -k .
   ```
