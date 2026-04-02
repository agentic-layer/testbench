package controller

import (
	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

var _ = Describe("buildLabels", func() {
	It("should include all required labels", func() {
		labels := buildLabels("my-exp", "team-a", resourceTypeAnchor)
		Expect(labels).To(HaveKeyWithValue(labelExperimentName, "my-exp"))
		Expect(labels).To(HaveKeyWithValue(labelExperimentNamespace, "team-a"))
		Expect(labels).To(HaveKeyWithValue(labelManagedBy, "experiment-controller"))
		Expect(labels).To(HaveKeyWithValue(labelResourceType, "anchor"))
	})

	It("should set correct resource type for workflow", func() {
		labels := buildLabels("exp", "ns", resourceTypeWorkflow)
		Expect(labels).To(HaveKeyWithValue(labelResourceType, "workflow"))
	})
})
