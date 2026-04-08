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

package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
)

// EDIT THIS FILE!  THIS IS SCAFFOLDING FOR YOU TO OWN!
// NOTE: json tags are required.  Any new fields you add must have json tags for the fields to be serialized.

// AgentRef references an Agent resource
type AgentRef struct {
	// Name of the Agent resource
	// +kubebuilder:validation:Required
	Name string `json:"name"`

	// Namespace of the Agent resource
	// +optional
	Namespace string `json:"namespace,omitempty"`
}

// S3Source defines S3/MinIO dataset source
type S3Source struct {
	// Bucket name
	// +kubebuilder:validation:Required
	Bucket string `json:"bucket"`

	// Object key (path to file)
	// +kubebuilder:validation:Required
	Key string `json:"key"`
}

// InlineDataset defines an inline experiment dataset with scenarios, model, and threshold.
type InlineDataset struct {
	// LLM model used for evaluation (e.g., "gemini-2.5-flash-lite")
	// +optional
	LLMAsAJudgeModel string `json:"llmAsAJudgeModel,omitempty"`

	// Default threshold for all metrics (0.0-1.0)
	// +optional
	// +kubebuilder:validation:Minimum=0.0
	// +kubebuilder:validation:Maximum=1.0
	DefaultThreshold *float64 `json:"defaultThreshold,omitempty"`

	// Test scenarios
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinItems=1
	Scenarios []Scenario `json:"scenarios"`
}

// DatasetSource defines where to load the test dataset from.
// Exactly one of s3, url, or inline must be set.
// +kubebuilder:validation:XValidation:rule="(has(self.s3) ? 1 : 0) + (has(self.url) ? 1 : 0) + (has(self.inline) ? 1 : 0) == 1",message="exactly one of s3, url, or inline must be set"
type DatasetSource struct {
	// S3 source configuration
	// +optional
	S3 *S3Source `json:"s3,omitempty"`

	// URL source (HTTP/HTTPS)
	// +optional
	URL string `json:"url,omitempty"`

	// Inline dataset with scenarios
	// +optional
	Inline *InlineDataset `json:"inline,omitempty"`
}

// ToolCall represents an expected tool invocation
type ToolCall struct {
	// Name of the tool
	// +kubebuilder:validation:Required
	Name string `json:"name"`

	// Arguments passed to the tool (JSON object)
	// +optional
	// +kubebuilder:pruning:PreserveUnknownFields
	// +kubebuilder:validation:Schemaless
	Args runtime.RawExtension `json:"args,omitempty"`
}

// Reference defines expected outputs for evaluation
type Reference struct {
	// Expected response text
	// +optional
	Response string `json:"response,omitempty"`

	// Expected tool calls
	// +optional
	ToolCalls []ToolCall `json:"toolCalls,omitempty"`

	// Expected topics to be covered
	// +optional
	Topics []string `json:"topics,omitempty"`
}

// Metric defines a single metric evaluation configuration
type Metric struct {
	// Name of the metric (e.g., "ragas_faithfulness", "tool_check")
	// +kubebuilder:validation:Required
	MetricName string `json:"metricName"`

	// Threshold for pass/fail (0.0-1.0)
	// +optional
	// +kubebuilder:validation:Minimum=0.0
	// +kubebuilder:validation:Maximum=1.0
	Threshold float64 `json:"threshold,omitempty"`

	// Additional parameters for the metric
	// +optional
	// +kubebuilder:pruning:PreserveUnknownFields
	// +kubebuilder:validation:Schemaless
	Parameters runtime.RawExtension `json:"parameters,omitempty"`
}

// Step represents a single test step within a scenario
type Step struct {
	// User input to the agent
	// +kubebuilder:validation:Required
	Input string `json:"input"`

	// Expected reference data for evaluation
	// +optional
	Reference *Reference `json:"reference,omitempty"`

	// Custom key-value pairs (e.g., retrieved_contexts)
	// +optional
	// +kubebuilder:pruning:PreserveUnknownFields
	// +kubebuilder:validation:Schemaless
	CustomValues runtime.RawExtension `json:"customValues,omitempty"`

	// Metrics to evaluate for this step
	// +optional
	Metrics []Metric `json:"metrics,omitempty"`
}

