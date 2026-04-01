package controller

import (
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

var _ = Describe("resourceName", func() {
	It("should combine experiment name, namespace, and suffix", func() {
		Expect(resourceName("my-exp", "team-a", "anchor")).To(Equal("my-exp-team-a-anchor"))
	})

	It("should produce names under 253 characters", func() {
		longName := strings.Repeat("a", 200)
		longNs := strings.Repeat("b", 200)
		result := resourceName(longName, longNs, "anchor")
		Expect(len(result)).To(BeNumerically("<=", 253))
	})

	It("should produce deterministic names for long inputs", func() {
		longName := strings.Repeat("a", 200)
		longNs := strings.Repeat("b", 200)
		r1 := resourceName(longName, longNs, "anchor")
		r2 := resourceName(longName, longNs, "anchor")
		Expect(r1).To(Equal(r2))
	})

	It("should produce different names for different suffixes", func() {
		name := resourceName("exp", "ns", "anchor")
		wf := resourceName("exp", "ns", "workflow")
		Expect(name).NotTo(Equal(wf))
	})
})
