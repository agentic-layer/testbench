package controller

import (
	"context"
	"sync"
	"time"

	"github.com/go-logr/logr"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"

	testbenchv1alpha1 "github.com/agentic-layer/testbench/operator/api/v1alpha1"
)

// GarbageCollector periodically checks for orphaned anchor ConfigMaps
// whose source Experiments no longer exist, and deletes them.
type GarbageCollector struct {
	Client   client.Client
	Interval time.Duration
	Logger   logr.Logger

	// mu protects failCounts and backoffAnchors.
	mu sync.Mutex
	// failCounts tracks consecutive failures per anchor for backoff.
	failCounts map[string]int
	// backoffAnchors tracks anchors in backoff with their next-check time.
	backoffAnchors map[string]time.Time
}

// Start implements manager.Runnable. It runs the GC sweep on a ticker.
func (gc *GarbageCollector) Start(ctx context.Context) error {
	gc.failCounts = make(map[string]int)
	gc.backoffAnchors = make(map[string]time.Time)

	ticker := time.NewTicker(gc.Interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			gc.sweep(ctx)
		}
	}
}

// sweep lists all anchor ConfigMaps and deletes those whose source Experiment is gone.
func (gc *GarbageCollector) sweep(ctx context.Context) {
	var anchors corev1.ConfigMapList
	if err := gc.Client.List(ctx, &anchors,
		client.InNamespace(testkubeNamespace),
		client.MatchingLabels{
			labelManagedBy:    "experiment-controller",
			labelResourceType: resourceTypeAnchor,
		},
	); err != nil {
		gc.Logger.Error(err, "failed to list anchor ConfigMaps")
		return
	}

	for i := range anchors.Items {
		anchor := &anchors.Items[i]
		expName := anchor.Labels[labelExperimentName]
		expNamespace := anchor.Labels[labelExperimentNamespace]

		if expName == "" || expNamespace == "" {
			gc.Logger.Info("anchor missing experiment labels, skipping",
				"anchor", anchor.Name)
			continue
		}

		// Skip anchors in backoff period.
		gc.mu.Lock()
		if nextCheck, ok := gc.backoffAnchors[anchor.Name]; ok {
			if time.Now().Before(nextCheck) {
				gc.mu.Unlock()
				continue
			}
		}
		gc.mu.Unlock()

		// Check if source Experiment still exists (direct API call).
		var experiment testbenchv1alpha1.Experiment
		err := gc.Client.Get(ctx, types.NamespacedName{
			Name:      expName,
			Namespace: expNamespace,
		}, &experiment)

		if errors.IsNotFound(err) {
			gc.Logger.Info("deleting orphaned anchor",
				"anchor", anchor.Name,
				"experiment", expName,
				"experimentNamespace", expNamespace)
			if delErr := gc.Client.Delete(ctx, anchor); delErr != nil && !errors.IsNotFound(delErr) {
				gc.Logger.Error(delErr, "failed to delete orphaned anchor", "anchor", anchor.Name)
			}
			gc.mu.Lock()
			delete(gc.failCounts, anchor.Name)
			delete(gc.backoffAnchors, anchor.Name)
			gc.mu.Unlock()
		} else if err != nil {
			// Track consecutive failures for backoff.
			gc.mu.Lock()
			gc.failCounts[anchor.Name]++
			if gc.failCounts[anchor.Name] >= 3 {
				gc.backoffAnchors[anchor.Name] = time.Now().Add(5 * time.Minute)
				gc.Logger.Info("anchor check backed off after 3 failures",
					"anchor", anchor.Name, "nextCheck", gc.backoffAnchors[anchor.Name])
			}
			gc.mu.Unlock()
			gc.Logger.Error(err, "failed to check source Experiment",
				"experiment", expName,
				"experimentNamespace", expNamespace)
		} else {
			// Success — reset failure tracking.
			gc.mu.Lock()
			delete(gc.failCounts, anchor.Name)
			delete(gc.backoffAnchors, anchor.Name)
			gc.mu.Unlock()
		}
	}
}
