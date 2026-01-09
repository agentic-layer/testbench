# -*- mode: Python -*-

# Increase Kubernetes upsert timeout for CRD installations and slow Helm charts (testkube)
update_settings(max_parallel_updates=10, k8s_upsert_timeout_secs=600)

# Load .env file for environment variables
load('ext://dotenv', 'dotenv')
dotenv()

v1alpha1.extension_repo(name='agentic-layer', url='https://github.com/agentic-layer/tilt-extensions', ref='v0.6.0')

v1alpha1.extension(name='cert-manager', repo_name='agentic-layer', repo_path='cert-manager')
load('ext://cert-manager', 'cert_manager_install')
cert_manager_install()

v1alpha1.extension(name='agent-runtime', repo_name='agentic-layer', repo_path='agent-runtime')
load('ext://agent-runtime', 'agent_runtime_install')
agent_runtime_install(version='0.16.0')

v1alpha1.extension(name='ai-gateway-litellm', repo_name='agentic-layer', repo_path='ai-gateway-litellm')
load('ext://ai-gateway-litellm', 'ai_gateway_litellm_install')
ai_gateway_litellm_install(version='0.3.2')

v1alpha1.extension(name='agent-gateway-krakend', repo_name='agentic-layer', repo_path='agent-gateway-krakend')
load('ext://agent-gateway-krakend', 'agent_gateway_krakend_install')
agent_gateway_krakend_install(version='0.4.1')

load('ext://helm_resource', 'helm_resource')
helm_resource(
    'testkube',
    'oci://docker.io/kubeshop/testkube',
    namespace='testkube',
    flags=['--version=2.4.2', '--create-namespace', '--values=deploy/local/testkube/values.yaml', '--wait',
    '--wait-for-jobs', '--timeout=10m'],
)

# Apply Kubernetes manifests
k8s_yaml(kustomize('deploy/local'))

k8s_resource('ai-gateway-litellm', port_forwards=['11001:4000'])
k8s_resource('weather-agent', port_forwards='11010:8000', labels=['agents'], resource_deps=['agent-runtime'])
k8s_resource('lgtm', port_forwards=['11000:3000', '4318:4318'])

# Declare Testkube resources
k8s_kind(
    '^TestWorkflow.*$',
    pod_readiness='ignore',
)

k8s_resource('ragas-evaluate-template', resource_deps=['testkube'])
k8s_resource('ragas-publish-template', resource_deps=['testkube'])
k8s_resource('ragas-run-template', resource_deps=['testkube'])
k8s_resource('ragas-setup-template', resource_deps=['testkube'])
k8s_resource('ragas-visualize-template', resource_deps=['testkube'])
k8s_resource('multi-turn-workflow', resource_deps=['testkube'])
