package controller

const (
	labelExperimentName      = "testbench.agentic-layer.ai/experiment-name"
	labelExperimentNamespace = "testbench.agentic-layer.ai/experiment-namespace"
	labelManagedBy           = "testbench.agentic-layer.ai/managed-by"
	labelResourceType        = "testbench.agentic-layer.ai/resource-type"

	resourceTypeAnchor   = "anchor"
	resourceTypeWorkflow = "workflow"
	resourceTypeTrigger  = "trigger"
	resourceTypeDataset  = "dataset"
)

// buildLabels creates the standard label set for a managed resource.
func buildLabels(experimentName, experimentNamespace, resourceType string) map[string]string {
	return map[string]string{
		labelExperimentName:      experimentName,
		labelExperimentNamespace: experimentNamespace,
		labelManagedBy:           "experiment-controller",
		labelResourceType:        resourceType,
	}
}
