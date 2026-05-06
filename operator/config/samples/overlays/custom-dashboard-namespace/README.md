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
