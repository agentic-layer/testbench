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

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	runtimev1alpha1 "github.com/agentic-layer/agent-runtime-operator/api/v1alpha1"
	testbenchv1alpha1 "github.com/agentic-layer/testbench/operator/api/v1alpha1"
)

var _ = Describe("Experiment Controller", func() {
	const namespace = "default"
	ctx := context.Background()

	newReconciler := func() *ExperimentReconciler {
		return &ExperimentReconciler{
			Client: k8sClient,
			Scheme: k8sClient.Scheme(),
		}
	}

	reconcileExperiment := func(name string) error {
		_, err := newReconciler().Reconcile(ctx, reconcile.Request{
			NamespacedName: types.NamespacedName{Name: name, Namespace: namespace},
		})
		return err
	}

	cleanupExperiment := func(name string) {
		exp := &testbenchv1alpha1.Experiment{}
		if err := k8sClient.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, exp); err == nil {
			_ = k8sClient.Delete(ctx, exp)
		}
		// All generated resources are in testkubeNamespace with namespace-qualified names
		for _, suffix := range []string{"anchor", "experiment"} {
			rName := resourceName(name, namespace, suffix)
			cm := &corev1.ConfigMap{}
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: rName, Namespace: testkubeNamespace}, cm); err == nil {
				_ = k8sClient.Delete(ctx, cm)
			}
		}
		for _, info := range []struct {
			suffix string
			gvk    schema.GroupVersionKind
		}{
			{"workflow", testWorkflowGVK},
			{"trigger", testTriggerGVK},
		} {
			rName := resourceName(name, namespace, info.suffix)
			obj := &unstructured.Unstructured{}
			obj.SetGroupVersionKind(info.gvk)
			if err := k8sClient.Get(ctx, types.NamespacedName{Name: rName, Namespace: testkubeNamespace}, obj); err == nil {
				_ = k8sClient.Delete(ctx, obj)
			}
		}
	}

	Context("Scenarios mode reconciliation", func() {
		const expName = "exp-scenarios"

		BeforeEach(func() {
			By("creating the Experiment with inline scenarios")
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Name: expName, Namespace: namespace},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AgentRef: testbenchv1alpha1.AgentRef{Name: "my-agent", Namespace: "agents"},
					Dataset: testbenchv1alpha1.DatasetSource{
						Inline: &testbenchv1alpha1.InlineDataset{
							Scenarios: []testbenchv1alpha1.Scenario{
								{
									Name: "test scenario",
									Steps: []testbenchv1alpha1.Step{
										{
											Input: "What is the weather?",
											Reference: &testbenchv1alpha1.Reference{
												Response: "It is sunny",
												Topics:   []string{"weather"},
												ToolCalls: []testbenchv1alpha1.ToolCall{
													{
														Name: "get_weather",
														Args: runtime.RawExtension{Raw: []byte(`{"city":"NY"}`)},
													},
												},
											},
											Metrics: []testbenchv1alpha1.Metric{
												{MetricName: "AgentGoalAccuracy"},
											},
										},
									},
								},
							},
						},
					},
				},
			}
			Expect(k8sClient.Create(ctx, exp)).To(Succeed())
		})

		AfterEach(func() {
			cleanupExperiment(expName)
		})

		It("should create a ConfigMap with experiment.json", func() {
			By("reconciling the Experiment")
			Expect(reconcileExperiment(expName)).To(Succeed())

			By("checking the ConfigMap exists")
			cm := &corev1.ConfigMap{}
			Expect(k8sClient.Get(ctx, types.NamespacedName{Name: resourceName(expName, namespace, "experiment"), Namespace: testkubeNamespace}, cm)).To(Succeed())
			Expect(cm.Data).To(HaveKey("experiment.json"))

			By("verifying the experiment.json content")
			var expJSON experimentJSON
			Expect(json.Unmarshal([]byte(cm.Data["experiment.json"]), &expJSON)).To(Succeed())
			Expect(expJSON.Scenarios).To(HaveLen(1))
			Expect(expJSON.Scenarios[0].Name).To(Equal("test scenario"))
			Expect(expJSON.Scenarios[0].Steps).To(HaveLen(1))
			Expect(expJSON.Scenarios[0].Steps[0].Input).To(Equal("What is the weather?"))
			Expect(expJSON.Scenarios[0].Steps[0].Reference).NotTo(BeNil())
			Expect(expJSON.Scenarios[0].Steps[0].Reference.Response).To(Equal("It is sunny"))
			Expect(expJSON.Scenarios[0].Steps[0].Reference.Topics).To(ConsistOf("weather"))
			Expect(expJSON.Scenarios[0].Steps[0].Reference.ToolCalls).To(HaveLen(1))
			Expect(expJSON.Scenarios[0].Steps[0].Reference.ToolCalls[0].Name).To(Equal("get_weather"))
			Expect(expJSON.Scenarios[0].Steps[0].Metrics).To(HaveLen(1))
			Expect(expJSON.Scenarios[0].Steps[0].Metrics[0].MetricName).To(Equal("AgentGoalAccuracy"))
		})

		It("should set ConfigMap owner reference to the anchor", func() {
			Expect(reconcileExperiment(expName)).To(Succeed())

			cm := &corev1.ConfigMap{}
			Expect(k8sClient.Get(ctx, types.NamespacedName{Name: resourceName(expName, namespace, "experiment"), Namespace: testkubeNamespace}, cm)).To(Succeed())
			Expect(cm.OwnerReferences).To(HaveLen(1))
			Expect(cm.OwnerReferences[0].Kind).To(Equal("ConfigMap"))
			Expect(cm.OwnerReferences[0].Name).To(Equal(resourceName(expName, namespace, "anchor")))
			Expect(cm.OwnerReferences[0].Controller).NotTo(BeNil())
			Expect(*cm.OwnerReferences[0].Controller).To(BeTrue())
		})

		It("should create a TestWorkflow without setup-template", func() {
			Expect(reconcileExperiment(expName)).To(Succeed())

			wf := &unstructured.Unstructured{}
			wf.SetGroupVersionKind(testWorkflowGVK)
			Expect(k8sClient.Get(ctx, types.NamespacedName{Name: resourceName(expName, namespace, "workflow"), Namespace: testkubeNamespace}, wf)).To(Succeed())

			spec := wf.Object["spec"].(map[string]interface{})

			By("checking content.files mounts the ConfigMap")
			content, ok := spec["content"].(map[string]interface{})
			Expect(ok).To(BeTrue(), "spec.content should be present in scenarios mode")
			files := content["files"].([]interface{})
			Expect(files).To(HaveLen(1))
			file := files[0].(map[string]interface{})
			Expect(file["path"]).To(Equal("/data/datasets/experiment.json"))
			contentFrom := file["contentFrom"].(map[string]interface{})
			cmRef := contentFrom["configMapKeyRef"].(map[string]interface{})
			Expect(cmRef["name"]).To(Equal(resourceName(expName, namespace, "experiment")))
			Expect(cmRef["key"]).To(Equal("experiment.json"))

			By("checking use templates do NOT include setup-template")
			use := spec["use"].([]interface{})
			templateNames := make([]string, 0, len(use))
			for _, u := range use {
				templateNames = append(templateNames, u.(map[string]interface{})["name"].(string))
			}
			Expect(templateNames).NotTo(ContainElement("setup-template"))
			Expect(templateNames).To(ContainElements("run-template", "evaluate-template", "publish-template", "visualize-template"))

			By("checking the run-template has the correct agentUrl")
			for _, u := range use {
				um := u.(map[string]interface{})
				if um["name"] == "run-template" {
					cfg := um["config"].(map[string]interface{})
					Expect(cfg["agentUrl"]).To(Equal("http://my-agent.agents:8000"))
				}
			}
		})

		It("should set TestWorkflow owner reference to the anchor", func() {
			Expect(reconcileExperiment(expName)).To(Succeed())

			wf := &unstructured.Unstructured{}
			wf.SetGroupVersionKind(testWorkflowGVK)
			Expect(k8sClient.Get(ctx, types.NamespacedName{Name: resourceName(expName, namespace, "workflow"), Namespace: testkubeNamespace}, wf)).To(Succeed())
			Expect(wf.GetOwnerReferences()).To(HaveLen(1))
			Expect(wf.GetOwnerReferences()[0].Kind).To(Equal("ConfigMap"))
			Expect(wf.GetOwnerReferences()[0].Name).To(Equal(resourceName(expName, namespace, "anchor")))
		})

		It("should not create a TestTrigger when trigger is nil", func() {
			Expect(reconcileExperiment(expName)).To(Succeed())

			trig := &unstructured.Unstructured{}
			trig.SetGroupVersionKind(testTriggerGVK)
			err := k8sClient.Get(ctx, types.NamespacedName{Name: resourceName(expName, namespace, "trigger"), Namespace: testkubeNamespace}, trig)
			Expect(errors.IsNotFound(err)).To(BeTrue())
		})

		It("should set Ready=True status condition after successful reconciliation", func() {
			Expect(reconcileExperiment(expName)).To(Succeed())

			exp := &testbenchv1alpha1.Experiment{}
			Expect(k8sClient.Get(ctx, types.NamespacedName{Name: expName, Namespace: namespace}, exp)).To(Succeed())

			var readyCond *metav1.Condition
			for i := range exp.Status.Conditions {
				if exp.Status.Conditions[i].Type == conditionReady {
					readyCond = &exp.Status.Conditions[i]
					break
				}
			}
			Expect(readyCond).NotTo(BeNil())
			Expect(readyCond.Status).To(Equal(metav1.ConditionTrue))
			Expect(readyCond.Reason).To(Equal("ReconcileSucceeded"))
			Expect(readyCond.ObservedGeneration).To(Equal(exp.Generation))
		})

		It("should populate generatedResources in status", func() {
			Expect(reconcileExperiment(expName)).To(Succeed())

			exp := &testbenchv1alpha1.Experiment{}
			Expect(k8sClient.Get(ctx, types.NamespacedName{Name: expName, Namespace: namespace}, exp)).To(Succeed())

			kinds := make([]string, 0, len(exp.Status.GeneratedResources))
			for _, gr := range exp.Status.GeneratedResources {
				kinds = append(kinds, gr.Kind)
			}
			Expect(kinds).To(ContainElements("ConfigMap", "TestWorkflow"))
		})

		It("should be idempotent on re-reconciliation", func() {
			Expect(reconcileExperiment(expName)).To(Succeed())
			Expect(reconcileExperiment(expName)).To(Succeed())

			cmList := &corev1.ConfigMapList{}
			Expect(k8sClient.List(ctx, cmList,
				client.InNamespace(testkubeNamespace), client.MatchingLabels{})).To(Succeed())
			count := 0
			for _, cm := range cmList.Items {
				if cm.Name == resourceName(expName, namespace, "experiment") {
					count++
				}
			}
			Expect(count).To(Equal(1))
		})

		It("should create an anchor ConfigMap in testkube namespace", func() {
			Expect(reconcileExperiment(expName)).To(Succeed())

			anchor := &corev1.ConfigMap{}
			anchorName := resourceName(expName, namespace, "anchor")
			Expect(k8sClient.Get(ctx, types.NamespacedName{
				Name:      anchorName,
				Namespace: testkubeNamespace,
			}, anchor)).To(Succeed())

			Expect(anchor.Labels).To(HaveKeyWithValue(labelExperimentName, expName))
			Expect(anchor.Labels).To(HaveKeyWithValue(labelExperimentNamespace, namespace))
			Expect(anchor.Labels).To(HaveKeyWithValue(labelManagedBy, "experiment-controller"))
			Expect(anchor.Labels).To(HaveKeyWithValue(labelResourceType, resourceTypeAnchor))
		})

		It("should not create duplicate anchors on re-reconciliation", func() {
			Expect(reconcileExperiment(expName)).To(Succeed())
			Expect(reconcileExperiment(expName)).To(Succeed())

			anchorList := &corev1.ConfigMapList{}
			Expect(k8sClient.List(ctx, anchorList,
				client.InNamespace(testkubeNamespace),
				client.MatchingLabels{labelExperimentName: expName})).To(Succeed())
			anchorCount := 0
			for _, cm := range anchorList.Items {
				if cm.Labels[labelResourceType] == resourceTypeAnchor {
					anchorCount++
				}
			}
			Expect(anchorCount).To(Equal(1))
		})
	})

	Context("Dataset mode reconciliation", func() {
		const expName = "exp-dataset"

		BeforeEach(func() {
			By("creating the Experiment with a dataset URL")
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Name: expName, Namespace: namespace},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AgentRef: testbenchv1alpha1.AgentRef{Name: "my-agent", Namespace: "agents"},
					Dataset: testbenchv1alpha1.DatasetSource{
						URL: "http://data-server/dataset.csv",
					},
				},
			}
			Expect(k8sClient.Create(ctx, exp)).To(Succeed())
		})

		AfterEach(func() {
			cleanupExperiment(expName)
		})

		It("should not create a ConfigMap in URL mode", func() {
			Expect(reconcileExperiment(expName)).To(Succeed())

			cm := &corev1.ConfigMap{}
			err := k8sClient.Get(ctx, types.NamespacedName{Name: resourceName(expName, namespace, "experiment"), Namespace: testkubeNamespace}, cm)
			Expect(errors.IsNotFound(err)).To(BeTrue())
		})

		It("should create a TestWorkflow with setup-template and correct datasetUrl", func() {
			Expect(reconcileExperiment(expName)).To(Succeed())

			wf := &unstructured.Unstructured{}
			wf.SetGroupVersionKind(testWorkflowGVK)
			Expect(k8sClient.Get(ctx, types.NamespacedName{Name: resourceName(expName, namespace, "workflow"), Namespace: testkubeNamespace}, wf)).To(Succeed())

			spec := wf.Object["spec"].(map[string]interface{})

			By("checking no content.files in dataset mode")
			_, hasContent := spec["content"]
			Expect(hasContent).To(BeFalse(), "spec.content should be absent in dataset mode")

			By("checking setup-template is first in use list")
			use := spec["use"].([]interface{})
			first := use[0].(map[string]interface{})
			Expect(first["name"]).To(Equal("setup-template"))
			cfg := first["config"].(map[string]interface{})
			Expect(cfg["datasetUrl"]).To(Equal("http://data-server/dataset.csv"))
		})

		It("should resolve S3 dataset URL correctly", func() {
			exp := &testbenchv1alpha1.Experiment{}
			Expect(k8sClient.Get(ctx, types.NamespacedName{Name: expName, Namespace: namespace}, exp)).To(Succeed())
			exp.Spec.Dataset = testbenchv1alpha1.DatasetSource{
				S3: &testbenchv1alpha1.S3Source{Bucket: "my-bucket", Key: "data/dataset.csv"},
			}
			Expect(k8sClient.Update(ctx, exp)).To(Succeed())
			Expect(reconcileExperiment(expName)).To(Succeed())

			wf := &unstructured.Unstructured{}
			wf.SetGroupVersionKind(testWorkflowGVK)
			Expect(k8sClient.Get(ctx, types.NamespacedName{Name: resourceName(expName, namespace, "workflow"), Namespace: testkubeNamespace}, wf)).To(Succeed())
			spec := wf.Object["spec"].(map[string]interface{})
			use := spec["use"].([]interface{})
			first := use[0].(map[string]interface{})
			Expect(first["name"]).To(Equal("setup-template"))
			Expect(first["config"].(map[string]interface{})["datasetUrl"]).
				To(Equal("s3://my-bucket/data/dataset.csv"))
		})
	})

	Context("Trigger management", func() {
		const expName = "exp-trigger"

		createExperiment := func(triggerEnabled bool, policy string) {
			trigger := &testbenchv1alpha1.TriggerSpec{
				Enabled:           triggerEnabled,
				ConcurrencyPolicy: policy,
			}
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Name: expName, Namespace: namespace},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AgentRef: testbenchv1alpha1.AgentRef{Name: "my-agent", Namespace: "agents"},
					Dataset:  testbenchv1alpha1.DatasetSource{Inline: &testbenchv1alpha1.InlineDataset{Scenarios: []testbenchv1alpha1.Scenario{{Name: "s", Steps: []testbenchv1alpha1.Step{{Input: "q"}}}}}},
					Trigger:  trigger,
				},
			}
			Expect(k8sClient.Create(ctx, exp)).To(Succeed())
		}

		AfterEach(func() {
			cleanupExperiment(expName)
		})

		It("should create a TestTrigger when trigger.enabled=true", func() {
			createExperiment(true, "Forbid")
			Expect(reconcileExperiment(expName)).To(Succeed())

			trig := &unstructured.Unstructured{}
			trig.SetGroupVersionKind(testTriggerGVK)
			Expect(k8sClient.Get(ctx, types.NamespacedName{
				Name:      resourceName(expName, namespace, "trigger"),
				Namespace: testkubeNamespace,
			}, trig)).To(Succeed())

			spec := trig.Object["spec"].(map[string]interface{})
			Expect(spec["resource"]).To(Equal("deployment"))
			Expect(spec["concurrencyPolicy"]).To(Equal("forbid"))
			Expect(spec["action"]).To(Equal("run"))
			Expect(spec["execution"]).To(Equal("testworkflow"))
			Expect(spec["disabled"]).To(BeFalse())

			resSelector := spec["resourceSelector"].(map[string]interface{})
			Expect(resSelector["name"]).To(Equal("my-agent"))
			Expect(resSelector["namespace"]).To(Equal("agents"))

			testSelector := spec["testSelector"].(map[string]interface{})
			Expect(testSelector["name"]).To(Equal(resourceName(expName, namespace, "workflow")))
			Expect(testSelector["namespace"]).To(Equal(testkubeNamespace))
		})

		It("should set TestTrigger owner reference to the anchor", func() {
			createExperiment(true, "Allow")
			Expect(reconcileExperiment(expName)).To(Succeed())

			trig := &unstructured.Unstructured{}
			trig.SetGroupVersionKind(testTriggerGVK)
			Expect(k8sClient.Get(ctx, types.NamespacedName{
				Name:      resourceName(expName, namespace, "trigger"),
				Namespace: testkubeNamespace,
			}, trig)).To(Succeed())
			Expect(trig.GetOwnerReferences()).To(HaveLen(1))
			Expect(trig.GetOwnerReferences()[0].Kind).To(Equal("ConfigMap"))
		})

		It("should not create a TestTrigger when trigger.enabled=false", func() {
			createExperiment(false, "")
			Expect(reconcileExperiment(expName)).To(Succeed())

			trig := &unstructured.Unstructured{}
			trig.SetGroupVersionKind(testTriggerGVK)
			err := k8sClient.Get(ctx, types.NamespacedName{
				Name:      resourceName(expName, namespace, "trigger"),
				Namespace: testkubeNamespace,
			}, trig)
			Expect(errors.IsNotFound(err)).To(BeTrue())
		})

		It("should delete the TestTrigger when trigger is disabled after being enabled", func() {
			By("creating an experiment with trigger enabled")
			createExperiment(true, "Allow")
			Expect(reconcileExperiment(expName)).To(Succeed())

			trig := &unstructured.Unstructured{}
			trig.SetGroupVersionKind(testTriggerGVK)
			Expect(k8sClient.Get(ctx, types.NamespacedName{
				Name:      resourceName(expName, namespace, "trigger"),
				Namespace: testkubeNamespace,
			}, trig)).To(Succeed())

			By("disabling the trigger")
			exp := &testbenchv1alpha1.Experiment{}
			Expect(k8sClient.Get(ctx, types.NamespacedName{Name: expName, Namespace: namespace}, exp)).To(Succeed())
			exp.Spec.Trigger.Enabled = false
			Expect(k8sClient.Update(ctx, exp)).To(Succeed())

			Expect(reconcileExperiment(expName)).To(Succeed())

			err := k8sClient.Get(ctx, types.NamespacedName{
				Name:      resourceName(expName, namespace, "trigger"),
				Namespace: testkubeNamespace,
			}, trig)
			Expect(errors.IsNotFound(err)).To(BeTrue())
		})

		It("should include TestTrigger in generatedResources when enabled", func() {
			createExperiment(true, "Allow")
			Expect(reconcileExperiment(expName)).To(Succeed())

			exp := &testbenchv1alpha1.Experiment{}
			Expect(k8sClient.Get(ctx, types.NamespacedName{Name: expName, Namespace: namespace}, exp)).To(Succeed())

			kinds := make([]string, 0, len(exp.Status.GeneratedResources))
			for _, gr := range exp.Status.GeneratedResources {
				kinds = append(kinds, gr.Kind)
			}
			Expect(kinds).To(ContainElements("ConfigMap", "TestWorkflow", "TestTrigger"))
		})
	})

	Context("Status management", func() {
		const expName = "exp-status"

		AfterEach(func() {
			cleanupExperiment(expName)
		})

		It("should set WorkflowReady condition to True on success", func() {
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Name: expName, Namespace: namespace},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AgentRef: testbenchv1alpha1.AgentRef{Name: "agent"},
					Dataset:  testbenchv1alpha1.DatasetSource{Inline: &testbenchv1alpha1.InlineDataset{Scenarios: []testbenchv1alpha1.Scenario{{Name: "s", Steps: []testbenchv1alpha1.Step{{Input: "q"}}}}}},
				},
			}
			Expect(k8sClient.Create(ctx, exp)).To(Succeed())
			Expect(reconcileExperiment(expName)).To(Succeed())

			Expect(k8sClient.Get(ctx, types.NamespacedName{Name: expName, Namespace: namespace}, exp)).To(Succeed())
			var wfCond *metav1.Condition
			for i := range exp.Status.Conditions {
				if exp.Status.Conditions[i].Type == conditionWorkflowReady {
					wfCond = &exp.Status.Conditions[i]
					break
				}
			}
			Expect(wfCond).NotTo(BeNil())
			Expect(wfCond.Status).To(Equal(metav1.ConditionTrue))
		})

		It("should handle missing Experiment gracefully (not found)", func() {
			err := reconcileExperiment("nonexistent")
			Expect(err).NotTo(HaveOccurred())
		})
	})

	Context("Agent URL resolution", func() {
		It("should use agentRef.Namespace for the agent URL", func() {
			r := newReconciler()
			exp := &testbenchv1alpha1.Experiment{
				Spec: testbenchv1alpha1.ExperimentSpec{
					AgentRef: testbenchv1alpha1.AgentRef{Name: "weather-agent", Namespace: "sample-agents"},
				},
			}
			Expect(r.resolveAgentURL(exp)).To(Equal("http://weather-agent.sample-agents:8000"))
		})

		It("should fall back to experiment namespace when agentRef.Namespace is empty", func() {
			r := newReconciler()
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Namespace: "my-ns"},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AgentRef: testbenchv1alpha1.AgentRef{Name: "my-agent"},
				},
			}
			Expect(r.resolveAgentURL(exp)).To(Equal("http://my-agent.my-ns:8000"))
		})
	})

	Context("buildExperimentJSON", func() {
		It("should serialize customValues and metric parameters as raw JSON", func() {
			r := newReconciler()
			exp := &testbenchv1alpha1.Experiment{
				Spec: testbenchv1alpha1.ExperimentSpec{
					Dataset: testbenchv1alpha1.DatasetSource{
						Inline: &testbenchv1alpha1.InlineDataset{
							Scenarios: []testbenchv1alpha1.Scenario{
								{
									Name: "s",
									Steps: []testbenchv1alpha1.Step{
										{
											Input:        "q",
											CustomValues: runtime.RawExtension{Raw: []byte(`{"key":"value"}`)},
											Metrics: []testbenchv1alpha1.Metric{
												{
													MetricName: "M",
													Threshold:  0.7,
													Parameters: runtime.RawExtension{Raw: []byte(`{"mode":"precision"}`)},
												},
											},
										},
									},
								},
							},
						},
					},
				},
			}
			data, err := r.buildExperimentJSON(exp)
			Expect(err).NotTo(HaveOccurred())

			var result experimentJSON
			Expect(json.Unmarshal([]byte(data), &result)).To(Succeed())
			Expect(result.Scenarios[0].Steps[0].CustomValues).To(MatchJSON(`{"key":"value"}`))
			Expect(result.Scenarios[0].Steps[0].Metrics[0].Parameters).To(MatchJSON(`{"mode":"precision"}`))
		})

	})

	Context("AiGateway resolution", func() {
		It("should accept an Experiment with aiGatewayRef", func() {
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "exp-gw-ref",
					Namespace: namespace,
				},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AgentRef: testbenchv1alpha1.AgentRef{Name: "agent"},
					AiGatewayRef: &corev1.ObjectReference{
						Name:      "my-gateway",
						Namespace: "ai-gateway",
					},
					Dataset: testbenchv1alpha1.DatasetSource{Inline: &testbenchv1alpha1.InlineDataset{Scenarios: []testbenchv1alpha1.Scenario{{Name: "s", Steps: []testbenchv1alpha1.Step{{Input: "q"}}}}}},
				},
			}
			Expect(k8sClient.Create(ctx, exp)).To(Succeed())
			defer func() {
				_ = k8sClient.Delete(ctx, exp)
			}()

			fetched := &testbenchv1alpha1.Experiment{}
			Expect(k8sClient.Get(ctx, types.NamespacedName{
				Name: "exp-gw-ref", Namespace: namespace,
			}, fetched)).To(Succeed())
			Expect(fetched.Spec.AiGatewayRef).NotTo(BeNil())
			Expect(fetched.Spec.AiGatewayRef.Name).To(Equal("my-gateway"))
			Expect(fetched.Spec.AiGatewayRef.Namespace).To(Equal("ai-gateway"))
		})

		It("should resolve an explicit AiGateway by ref", func() {
			By("creating an AiGateway resource")
			gw := &runtimev1alpha1.AiGateway{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-gateway",
					Namespace: namespace,
				},
				Spec: runtimev1alpha1.AiGatewaySpec{
					Port:     4000,
					AiModels: []runtimev1alpha1.AiModel{{Name: "gpt-4", Provider: "openai"}},
				},
			}
			Expect(k8sClient.Create(ctx, gw)).To(Succeed())
			defer func() { _ = k8sClient.Delete(ctx, gw) }()

			r := newReconciler()
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Namespace: namespace},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AiGatewayRef: &corev1.ObjectReference{
						Name:      "test-gateway",
						Namespace: namespace,
					},
				},
			}
			resolved, err := r.resolveAiGateway(ctx, exp)
			Expect(err).NotTo(HaveOccurred())
			Expect(resolved).NotTo(BeNil())
			Expect(resolved.Name).To(Equal("test-gateway"))
			Expect(resolved.Spec.Port).To(Equal(int32(4000)))
		})

		It("should resolve default AiGateway from ai-gateway namespace", func() {
			By("creating the ai-gateway namespace")
			ns := &corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: "ai-gateway"}}
			_ = k8sClient.Create(ctx, ns)

			By("creating an AiGateway in ai-gateway namespace")
			gw := &runtimev1alpha1.AiGateway{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "default-gw",
					Namespace: "ai-gateway",
				},
				Spec: runtimev1alpha1.AiGatewaySpec{
					Port:     80,
					AiModels: []runtimev1alpha1.AiModel{{Name: "gpt-4", Provider: "openai"}},
				},
			}
			Expect(k8sClient.Create(ctx, gw)).To(Succeed())
			defer func() { _ = k8sClient.Delete(ctx, gw) }()

			r := newReconciler()
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Namespace: namespace},
				Spec:       testbenchv1alpha1.ExperimentSpec{},
			}
			resolved, err := r.resolveAiGateway(ctx, exp)
			Expect(err).NotTo(HaveOccurred())
			Expect(resolved).NotTo(BeNil())
			Expect(resolved.Name).To(Equal("default-gw"))
		})

		It("should return nil when no AiGateway exists", func() {
			r := newReconciler()
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Namespace: namespace},
				Spec:       testbenchv1alpha1.ExperimentSpec{},
			}
			resolved, err := r.resolveAiGateway(ctx, exp)
			Expect(err).NotTo(HaveOccurred())
			Expect(resolved).To(BeNil())
		})

		It("should return error when explicit ref points to non-existent gateway", func() {
			r := newReconciler()
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Namespace: namespace},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AiGatewayRef: &corev1.ObjectReference{
						Name:      "nonexistent",
						Namespace: namespace,
					},
				},
			}
			_, err := r.resolveAiGateway(ctx, exp)
			Expect(err).To(HaveOccurred())
			Expect(err.Error()).To(ContainSubstring("failed to resolve AiGateway"))
		})

		It("should set openApiBasePath on evaluate-template when AiGateway is resolved", func() {
			r := newReconciler()
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Name: "exp-gw-url", Namespace: namespace},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AgentRef: testbenchv1alpha1.AgentRef{Name: "agent", Namespace: "agents"},
					Dataset:  testbenchv1alpha1.DatasetSource{Inline: &testbenchv1alpha1.InlineDataset{Scenarios: []testbenchv1alpha1.Scenario{{Name: "s", Steps: []testbenchv1alpha1.Step{{Input: "q"}}}}}},
				},
			}
			gw := &runtimev1alpha1.AiGateway{
				ObjectMeta: metav1.ObjectMeta{Name: "my-gw", Namespace: "ai-gateway"},
				Spec:       runtimev1alpha1.AiGatewaySpec{Port: 4000, AiModels: []runtimev1alpha1.AiModel{{Name: "gpt-4", Provider: "openai"}}},
			}

			wf := r.buildTestWorkflow(exp, gw)
			spec := wf.Object["spec"].(map[string]interface{})
			use := spec["use"].([]interface{})

			var evalTemplate map[string]interface{}
			for _, u := range use {
				um := u.(map[string]interface{})
				if um["name"] == "evaluate-template" {
					evalTemplate = um
					break
				}
			}
			Expect(evalTemplate).NotTo(BeNil())
			cfg := evalTemplate["config"].(map[string]interface{})
			Expect(cfg["openApiBasePath"]).To(Equal("http://my-gw.ai-gateway.svc.cluster.local.:4000"))
		})

		It("should not set config on evaluate-template when no AiGateway", func() {
			r := newReconciler()
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Name: "exp-no-gw", Namespace: namespace},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AgentRef: testbenchv1alpha1.AgentRef{Name: "agent", Namespace: "agents"},
					Dataset:  testbenchv1alpha1.DatasetSource{Inline: &testbenchv1alpha1.InlineDataset{Scenarios: []testbenchv1alpha1.Scenario{{Name: "s", Steps: []testbenchv1alpha1.Step{{Input: "q"}}}}}},
				},
			}

			wf := r.buildTestWorkflow(exp, nil)
			spec := wf.Object["spec"].(map[string]interface{})
			use := spec["use"].([]interface{})

			var evalTemplate map[string]interface{}
			for _, u := range use {
				um := u.(map[string]interface{})
				if um["name"] == "evaluate-template" {
					evalTemplate = um
					break
				}
			}
			Expect(evalTemplate).NotTo(BeNil())
			_, hasConfig := evalTemplate["config"]
			Expect(hasConfig).To(BeFalse())
		})
	})

	Context("Deletion handling", func() {
		const expName = "exp-delete"

		AfterEach(func() {
			cleanupExperiment(expName)
		})

		It("should delete the anchor when the Experiment is deleted", func() {
			By("creating and reconciling an Experiment")
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Name: expName, Namespace: namespace},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AgentRef: testbenchv1alpha1.AgentRef{Name: "agent", Namespace: "agents"},
					Dataset: testbenchv1alpha1.DatasetSource{
						Inline: &testbenchv1alpha1.InlineDataset{
							Scenarios: []testbenchv1alpha1.Scenario{
								{Name: "s", Steps: []testbenchv1alpha1.Step{{Input: "q"}}},
							},
						},
					},
				},
			}
			Expect(k8sClient.Create(ctx, exp)).To(Succeed())
			Expect(reconcileExperiment(expName)).To(Succeed())

			By("verifying anchor exists")
			anchorName := resourceName(expName, namespace, "anchor")
			anchor := &corev1.ConfigMap{}
			Expect(k8sClient.Get(ctx, types.NamespacedName{
				Name: anchorName, Namespace: testkubeNamespace,
			}, anchor)).To(Succeed())

			By("deleting the Experiment and reconciling")
			Expect(k8sClient.Delete(ctx, exp)).To(Succeed())
			Expect(reconcileExperiment(expName)).To(Succeed())

			By("verifying anchor is deleted")
			err := k8sClient.Get(ctx, types.NamespacedName{
				Name: anchorName, Namespace: testkubeNamespace,
			}, anchor)
			Expect(errors.IsNotFound(err)).To(BeTrue())
		})

		It("should not have a finalizer on the Experiment", func() {
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Name: expName, Namespace: namespace},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AgentRef: testbenchv1alpha1.AgentRef{Name: "agent"},
					Dataset: testbenchv1alpha1.DatasetSource{
						Inline: &testbenchv1alpha1.InlineDataset{
							Scenarios: []testbenchv1alpha1.Scenario{
								{Name: "s", Steps: []testbenchv1alpha1.Step{{Input: "q"}}},
							},
						},
					},
				},
			}
			Expect(k8sClient.Create(ctx, exp)).To(Succeed())
			Expect(reconcileExperiment(expName)).To(Succeed())

			Expect(k8sClient.Get(ctx, types.NamespacedName{Name: expName, Namespace: namespace}, exp)).To(Succeed())
			Expect(exp.Finalizers).To(BeEmpty())
		})

		It("should strip legacy finalizer from existing Experiments", func() {
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{
					Name:       "exp-legacy-finalizer",
					Namespace:  namespace,
					Finalizers: []string{"testbench.agentic-layer.ai/cleanup"},
				},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AgentRef: testbenchv1alpha1.AgentRef{Name: "agent"},
					Dataset: testbenchv1alpha1.DatasetSource{
						Inline: &testbenchv1alpha1.InlineDataset{
							Scenarios: []testbenchv1alpha1.Scenario{
								{Name: "s", Steps: []testbenchv1alpha1.Step{{Input: "q"}}},
							},
						},
					},
				},
			}
			Expect(k8sClient.Create(ctx, exp)).To(Succeed())
			defer cleanupExperiment("exp-legacy-finalizer")

			Expect(reconcileExperiment("exp-legacy-finalizer")).To(Succeed())

			Expect(k8sClient.Get(ctx, types.NamespacedName{
				Name: "exp-legacy-finalizer", Namespace: namespace,
			}, exp)).To(Succeed())
			Expect(exp.Finalizers).To(BeEmpty())
		})
	})

	Context("OTel env var injection", func() {
		const expName = "exp-otel"

		AfterEach(func() {
			cleanupExperiment(expName)
		})

		It("should inject OTEL_EXPORTER_OTLP_ENDPOINT as direct value from spec.otlpEndpoint", func() {
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Name: expName, Namespace: namespace},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AgentRef:     testbenchv1alpha1.AgentRef{Name: "agent"},
					OTLPEndpoint: "http://lgtm.monitoring.svc.cluster.local:4318",
					Dataset:      testbenchv1alpha1.DatasetSource{Inline: &testbenchv1alpha1.InlineDataset{Scenarios: []testbenchv1alpha1.Scenario{{Name: "s", Steps: []testbenchv1alpha1.Step{{Input: "q"}}}}}},
				},
			}
			Expect(k8sClient.Create(ctx, exp)).To(Succeed())
			Expect(reconcileExperiment(expName)).To(Succeed())

			wf := &unstructured.Unstructured{}
			wf.SetGroupVersionKind(testWorkflowGVK)
			Expect(k8sClient.Get(ctx, types.NamespacedName{Name: resourceName(expName, namespace, "workflow"), Namespace: testkubeNamespace}, wf)).To(Succeed())

			spec := wf.Object["spec"].(map[string]interface{})
			container := spec["container"].(map[string]interface{})
			envList := container["env"].([]interface{})
			Expect(envList).To(HaveLen(1))
			envVar := envList[0].(map[string]interface{})
			Expect(envVar["name"]).To(Equal(otelEndpointKey))
			Expect(envVar["value"]).To(Equal("http://lgtm.monitoring.svc.cluster.local:4318"))
		})

		It("should omit container env when otlpEndpoint is not set", func() {
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Name: expName, Namespace: namespace},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AgentRef: testbenchv1alpha1.AgentRef{Name: "agent"},
					Dataset:  testbenchv1alpha1.DatasetSource{Inline: &testbenchv1alpha1.InlineDataset{Scenarios: []testbenchv1alpha1.Scenario{{Name: "s", Steps: []testbenchv1alpha1.Step{{Input: "q"}}}}}},
				},
			}
			Expect(k8sClient.Create(ctx, exp)).To(Succeed())
			Expect(reconcileExperiment(expName)).To(Succeed())

			wf := &unstructured.Unstructured{}
			wf.SetGroupVersionKind(testWorkflowGVK)
			Expect(k8sClient.Get(ctx, types.NamespacedName{Name: resourceName(expName, namespace, "workflow"), Namespace: testkubeNamespace}, wf)).To(Succeed())

			spec := wf.Object["spec"].(map[string]interface{})
			_, hasContainer := spec["container"]
			Expect(hasContainer).To(BeFalse(), "spec.container should be absent when otlpEndpoint is not set")
		})
	})

	Context("Self-healing", func() {
		It("should recreate anchor when it is accidentally deleted", func() {
			const expName = "exp-self-heal"

			By("creating and reconciling an Experiment")
			exp := &testbenchv1alpha1.Experiment{
				ObjectMeta: metav1.ObjectMeta{Name: expName, Namespace: namespace},
				Spec: testbenchv1alpha1.ExperimentSpec{
					AgentRef: testbenchv1alpha1.AgentRef{Name: "agent", Namespace: "agents"},
					Dataset: testbenchv1alpha1.DatasetSource{
						Inline: &testbenchv1alpha1.InlineDataset{
							Scenarios: []testbenchv1alpha1.Scenario{
								{Name: "s", Steps: []testbenchv1alpha1.Step{{Input: "q"}}},
							},
						},
					},
				},
			}
			Expect(k8sClient.Create(ctx, exp)).To(Succeed())
			defer cleanupExperiment(expName)
			Expect(reconcileExperiment(expName)).To(Succeed())

			By("deleting the anchor manually")
			anchorName := resourceName(expName, namespace, "anchor")
			anchor := &corev1.ConfigMap{}
			Expect(k8sClient.Get(ctx, types.NamespacedName{
				Name: anchorName, Namespace: testkubeNamespace,
			}, anchor)).To(Succeed())
			Expect(k8sClient.Delete(ctx, anchor)).To(Succeed())

			By("reconciling again (simulates the secondary watch triggering)")
			Expect(reconcileExperiment(expName)).To(Succeed())

			By("verifying the anchor is recreated")
			Expect(k8sClient.Get(ctx, types.NamespacedName{
				Name: anchorName, Namespace: testkubeNamespace,
			}, anchor)).To(Succeed())
		})
	})
})
