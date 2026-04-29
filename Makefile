# Testworkflows Docker Image Makefile

# Image configuration
IMAGE_NAME ?= ghcr.io/agentic-layer/testbench/testworkflows
IMAGE_TAG ?= latest

# Full image reference
IMAGE := $(IMAGE_NAME):$(IMAGE_TAG)

.PHONY: help
help: ## Display this help message
	@echo "Testworkflows Docker Image Management"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"; printf "Targets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  %-15s %s\n", $$1, $$2 } /^##@/ { printf "\n%s\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

## Build the Docker image
.PHONY: build
build:
	docker build -t $(IMAGE) .

## Run container
.PHONY: run
run:
	docker run --rm -it $(IMAGE)
