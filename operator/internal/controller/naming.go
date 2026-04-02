package controller

import (
	"crypto/sha256"
	"fmt"
)

const maxK8sNameLen = 253

// resourceName builds a Kubernetes resource name from experiment name, namespace, and suffix.
// If the combined name exceeds 253 characters, it truncates the base and appends a hash.
func resourceName(experimentName, experimentNamespace, suffix string) string {
	base := experimentName + "-" + experimentNamespace
	full := base + "-" + suffix

	if len(full) <= maxK8sNameLen {
		return full
	}

	hash := fmt.Sprintf("%x", sha256.Sum256([]byte(base)))[:8]
	maxBaseLen := maxK8sNameLen - len(suffix) - len(hash) - 2 // two hyphens
	if maxBaseLen < 0 {
		maxBaseLen = 0
	}
	if len(base) > maxBaseLen {
		base = base[:maxBaseLen]
	}
	return base + "-" + hash + "-" + suffix
}
