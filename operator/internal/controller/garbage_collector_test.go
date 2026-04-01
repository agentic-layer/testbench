package controller

import (
	"context"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"

	testbenchv1alpha1 "github.com/agentic-layer/testbench/operator/api/v1alpha1"
)

var _ = Describe("GarbageCollector", func() {
	ctx := context.Background()

	newGC := func() *GarbageCollector {
		return &GarbageCollector{
			Client:         k8sClient,
			Interval:       100 * time.Millisecond,
			Logger:         zap.New(zap.WriteTo(GinkgoWriter)),
			failCounts:     make(map[string]int),
			backoffAnchors: make(map[string]time.Time),
		}
	}

	It("should delete anchor ConfigMaps whose source Experiment no longer exists", func() {
		By("creating an orphaned anchor ConfigMap in testkube")
		anchor := &corev1.ConfigMap{
			ObjectMeta: metav1.ObjectMeta{
				Name:      "orphan-gone-ns-anchor",
				Namespace: testkubeNamespace,
				Labels:    buildLabels("orphan", "gone-ns", resourceTypeAnchor),
			},
		}
		Expect(k8sClient.Create(ctx, anchor)).To(Succeed())

		By("running one GC sweep")
		gc := newGC()
		gc.sweep(ctx)

		By("verifying the anchor was deleted")
		err := k8sClient.Get(ctx, types.NamespacedName{
			Name: "orphan-gone-ns-anchor", Namespace: testkubeNamespace,
		}, anchor)
		Expect(errors.IsNotFound(err)).To(BeTrue())
	})

	It("should NOT delete anchor ConfigMaps whose source Experiment still exists", func() {
		By("creating an Experiment")
		exp := &testbenchv1alpha1.Experiment{
			ObjectMeta: metav1.ObjectMeta{Name: "gc-keep", Namespace: "default"},
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
		defer func() { _ = k8sClient.Delete(ctx, exp) }()

		By("creating the corresponding anchor")
		anchorName := resourceName("gc-keep", "default", "anchor")
		anchor := &corev1.ConfigMap{
			ObjectMeta: metav1.ObjectMeta{
				Name:      anchorName,
				Namespace: testkubeNamespace,
				Labels:    buildLabels("gc-keep", "default", resourceTypeAnchor),
			},
		}
		Expect(k8sClient.Create(ctx, anchor)).To(Succeed())
		defer func() { _ = k8sClient.Delete(ctx, anchor) }()

		By("running one GC sweep")
		gc := newGC()
		gc.sweep(ctx)

		By("verifying the anchor still exists")
		Expect(k8sClient.Get(ctx, types.NamespacedName{
			Name: anchorName, Namespace: testkubeNamespace,
		}, anchor)).To(Succeed())
	})

	It("should delete anchor when Experiment was deleted from an existing namespace", func() {
		By("creating and then deleting an Experiment in the default namespace")
		exp := &testbenchv1alpha1.Experiment{
			ObjectMeta: metav1.ObjectMeta{Name: "gc-deleted", Namespace: "default"},
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
		Expect(k8sClient.Delete(ctx, exp)).To(Succeed())

		By("creating the orphaned anchor (simulating controller was down during delete)")
		anchorName := resourceName("gc-deleted", "default", "anchor")
		anchor := &corev1.ConfigMap{
			ObjectMeta: metav1.ObjectMeta{
				Name:      anchorName,
				Namespace: testkubeNamespace,
				Labels:    buildLabels("gc-deleted", "default", resourceTypeAnchor),
			},
		}
		Expect(k8sClient.Create(ctx, anchor)).To(Succeed())

		By("running one GC sweep")
		gc := newGC()
		gc.sweep(ctx)

		By("verifying the anchor was deleted")
		err := k8sClient.Get(ctx, types.NamespacedName{
			Name: anchorName, Namespace: testkubeNamespace,
		}, anchor)
		Expect(errors.IsNotFound(err)).To(BeTrue())
	})
})