// Scenario represents a test scenario containing multiple steps
type Scenario struct {
	// Name of the scenario
	// +kubebuilder:validation:Required
	Name string `json:"name"`

	// Steps in this scenario
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinItems=1
	Steps []Step `json:"steps"`
}

// TriggerSpec defines when and how the experiment should run
type TriggerSpec struct {
	// Enabled controls whether the experiment runs automatically
	// +optional
	Enabled bool `json:"enabled,omitempty"`

	// ConcurrencyPolicy defines how concurrent executions are handled
	// +optional
	// +kubebuilder:validation:Enum=Allow;Forbid;Replace
	ConcurrencyPolicy string `json:"concurrencyPolicy,omitempty"`
}

// ScheduleSpec defines cron-based scheduling for the experiment workflow.
type ScheduleSpec struct {
	// Cron expression (standard Kubernetes cron format, e.g., "0 3 * * *")
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Pattern=`^(\S+\s){4}\S+$`
	Cron string `json:"cron"`

	// IANA timezone name (e.g., "Europe/Berlin"). Defaults to cluster local time.
	// +optional
	Timezone string `json:"timezone,omitempty"`
}

// ExperimentSpec defines the desired state of Experiment
type ExperimentSpec struct {
	// Reference to the Agent to evaluate
	// +kubebuilder:validation:Required
	AgentRef AgentRef `json:"agentRef"`

	// AiGatewayRef references an AiGateway resource for LLM access during evaluation.
	// Only Name and Namespace fields are used.
	// +optional
	AiGatewayRef *corev1.ObjectReference `json:"aiGatewayRef,omitempty"`

	// Source of the test dataset
	// +kubebuilder:validation:Required
	Dataset DatasetSource `json:"dataset"`

	// Env defines environment variables to inject into the TestWorkflow containers.
	// Uses the standard Kubernetes EnvVar schema (supports value, valueFrom with secretKeyRef, configMapKeyRef, etc.).
	// User-defined env vars override any operator-set vars with the same name.
	// +optional
	Env []corev1.EnvVar `json:"env,omitempty"`

	// Schedule configures cron-based execution of the experiment workflow.
	// Independent of trigger (event-based execution).
	// +optional
	Schedule *ScheduleSpec `json:"schedule,omitempty"`

	// Trigger configuration
	// +optional
	Trigger *TriggerSpec `json:"trigger,omitempty"`
}

// GeneratedResource represents a Kubernetes resource created by this Experiment
type GeneratedResource struct {
	// Kind of the resource (e.g., "TestWorkflow")
	Kind string `json:"kind"`

	// Name of the resource
	Name string `json:"name"`

	// Namespace of the resource
	Namespace string `json:"namespace,omitempty"`
}

// LastExecution contains metadata about the most recent execution
type LastExecution struct {
	// ExecutionID from Testkube
	ExecutionID string `json:"executionId,omitempty"`

	// ExecutionNumber from Testkube
	ExecutionNumber int `json:"executionNumber,omitempty"`

	// StartTime of the execution
	StartTime *metav1.Time `json:"startTime,omitempty"`

	// EndTime of the execution
	EndTime *metav1.Time `json:"endTime,omitempty"`

	// Status of the execution
	Status string `json:"status,omitempty"`
}

// ExperimentStatus defines the observed state of Experiment
type ExperimentStatus struct {
	// Conditions represent the latest available observations of the Experiment's state
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`

	// GeneratedResources lists Kubernetes resources created by this Experiment
	// +optional
	GeneratedResources []GeneratedResource `json:"generatedResources,omitempty"`

	// LastExecution contains metadata about the most recent execution
	// +optional
	LastExecution *LastExecution `json:"lastExecution,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:shortName=exp
// +kubebuilder:printcolumn:name="Agent",type=string,JSONPath=`.spec.agentRef.name`
// +kubebuilder:printcolumn:name="Status",type=string,JSONPath=`.status.conditions[?(@.type=="Ready")].status`
// +kubebuilder:printcolumn:name="Age",type=date,JSONPath=`.metadata.creationTimestamp`

// Experiment is the Schema for the experiments API
type Experiment struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   ExperimentSpec   `json:"spec,omitempty"`
	Status ExperimentStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// ExperimentList contains a list of Experiment
type ExperimentList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []Experiment `json:"items"`
}

func init() {
	SchemeBuilder.Register(&Experiment{}, &ExperimentList{})
}
