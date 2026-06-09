# -*- mode: Python -*-

# Increase Kubernetes upsert timeout for CRD installations and slow Helm charts (testkube)
update_settings(max_parallel_updates=10, k8s_upsert_timeout_secs=600)

# Load .env file for environment variables
load('ext://dotenv', 'dotenv')
dotenv()

v1alpha1.extension_repo(name='agentic-layer', url='https://github.com/agentic-layer/tilt-extensions', ref='v0.18.0')

v1alpha1.extension(name='cert-manager', repo_name='agentic-layer', repo_path='cert-manager')
load('ext://cert-manager', 'cert_manager_install')
cert_manager_install()

v1alpha1.extension(name='agent-runtime', repo_name='agentic-layer', repo_path='agent-runtime')
load('ext://agent-runtime', 'agent_runtime_install')
agent_runtime_install(version='0.28.1')

v1alpha1.extension(name='ai-gateway-litellm', repo_name='agentic-layer', repo_path='ai-gateway-litellm')
load('ext://ai-gateway-litellm', 'ai_gateway_litellm_install')
ai_gateway_litellm_install(version='0.10.0')

v1alpha1.extension(name='agent-gateway-krakend', repo_name='agentic-layer', repo_path='agent-gateway-krakend')
load('ext://agent-gateway-krakend', 'agent_gateway_krakend_install')
agent_gateway_krakend_install(version='0.7.0')

v1alpha1.extension(name='tool-gateway-agentgateway', repo_name='agentic-layer', repo_path='tool-gateway-agentgateway')
load('ext://tool-gateway-agentgateway', 'tool_gateway_agentgateway_install')
tool_gateway_agentgateway_install(version='0.5.0', instance=False)

# Pre-create testkube namespace to avoid race condition with kustomize resources
k8s_yaml(blob('''
apiVersion: v1
kind: Namespace
metadata:
  name: testkube
'''))

load('ext://helm_resource', 'helm_resource')
helm_resource(
    'testkube',
    'oci://docker.io/kubeshop/testkube',
    namespace='testkube',
    flags=['--version=2.9.3', '--values=deploy/local/testkube/values.yaml', '--wait',
    '--wait-for-jobs', '--timeout=10m'],
)

# Build the testbench operator image locally.
docker_build(
    'ghcr.io/agentic-layer/testbench/operator',
    'operator',
    dockerfile='operator/Dockerfile',
)

# Build the testworkflows image locally and tag it as :latest so the templates'
# IfNotPresent kubelet check finds it in the runtime's image store. Tilt does
# NOT rewrite the templates' image refs because Testkube's API server resolves
# the image manifest from the remote registry before scheduling the pod — so
# the tag must match a real published tag (which :latest does).
local_resource(
    'testworkflows-image',
    cmd='docker build -t ghcr.io/agentic-layer/testbench/testworkflows:latest .',
    deps=['testbench', 'Dockerfile', 'pyproject.toml', 'uv.lock'],
    labels=['testbench'],
)

# Deploy the unified testbench install: operator + testworkflow templates + dashboard ConfigMap.
k8s_yaml(kustomize('operator/config/default'))

# Apply local development manifests
k8s_yaml(kustomize('deploy/local'))

k8s_resource('ai-gateway', port_forwards=['11001:4000'])
k8s_resource('agent-runtime-configuration', resource_deps=['agent-runtime'])
k8s_resource('weather-agent', port_forwards='11010:8000', labels=['agents'], resource_deps=['agent-runtime'])
k8s_resource('tool-gateway', labels=['agentic-layer'], resource_deps=['agent-runtime'], port_forwards='11005:80')
k8s_resource('weather-mcp-server:toolserver', port_forwards='11020:8000', labels=['agents'], resource_deps=['agent-runtime'])
k8s_resource('weather-mcp-server:toolroute', labels=['agents'], resource_deps=['agent-runtime', 'weather-mcp-server:toolserver'])
k8s_resource('lgtm', port_forwards=['11000:3000', '4318:4318'])

# Declare Testkube resources
k8s_kind(
    '^Test(Workflow.*|Trigger.*)$',
    pod_readiness='ignore',
)

# Declare testbench Experiment resources
k8s_kind(
    'Experiment',
    pod_readiness='ignore',
)

k8s_resource('evaluate-template', resource_deps=['testkube'])
k8s_resource('publish-template', resource_deps=['testkube'])
k8s_resource('run-template', resource_deps=['testkube'])
k8s_resource('setup-template', resource_deps=['testkube'])
k8s_resource('visualize-template', resource_deps=['testkube'])
k8s_resource('operator-controller-manager', labels=['testbench-operator'])
k8s_resource('example-experiment', resource_deps=['operator-controller-manager', 'ai-gateway'])
