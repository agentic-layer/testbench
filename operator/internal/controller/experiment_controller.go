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
	"k8s.io/client-go/tools/record"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/predicate"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	runtimev1alpha1 "github.com/agentic-layer/agent-runtime-operator/api/v1alpha1"
	testbenchv1alpha1 "github.com/agentic-layer/testbench/operator/api/v1alpha1"
)

const (
	conditionReady            = "Ready"
	conditionWorkflowReady    = "WorkflowReady"
	defaultAgentPort          = "8000"
	testkubeNamespace         = "testkube"
	defaultAiGatewayNamespace = "ai-gateway"
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
	DefaultThreshold *float64       `json:"default_threshold,omitempty"`
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
	Response          string         `json:"response,omitempty"`
	ToolCalls         []toolCallJSON `json:"tool_calls,omitempty"`
	Topics            []string       `json:"topics,omitempty"`
	RetrievedContexts []string       `json:"retrieved_contexts,omitempty"`
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
	Scheme   *runtime.Scheme
	Recorder record.EventRecorder
}

// +kubebuilder:rbac:groups=testbench.agentic-layer.ai,resources=experiments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=testbench.agentic-layer.ai,resources=experiments/status,verbs=get;update;patch
// +kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=events,verbs=create;patch
// +kubebuilder:rbac:groups=testworkflows.testkube.io,resources=testworkflows,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=tests.testkube.io,resources=testtriggers,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=runtime.agentic-layer.ai,resources=aigateways,verbs=get;list;watch

// Reconcile moves the cluster state closer to the desired state specified by the Experiment.
func (r *ExperimentReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)

	experiment := &testbenchv1alpha1.Experiment{}
	if err := r.Get(ctx, req.NamespacedName, experiment); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	// Handle deletion: delete the anchor ConfigMap (cascades to all owned resources).
	if !experiment.DeletionTimestamp.IsZero() {
		anchorName := resourceName(experiment.Name, experiment.Namespace, "anchor")
		anchor := &corev1.ConfigMap{
			ObjectMeta: metav1.ObjectMeta{
				Name:      anchorName,
				Namespace: testkubeNamespace,
			},
		}
		if err := r.Delete(ctx, anchor); err != nil && !errors.IsNotFound(err) {
			logger.Error(err, "failed to delete anchor ConfigMap", "name", anchorName)
		} else if r.Recorder != nil {
			r.Recorder.Event(experiment, corev1.EventTypeNormal, EventAnchorDeleted,
				fmt.Sprintf("Deleted anchor ConfigMap %s", anchorName))
		}
		return ctrl.Result{}, nil
	}

	anchorUID, err := r.reconcileAnchor(ctx, experiment)
	if err != nil {
		return ctrl.Result{}, fmt.Errorf("reconciling anchor: %w", err)
	}

	result, reconcileErr := r.reconcileResources(ctx, experiment, anchorUID)

	if reconcileErr != nil && r.Recorder != nil {
		r.Recorder.Event(experiment, corev1.EventTypeWarning, EventReconcileError, reconcileErr.Error())
	}

	if statusErr := r.updateStatus(ctx, experiment, result, reconcileErr); statusErr != nil {
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
	anchorUID types.UID,
) (reconcileResult, error) {
	var result reconcileResult
	if err := r.reconcileConfigMap(ctx, experiment, anchorUID); err != nil {
		return result, fmt.Errorf("reconciling ConfigMap: %w", err)
	}
	aiGateway, err := r.resolveAiGateway(ctx, experiment)
	if err != nil {
		return result, fmt.Errorf("resolving AiGateway: %w", err)
	}
	wfSkipped, err := r.reconcileTestWorkflow(ctx, experiment, aiGateway, anchorUID)
	if err != nil {
		result.workflowErr = err
		return result, fmt.Errorf("reconciling TestWorkflow: %w", err)
	}
	result.workflowSkipped = wfSkipped
	if err := r.reconcileTestTrigger(ctx, experiment, anchorUID); err != nil {
		return result, fmt.Errorf("reconciling TestTrigger: %w", err)
	}
	return result, nil
}

