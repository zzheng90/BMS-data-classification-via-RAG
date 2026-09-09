# Convenience targets for the CI/CD lesson.
# Run `make help` to list them.

IMAGE       ?= bms-rag
TAG         ?= dev
KIND_CLUSTER ?= cicd-test
NAMESPACE   ?= bms-rag
PORT        ?= 8501

.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

## ---- Local Docker --------------------------------------------------------
build: ## Build the container image
	docker build -t $(IMAGE):$(TAG) .

run: ## Run the container locally on $(PORT), reading .env
	docker run --rm -it -p $(PORT):8501 --env-file .env --name $(IMAGE) $(IMAGE):$(TAG)

smoke: ## Build then check the health endpoint responds
	docker build -t $(IMAGE):$(TAG) .
	docker run -d --rm -p $(PORT):8501 --name $(IMAGE)-smoke $(IMAGE):$(TAG)
	@echo "waiting for health..."; \
	for i in $$(seq 1 30); do \
	  curl -fsS http://localhost:$(PORT)/_stcore/health && break || sleep 3; \
	done; \
	docker stop $(IMAGE)-smoke

## ---- Local Kubernetes (kind) -------------------------------------------
kind-up: ## Create the local kind cluster
	kind create cluster --name $(KIND_CLUSTER)

kind-down: ## Delete the local kind cluster
	kind delete cluster --name $(KIND_CLUSTER)

kind-load: build ## Build and load the image into kind
	kind load docker-image $(IMAGE):$(TAG) --name $(KIND_CLUSTER)

deploy: ## Apply the k8s manifests
	kubectl apply -k k8s/

redeploy: kind-load ## Rebuild, reload, and restart the deployment
	kubectl -n $(NAMESPACE) rollout restart deployment/bms-rag
	kubectl -n $(NAMESPACE) rollout status deployment/bms-rag

forward: ## Port-forward the service to localhost:$(PORT)
	kubectl -n $(NAMESPACE) port-forward svc/bms-rag $(PORT):80

logs: ## Tail application logs
	kubectl -n $(NAMESPACE) logs -f deployment/bms-rag

.PHONY: help build run smoke kind-up kind-down kind-load deploy redeploy forward logs
