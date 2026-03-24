/*
Copyright 2026.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package controller

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	apimeta "k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	testbenchv1alpha1 "github.com/agentic-layer/testbench/operator/api/v1alpha1"
)

const (
	conditionReady         = "Ready"
	conditionWorkflowReady = "WorkflowReady"
	otelConfigMapName      = "otel-config"
	otelEndpointKey        = "OTEL_EXPORTER_OTLP_ENDPOINT"
	defaultAgentPort       = "8000"
)

var (
	testWorkflowGVK = schema.GroupVersionKind{
		Group:   "testworkflows.testkube.io",
		Version: "v1",
		Kind:    "TestWorkflow",
	}
	testTriggerGVK = schema.GroupVersionKind{
		Group:   "tests.testkube.io",
		Version: "v1",
		Kind:    "TestTrigger",
	}
)

// experimentJSON is the JSON representation of experiment.json consumed by testbench scripts.
type experimentJSON struct {
	LLMAsAJudgeModel string         `json:"llm_as_a_judge_model,omitempty"`
	DefaultThreshold float64        `json:"default_threshold"`
	Scenarios        []scenarioJSON `json:"scenarios"`
}

type scenarioJSON struct {
	Name  string     `json:"name"`
	Steps []stepJSON `json:"steps"`
}

type stepJSON struct {
	Input        string          `json:"input"`
	Reference    *referenceJSON  `json:"reference,omitempty"`
	CustomValues json.RawMessage `json:"custom_values,omitempty"`
	Metrics      []metricJSON    `json:"metrics,omitempty"`
}

type referenceJSON struct {
	Response  string         `json:"response,omitempty"`
	ToolCalls []toolCallJSON `json:"tool_calls,omitempty"`
	Topics    []string       `json:"topics,omitempty"`
}

type toolCallJSON struct {
	Name string          `json:"name"`
	Args json.RawMessage `json:"args,omitempty"`
}

type metricJSON struct {
	MetricName string          `json:"metric_name"`
	Threshold  float64         `json:"threshold,omitempty"`
	Parameters json.RawMessage `json:"parameters,omitempty"`
}

// ExperimentReconciler reconciles an Experiment object.
type ExperimentReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=testbench.agentic-layer.ai,resources=experiments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=testbench.agentic-layer.ai,resources=experiments/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=testbench.agentic-layer.ai,resources=experiments/finalizers,verbs=update
// +kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=testworkflows.testkube.io,resources=testworkflows,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=tests.testkube.io,resources=testtriggers,verbs=get;list;watch;create;update;patch;delete

// Reconcile moves the cluster state closer to the desired state specified by the Experiment.
func (r *ExperimentReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)

	experiment := &testbenchv1alpha1.Experiment{}
	if err := r.Get(ctx, req.NamespacedName, experiment); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	var generatedResources []testbenchv1alpha1.GeneratedResource
	result, reconcileErr := r.reconcileResources(ctx, experiment, &generatedResources)

	if statusErr := r.updateStatus(ctx, experiment, generatedResources, result, reconcileErr); statusErr != nil {
		logger.Error(statusErr, "failed to update status")
		return ctrl.Result{}, statusErr
	}

	return ctrl.Result{}, reconcileErr
}

// reconcileResult tracks per-resource errors so status conditions can be set accurately.
type reconcileResult struct {
	workflowSkipped bool
	workflowErr     error
}

func (r *ExperimentReconciler) reconcileResources(
	ctx context.Context,
	experiment *testbenchv1alpha1.Experiment,
	generatedResources *[]testbenchv1alpha1.GeneratedResource,
) (reconcileResult, error) {
	var result reconcileResult
	if err := r.reconcileConfigMap(ctx, experiment, generatedResources); err != nil {
		return result, fmt.Errorf("reconciling ConfigMap: %w", err)
	}
	wfSkipped, err := r.reconcileTestWorkflow(ctx, experiment, generatedResources)
	if err != nil {
		result.workflowErr = err
		return result, fmt.Errorf("reconciling TestWorkflow: %w", err)
	}
	result.workflowSkipped = wfSkipped
	if err := r.reconcileTestTrigger(ctx, experiment, generatedResources); err != nil {
		return result, fmt.Errorf("reconciling TestTrigger: %w", err)
	}
	return result, nil
}

// reconcileConfigMap creates or updates the ConfigMap holding experiment.json.
func (r *ExperimentReconciler) reconcileConfigMap(
	ctx context.Context,
	experiment *testbenchv1alpha1.Experiment,
	generatedResources *[]testbenchv1alpha1.GeneratedResource,
) error {
	cmName := experiment.Name + "-experiment"
	cm := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      cmName,
			Namespace: experiment.Namespace,
		},
	}

	_, err := controllerutil.CreateOrUpdate(ctx, r.Client, cm, func() error {
		if err := controllerutil.SetControllerReference(experiment, cm, r.Scheme); err != nil {
			return err
		}
		data, buildErr := r.buildExperimentJSON(experiment)
		if buildErr != nil {
			return buildErr
		}
		cm.Data = map[string]string{
			"experiment.json": data,
		}
		return nil
	})
	if err != nil {
		return err
	}

	*generatedResources = append(*generatedResources, testbenchv1alpha1.GeneratedResource{
		Kind:      "ConfigMap",
		Name:      cm.Name,
		Namespace: cm.Namespace,
	})
	return nil
}

// buildExperimentJSON serializes the Experiment spec scenarios into the experiment.json format
// expected by the testbench scripts. For dataset mode, it returns an empty scenarios list.
func (r *ExperimentReconciler) buildExperimentJSON(experiment *testbenchv1alpha1.Experiment) (string, error) {
	exp := experimentJSON{
		LLMAsAJudgeModel: experiment.Spec.LLMAsAJudgeModel,
		DefaultThreshold: experiment.Spec.DefaultThreshold,
		Scenarios:        make([]scenarioJSON, 0, len(experiment.Spec.Scenarios)),
	}
	for _, scenario := range experiment.Spec.Scenarios {
		sj := scenarioJSON{
			Name:  scenario.Name,
			Steps: make([]stepJSON, 0, len(scenario.Steps)),
		}
		for _, step := range scenario.Steps {
			sj.Steps = append(sj.Steps, r.convertStep(step))
		}
		exp.Scenarios = append(exp.Scenarios, sj)
	}
	data, err := json.MarshalIndent(exp, "", "  ")
	if err != nil {
		return "", err
	}
	return string(data), nil
}

func (r *ExperimentReconciler) convertStep(step testbenchv1alpha1.Step) stepJSON {
	sj := stepJSON{Input: step.Input}
	if step.Reference != nil {
		ref := &referenceJSON{
			Response: step.Reference.Response,
			Topics:   step.Reference.Topics,
		}
		for _, tc := range step.Reference.ToolCalls {
			ref.ToolCalls = append(ref.ToolCalls, toolCallJSON{
				Name: tc.Name,
				Args: tc.Args.Raw,
			})
		}
		sj.Reference = ref
	}
	if step.CustomValues.Raw != nil {
		sj.CustomValues = step.CustomValues.Raw
	}
	for _, m := range step.Metrics {
		mj := metricJSON{
			MetricName: m.MetricName,
			Threshold:  m.Threshold,
		}
		if m.Parameters.Raw != nil {
			mj.Parameters = m.Parameters.Raw
		}
		sj.Metrics = append(sj.Metrics, mj)
	}
	return sj
}

// reconcileTestWorkflow creates or updates the Testkube TestWorkflow for the Experiment.
// It returns (skipped, error) where skipped is true when the CRD is not installed.
func (r *ExperimentReconciler) reconcileTestWorkflow(
	ctx context.Context,
	experiment *testbenchv1alpha1.Experiment,
	generatedResources *[]testbenchv1alpha1.GeneratedResource,
) (bool, error) {
	workflow := r.buildTestWorkflow(experiment)
	if err := controllerutil.SetControllerReference(experiment, workflow, r.Scheme); err != nil {
		return false, err
	}

	existing := &unstructured.Unstructured{}
	existing.SetGroupVersionKind(testWorkflowGVK)
	err := r.Get(ctx, types.NamespacedName{Name: workflow.GetName(), Namespace: workflow.GetNamespace()}, existing)
	if errors.IsNotFound(err) {
		if createErr := r.Create(ctx, workflow); createErr != nil {
			return false, createErr
		}
	} else if err != nil {
		if isCRDNotInstalled(err) {
			log.FromContext(ctx).Info("Testkube TestWorkflow CRD not installed; skipping TestWorkflow reconciliation")
			return true, nil
		}
		return false, err
	} else {
		existing.Object["spec"] = workflow.Object["spec"]
		existing.SetOwnerReferences(workflow.GetOwnerReferences())
		if updateErr := r.Update(ctx, existing); updateErr != nil {
			return false, updateErr
		}
	}

	*generatedResources = append(*generatedResources, testbenchv1alpha1.GeneratedResource{
		Kind:      "TestWorkflow",
		Name:      workflow.GetName(),
		Namespace: workflow.GetNamespace(),
	})
	return false, nil
}

// buildTestWorkflow constructs the desired TestWorkflow unstructured object.
func (r *ExperimentReconciler) buildTestWorkflow(experiment *testbenchv1alpha1.Experiment) *unstructured.Unstructured {
	agentURL := r.resolveAgentURL(experiment)

	// Build the list of phase templates to chain.
	var useTemplates []interface{}
	if experiment.Spec.Dataset != nil {
		useTemplates = append(useTemplates, map[string]interface{}{
			"name": "setup-template",
			"config": map[string]interface{}{
				"datasetUrl": r.resolveDatasetURL(experiment),
			},
		})
	}
	useTemplates = append(useTemplates,
		map[string]interface{}{
			"name": "run-template",
			"config": map[string]interface{}{
				"agentUrl": agentURL,
			},
		},
		map[string]interface{}{"name": "evaluate-template"},
		map[string]interface{}{"name": "publish-template"},
		map[string]interface{}{"name": "visualize-template"},
	)

	spec := map[string]interface{}{
		"container": map[string]interface{}{
			"env": []interface{}{
				map[string]interface{}{
					"name": otelEndpointKey,
					"valueFrom": map[string]interface{}{
						"configMapKeyRef": map[string]interface{}{
							"name": otelConfigMapName,
							"key":  otelEndpointKey,
						},
					},
				},
			},
		},
		"use": useTemplates,
	}

	// For scenarios mode, mount the pre-populated ConfigMap as the experiment file.
	if experiment.Spec.Dataset == nil {
		spec["content"] = map[string]interface{}{
			"files": []interface{}{
				map[string]interface{}{
					"path": "/data/datasets/experiment.json",
					"contentFrom": map[string]interface{}{
						"configMapKeyRef": map[string]interface{}{
							"name": experiment.Name + "-experiment",
							"key":  "experiment.json",
						},
					},
				},
			},
		}
	}

	workflow := &unstructured.Unstructured{
		Object: map[string]interface{}{
			"apiVersion": testWorkflowGVK.GroupVersion().String(),
			"kind":       testWorkflowGVK.Kind,
			"metadata": map[string]interface{}{
				"name":      experiment.Name + "-workflow",
				"namespace": experiment.Namespace,
			},
			"spec": spec,
		},
	}
	return workflow
}

// reconcileTestTrigger creates, updates, or deletes the Testkube TestTrigger.
func (r *ExperimentReconciler) reconcileTestTrigger(
	ctx context.Context,
	experiment *testbenchv1alpha1.Experiment,
	generatedResources *[]testbenchv1alpha1.GeneratedResource,
) error {
	triggerName := experiment.Name + "-trigger"

	if experiment.Spec.Trigger == nil || !experiment.Spec.Trigger.Enabled {
		// Delete trigger if it exists.
		existing := &unstructured.Unstructured{}
		existing.SetGroupVersionKind(testTriggerGVK)
		existing.SetName(triggerName)
		existing.SetNamespace(experiment.Namespace)
		if delErr := r.Delete(ctx, existing); delErr != nil && !errors.IsNotFound(delErr) {
			if isCRDNotInstalled(delErr) {
				return nil
			}
			return delErr
		}
		return nil
	}

	trigger := r.buildTestTrigger(experiment)
	if err := controllerutil.SetControllerReference(experiment, trigger, r.Scheme); err != nil {
		return err
	}

	existing := &unstructured.Unstructured{}
	existing.SetGroupVersionKind(testTriggerGVK)
	err := r.Get(ctx, types.NamespacedName{Name: triggerName, Namespace: experiment.Namespace}, existing)
	if errors.IsNotFound(err) {
		if createErr := r.Create(ctx, trigger); createErr != nil {
			return createErr
		}
	} else if err != nil {
		if isCRDNotInstalled(err) {
			log.FromContext(ctx).Info("Testkube TestTrigger CRD not installed; skipping TestTrigger reconciliation")
			return nil
		}
		return err
	} else {
		existing.Object["spec"] = trigger.Object["spec"]
		existing.SetOwnerReferences(trigger.GetOwnerReferences())
		if updateErr := r.Update(ctx, existing); updateErr != nil {
			return updateErr
		}
	}

	*generatedResources = append(*generatedResources, testbenchv1alpha1.GeneratedResource{
		Kind:      "TestTrigger",
		Name:      triggerName,
		Namespace: experiment.Namespace,
	})
	return nil
}

// buildTestTrigger constructs the desired TestTrigger unstructured object.
func (r *ExperimentReconciler) buildTestTrigger(experiment *testbenchv1alpha1.Experiment) *unstructured.Unstructured {
	agentNs := experiment.Spec.AgentRef.Namespace
	if agentNs == "" {
		agentNs = experiment.Namespace
	}

	concurrencyPolicy := "allow"
	if experiment.Spec.Trigger != nil && experiment.Spec.Trigger.ConcurrencyPolicy != "" {
		concurrencyPolicy = strings.ToLower(experiment.Spec.Trigger.ConcurrencyPolicy)
	}

	return &unstructured.Unstructured{
		Object: map[string]interface{}{
			"apiVersion": testTriggerGVK.GroupVersion().String(),
			"kind":       testTriggerGVK.Kind,
			"metadata": map[string]interface{}{
				"name":      experiment.Name + "-trigger",
				"namespace": experiment.Namespace,
			},
			"spec": map[string]interface{}{
				"resource": "deployment",
				"resourceSelector": map[string]interface{}{
					"name":      experiment.Spec.AgentRef.Name,
					"namespace": agentNs,
				},
				"event":             r.resolveTriggerEvent(experiment),
				"action":            "run",
				"execution":         "testworkflow",
				"concurrencyPolicy": concurrencyPolicy,
				"testSelector": map[string]interface{}{
					"name":      experiment.Name + "-workflow",
					"namespace": experiment.Namespace,
				},
				"disabled": false,
			},
		},
	}
}

// updateStatus updates Ready and WorkflowReady conditions and the generatedResources list.
func (r *ExperimentReconciler) updateStatus(
	ctx context.Context,
	experiment *testbenchv1alpha1.Experiment,
	generatedResources []testbenchv1alpha1.GeneratedResource,
	result reconcileResult,
	reconcileErr error,
) error {
	experiment.Status.GeneratedResources = generatedResources

	readyStatus := metav1.ConditionTrue
	readyReason := "ReconcileSucceeded"
	readyMsg := "All resources reconciled successfully"
	if reconcileErr != nil {
		readyStatus = metav1.ConditionFalse
		readyReason = "ReconcileFailed"
		readyMsg = reconcileErr.Error()
	}
	apimeta.SetStatusCondition(&experiment.Status.Conditions, metav1.Condition{
		Type:               conditionReady,
		Status:             readyStatus,
		ObservedGeneration: experiment.Generation,
		Reason:             readyReason,
		Message:            readyMsg,
	})

	wfStatus := metav1.ConditionTrue
	wfReason := "WorkflowCreated"
	wfMsg := "TestWorkflow created successfully"
	if result.workflowErr != nil {
		wfStatus = metav1.ConditionFalse
		wfReason = "WorkflowNotReady"
		wfMsg = result.workflowErr.Error()
	} else if result.workflowSkipped {
		wfStatus = metav1.ConditionFalse
		wfReason = "CRDNotInstalled"
		wfMsg = "TestWorkflow CRD not installed; workflow was not created"
	}
	apimeta.SetStatusCondition(&experiment.Status.Conditions, metav1.Condition{
		Type:               conditionWorkflowReady,
		Status:             wfStatus,
		ObservedGeneration: experiment.Generation,
		Reason:             wfReason,
		Message:            wfMsg,
	})

	return r.Status().Update(ctx, experiment)
}

// resolveTriggerEvent returns the trigger event, defaulting to "modified".
func (r *ExperimentReconciler) resolveTriggerEvent(experiment *testbenchv1alpha1.Experiment) string {
	if experiment.Spec.Trigger != nil && experiment.Spec.Trigger.Event != "" {
		return strings.ToLower(experiment.Spec.Trigger.Event)
	}
	return "modified"
}

// resolveAgentURL builds the in-cluster DNS URL for the agent service.
func (r *ExperimentReconciler) resolveAgentURL(experiment *testbenchv1alpha1.Experiment) string {
	ns := experiment.Spec.AgentRef.Namespace
	if ns == "" {
		ns = experiment.Namespace
	}
	return fmt.Sprintf("http://%s.%s:%s", experiment.Spec.AgentRef.Name, ns, defaultAgentPort)
}

// resolveDatasetURL extracts the dataset URL from the DatasetSource.
func (r *ExperimentReconciler) resolveDatasetURL(experiment *testbenchv1alpha1.Experiment) string {
	if experiment.Spec.Dataset == nil {
		return ""
	}
	if experiment.Spec.Dataset.URL != "" {
		return experiment.Spec.Dataset.URL
	}
	if experiment.Spec.Dataset.S3 != nil {
		return fmt.Sprintf("s3://%s/%s", experiment.Spec.Dataset.S3.Bucket, experiment.Spec.Dataset.S3.Key)
	}
	return ""
}

// SetupWithManager sets up the controller with the Manager.
func (r *ExperimentReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&testbenchv1alpha1.Experiment{}).
		Owns(&corev1.ConfigMap{}).
		Complete(r)
}

// isCRDNotInstalled returns true when the error indicates the target CRD is not registered.
func isCRDNotInstalled(err error) bool {
	return apimeta.IsNoMatchError(err)
}