// toUnstructuredLabels converts map[string]string to map[string]interface{} for use in unstructured objects.
func toUnstructuredLabels(labels map[string]string) map[string]interface{} {
	out := make(map[string]interface{}, len(labels))
	for k, v := range labels {
		out[k] = v
	}
	return out
}

// anchorOwnerReference builds an OwnerReference pointing to the anchor ConfigMap.
func anchorOwnerReference(experimentName, experimentNamespace string, uid types.UID) metav1.OwnerReference {
	isController := true
	return metav1.OwnerReference{
		APIVersion: "v1",
		Kind:       "ConfigMap",
		Name:       resourceName(experimentName, experimentNamespace, "anchor"),
		UID:        uid,
		Controller: &isController,
	}
}

// reconcileAnchor creates or updates the anchor ConfigMap in testkube namespace.
// Returns the anchor's UID for use in ownerReferences on child resources.
func (r *ExperimentReconciler) reconcileAnchor(
	ctx context.Context,
	experiment *testbenchv1alpha1.Experiment,
) (types.UID, error) {
	anchorName := resourceName(experiment.Name, experiment.Namespace, "anchor")
	anchor := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      anchorName,
			Namespace: testkubeNamespace,
		},
	}

	opResult, err := controllerutil.CreateOrUpdate(ctx, r.Client, anchor, func() error {
		anchor.Labels = buildLabels(experiment.Name, experiment.Namespace, resourceTypeAnchor)
		// If experiment is in testkube, set ownerRef for native GC
		if experiment.Namespace == testkubeNamespace {
			if err := controllerutil.SetControllerReference(experiment, anchor, r.Scheme); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return "", err
	}

	if opResult == controllerutil.OperationResultCreated && r.Recorder != nil {
		r.Recorder.Event(experiment, corev1.EventTypeNormal, EventAnchorCreated,
			fmt.Sprintf("Created anchor ConfigMap %s in %s", anchorName, testkubeNamespace))
	}

	return anchor.UID, nil
}

// reconcileConfigMap creates or updates the ConfigMap holding experiment.json for inline mode,
// or deletes a stale ConfigMap when switching to S3/URL mode.
func (r *ExperimentReconciler) reconcileConfigMap(
	ctx context.Context,
	experiment *testbenchv1alpha1.Experiment,
	anchorUID types.UID,
) error {
	cmName := resourceName(experiment.Name, experiment.Namespace, "experiment")

	if experiment.Spec.Dataset.Inline == nil {
		// Delete stale ConfigMap if it exists (mode switched from inline to S3/URL).
		cm := &corev1.ConfigMap{
			ObjectMeta: metav1.ObjectMeta{
				Name:      cmName,
				Namespace: testkubeNamespace,
			},
		}
		if err := r.Delete(ctx, cm); err != nil && !errors.IsNotFound(err) {
			return err
		}
		return nil
	}

	cm := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      cmName,
			Namespace: testkubeNamespace,
		},
	}

	_, err := controllerutil.CreateOrUpdate(ctx, r.Client, cm, func() error {
		cm.OwnerReferences = []metav1.OwnerReference{
			anchorOwnerReference(experiment.Name, experiment.Namespace, anchorUID),
		}
		cm.Labels = buildLabels(experiment.Name, experiment.Namespace, resourceTypeDataset)
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

	return nil
}

// buildExperimentJSON serializes the InlineDataset into the experiment.json format
// expected by the testbench scripts.
func (r *ExperimentReconciler) buildExperimentJSON(experiment *testbenchv1alpha1.Experiment) (string, error) {
	inline := experiment.Spec.Dataset.Inline
	exp := experimentJSON{
		LLMAsAJudgeModel: inline.LLMAsAJudgeModel,
		DefaultThreshold: inline.DefaultThreshold,
		Scenarios:        make([]scenarioJSON, 0, len(inline.Scenarios)),
	}
	for _, scenario := range inline.Scenarios {
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
			Response:          step.Reference.Response,
			Topics:            step.Reference.Topics,
			RetrievedContexts: step.Reference.RetrievedContexts,
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
	aiGateway *runtimev1alpha1.AiGateway,
	anchorUID types.UID,
) (bool, error) {
	workflow := r.buildTestWorkflow(experiment, aiGateway)
	ownerRef := anchorOwnerReference(experiment.Name, experiment.Namespace, anchorUID)
	workflow.SetOwnerReferences([]metav1.OwnerReference{ownerRef})

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
		existing.SetOwnerReferences([]metav1.OwnerReference{ownerRef})
		existing.SetLabels(workflow.GetLabels())
		if updateErr := r.Update(ctx, existing); updateErr != nil {
			return false, updateErr
		}
	}

	return false, nil
}

// buildTestWorkflow constructs the desired TestWorkflow unstructured object.
func (r *ExperimentReconciler) buildTestWorkflow(experiment *testbenchv1alpha1.Experiment, aiGateway *runtimev1alpha1.AiGateway) *unstructured.Unstructured {
	agentURL := r.resolveAgentURL(experiment)

	// Build the list of phase templates to chain.
	var useTemplates []interface{}
	if experiment.Spec.Dataset.Inline == nil {
		useTemplates = append(useTemplates, map[string]interface{}{
			"name": "setup-template",
			"config": map[string]interface{}{
				"datasetUrl": r.resolveDatasetURL(experiment),
			},
		})
	}
	evaluateTemplate := map[string]interface{}{"name": "evaluate-template"}
	if aiGateway != nil {
		evaluateTemplate["config"] = map[string]interface{}{
			"openAiBasePath": buildAiGatewayServiceUrl(*aiGateway),
			"openAiApiKey":   "testbench",
		}
	}

	useTemplates = append(useTemplates,
		map[string]interface{}{
			"name": "run-template",
			"config": map[string]interface{}{
				"agentUrl":       agentURL,
				"experimentName": experiment.Name,
			},
		},
		evaluateTemplate,
		map[string]interface{}{
			"name": "publish-template",
			"config": map[string]interface{}{
				"experimentName": experiment.Name,
			},
		},
		map[string]interface{}{
			"name": "visualize-template",
			"config": map[string]interface{}{
				"experimentName": experiment.Name,
			},
		},
	)

	spec := map[string]interface{}{
		"use": useTemplates,
	}

	if len(experiment.Spec.Env) > 0 {
		envList := make([]interface{}, 0, len(experiment.Spec.Env))
		for _, e := range experiment.Spec.Env {
			envVar := map[string]interface{}{
				"name": e.Name,
			}
			if e.Value != "" {
				envVar["value"] = e.Value
			}
			if e.ValueFrom != nil {
				valueFrom := map[string]interface{}{}
				if e.ValueFrom.SecretKeyRef != nil {
					ref := map[string]interface{}{
						"name": e.ValueFrom.SecretKeyRef.Name,
						"key":  e.ValueFrom.SecretKeyRef.Key,
					}
					if e.ValueFrom.SecretKeyRef.Optional != nil {
						ref["optional"] = *e.ValueFrom.SecretKeyRef.Optional
					}
					valueFrom["secretKeyRef"] = ref
				}
				if e.ValueFrom.ConfigMapKeyRef != nil {
					ref := map[string]interface{}{
						"name": e.ValueFrom.ConfigMapKeyRef.Name,
						"key":  e.ValueFrom.ConfigMapKeyRef.Key,
					}
					if e.ValueFrom.ConfigMapKeyRef.Optional != nil {
						ref["optional"] = *e.ValueFrom.ConfigMapKeyRef.Optional
					}
					valueFrom["configMapKeyRef"] = ref
				}
				if e.ValueFrom.FieldRef != nil {
					valueFrom["fieldRef"] = map[string]interface{}{
						"fieldPath": e.ValueFrom.FieldRef.FieldPath,
					}
				}
				if len(valueFrom) > 0 {
					envVar["valueFrom"] = valueFrom
				}
			}
			envList = append(envList, envVar)
		}
		spec["container"] = map[string]interface{}{
			"env": envList,
		}
	}

	// Add cron schedule as a TestWorkflow event if configured.
	if experiment.Spec.Schedule != nil {
		cronjob := map[string]interface{}{
			"cron": experiment.Spec.Schedule.Cron,
		}
		if experiment.Spec.Schedule.Timezone != "" {
			cronjob["timezone"] = experiment.Spec.Schedule.Timezone
		}
		spec["events"] = []interface{}{
			map[string]interface{}{
				"cronjob": cronjob,
			},
		}
	}

	// For inline mode, mount the pre-populated ConfigMap as the experiment file.
	if experiment.Spec.Dataset.Inline != nil {
		spec["content"] = map[string]interface{}{
			"files": []interface{}{
				map[string]interface{}{
					"path": "/data/datasets/experiment.json",
					"contentFrom": map[string]interface{}{
						"configMapKeyRef": map[string]interface{}{
							"name": resourceName(experiment.Name, experiment.Namespace, "experiment"),
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
				"name":      resourceName(experiment.Name, experiment.Namespace, "workflow"),
				"namespace": testkubeNamespace,
				"labels":    toUnstructuredLabels(buildLabels(experiment.Name, experiment.Namespace, resourceTypeWorkflow)),
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
	anchorUID types.UID,
) error {
	triggerName := resourceName(experiment.Name, experiment.Namespace, "trigger")

	if experiment.Spec.Trigger == nil || !experiment.Spec.Trigger.Enabled {
		// Delete trigger if it exists.
		existing := &unstructured.Unstructured{}
		existing.SetGroupVersionKind(testTriggerGVK)
		existing.SetName(triggerName)
		existing.SetNamespace(testkubeNamespace)
		if delErr := r.Delete(ctx, existing); delErr != nil && !errors.IsNotFound(delErr) {
			if isCRDNotInstalled(delErr) {
				return nil
			}
			return delErr
		}
		return nil
	}

	trigger := r.buildTestTrigger(experiment)
	ownerRef := anchorOwnerReference(experiment.Name, experiment.Namespace, anchorUID)
	trigger.SetOwnerReferences([]metav1.OwnerReference{ownerRef})

	existing := &unstructured.Unstructured{}
	existing.SetGroupVersionKind(testTriggerGVK)
	err := r.Get(ctx, types.NamespacedName{Name: triggerName, Namespace: testkubeNamespace}, existing)
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
		existing.SetOwnerReferences([]metav1.OwnerReference{ownerRef})
		existing.SetLabels(trigger.GetLabels())
		if updateErr := r.Update(ctx, existing); updateErr != nil {
			return updateErr
		}
	}

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
				"name":      resourceName(experiment.Name, experiment.Namespace, "trigger"),
				"namespace": testkubeNamespace,
				"labels":    toUnstructuredLabels(buildLabels(experiment.Name, experiment.Namespace, resourceTypeTrigger)),
			},
			"spec": map[string]interface{}{
				"selector": map[string]interface{}{
					"matchLabels": map[string]interface{}{
						"testkube.io/resource-kind":      "Deployment",
						"testkube.io/resource-name":      experiment.Spec.AgentRef.Name,
						"testkube.io/resource-namespace": agentNs,
					},
				},
				"event":             r.resolveTriggerEvent(experiment),
				"action":            "run",
				"execution":         "testworkflow",
				"concurrencyPolicy": concurrencyPolicy,
				"testSelector": map[string]interface{}{
					"name":      resourceName(experiment.Name, experiment.Namespace, "workflow"),
					"namespace": testkubeNamespace,
				},
				"disabled": false,
				"conditionSpec": map[string]interface{}{
					"timeout": int64(100),
					"delay":   int64(2),
					"conditions": []interface{}{
						map[string]interface{}{
							"type":   "Progressing",
							"status": "True",
							"reason": "NewReplicaSetAvailable",
							"ttl":    int64(60),
						},
						map[string]interface{}{
							"type":   "Available",
							"status": "True",
						},
					},
				},
			},
		},
	}
}

// updateStatus updates Ready and WorkflowReady conditions.
func (r *ExperimentReconciler) updateStatus(
	ctx context.Context,
	experiment *testbenchv1alpha1.Experiment,
	result reconcileResult,
	reconcileErr error,
) error {
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

// resolveTriggerEvent returns the trigger event, always "modified".
func (r *ExperimentReconciler) resolveTriggerEvent(_ *testbenchv1alpha1.Experiment) string {
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
	if experiment.Spec.Dataset.URL != "" {
		return experiment.Spec.Dataset.URL
	}
	if experiment.Spec.Dataset.S3 != nil {
		return fmt.Sprintf("s3://%s/%s", experiment.Spec.Dataset.S3.Bucket, experiment.Spec.Dataset.S3.Key)
	}
	return ""
}

// resolveAiGateway resolves the AiGateway resource for an experiment.
func (r *ExperimentReconciler) resolveAiGateway(ctx context.Context, experiment *testbenchv1alpha1.Experiment) (*runtimev1alpha1.AiGateway, error) {
	if experiment.Spec.AiGatewayRef != nil {
		return r.resolveExplicitAiGateway(ctx, experiment.Spec.AiGatewayRef, experiment.Namespace)
	}
	return r.resolveDefaultAiGateway(ctx)
}

// resolveExplicitAiGateway resolves a specific AiGateway referenced by the experiment.
func (r *ExperimentReconciler) resolveExplicitAiGateway(ctx context.Context, ref *corev1.ObjectReference, experimentNamespace string) (*runtimev1alpha1.AiGateway, error) {
	namespace := ref.Namespace
	if namespace == "" {
		namespace = experimentNamespace
	}

	var aiGateway runtimev1alpha1.AiGateway
	err := r.Get(ctx, types.NamespacedName{
		Name:      ref.Name,
		Namespace: namespace,
	}, &aiGateway)

	if err != nil {
		if apimeta.IsNoMatchError(err) {
			return nil, fmt.Errorf("AiGateway CRD is not installed in the cluster")
		}
		return nil, fmt.Errorf("failed to resolve AiGateway %s/%s: %w", namespace, ref.Name, err)
	}

	return &aiGateway, nil
}

// resolveDefaultAiGateway searches for any AiGateway in the default ai-gateway namespace.
func (r *ExperimentReconciler) resolveDefaultAiGateway(ctx context.Context) (*runtimev1alpha1.AiGateway, error) {
	logger := log.FromContext(ctx)

	var aiGatewayList runtimev1alpha1.AiGatewayList
	err := r.List(ctx, &aiGatewayList, client.InNamespace(defaultAiGatewayNamespace))
	if err != nil {
		if apimeta.IsNoMatchError(err) {
			logger.Info("AiGateway CRD is not installed, skipping default gateway resolution")
			return nil, nil
		}
		return nil, fmt.Errorf("failed to list AiGateways in namespace %s: %w", defaultAiGatewayNamespace, err)
	}

	if len(aiGatewayList.Items) == 0 {
		return nil, nil
	}

	if len(aiGatewayList.Items) > 1 {
		logger.Info("Multiple AiGateways found, selecting first one",
			"selected", aiGatewayList.Items[0].Name,
			"count", len(aiGatewayList.Items))
	}

	aiGateway := aiGatewayList.Items[0]
	return &aiGateway, nil
}

func buildAiGatewayServiceUrl(aiGateway runtimev1alpha1.AiGateway) string {
	return fmt.Sprintf("http://%s.%s.svc.cluster.local.:%d", aiGateway.Name, aiGateway.Namespace, aiGateway.Spec.Port)
}

// SetupWithManager sets up the controller with the Manager.
func (r *ExperimentReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&testbenchv1alpha1.Experiment{}).
		Watches(
			&corev1.ConfigMap{},
			handler.EnqueueRequestsFromMapFunc(r.anchorToExperiment),
			builder.WithPredicates(predicate.NewPredicateFuncs(func(obj client.Object) bool {
				labels := obj.GetLabels()
				return labels[labelManagedBy] == "experiment-controller" &&
					labels[labelResourceType] == resourceTypeAnchor
			})),
		).
		Complete(r)
}

// anchorToExperiment maps an anchor ConfigMap back to the source Experiment for reconciliation.
func (r *ExperimentReconciler) anchorToExperiment(_ context.Context, obj client.Object) []reconcile.Request {
	labels := obj.GetLabels()
	expName := labels[labelExperimentName]
	expNs := labels[labelExperimentNamespace]
	if expName == "" || expNs == "" {
		return nil
	}
	return []reconcile.Request{{
		NamespacedName: types.NamespacedName{Name: expName, Namespace: expNs},
	}}
}

// isCRDNotInstalled returns true when the error indicates the target CRD is not registered.
func isCRDNotInstalled(err error) bool {
	return apimeta.IsNoMatchError(err)
}
