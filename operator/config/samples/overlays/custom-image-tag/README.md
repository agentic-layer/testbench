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
