SHELL := /bin/bash
.DEFAULT_GOAL := help

PROJECT ?= jutra-493710
REGION ?= europe-west4
SERVICE ?= jutra
SA ?= jutra-689@$(PROJECT).iam.gserviceaccount.com

export GOOGLE_CLOUD_PROJECT=$(PROJECT)
export GOOGLE_APPLICATION_CREDENTIALS ?= $(PWD)/jutra-493710-f25c69585e55.json

.PHONY: help
help:
	@awk 'BEGIN{FS=":.*##"}/^[a-zA-Z0-9_-]+:.*##/{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}' $(MAKEFILE_LIST)

.PHONY: install
install: ## Install runtime + dev deps with uv
	uv pip install --system -e ".[dev]"

.PHONY: lint
lint: ## Ruff check
	ruff check jutra tests scripts
	ruff format --check jutra tests scripts

.PHONY: fmt
fmt: ## Ruff format
	ruff format jutra tests scripts
	ruff check --fix jutra tests scripts

.PHONY: test
test: ## Run fast unit tests (no live GCP)
	pytest -m "not live and not slow" -q

.PHONY: test-live
test-live: ## Run live tests (requires GCP creds)
	pytest -m live -q

.PHONY: run
run: ## Run FastAPI + MCP locally (uvicorn reload)
	uvicorn jutra.api.main:app --host 0.0.0.0 --port 8080 --reload

.PHONY: seed
seed: ## Seed demo user (alex_15) via MCP tools
	python scripts/seed.py

.PHONY: mcp-test
mcp-test: ## Smoke test MCP tools against http://localhost:8080/mcp
	python scripts/mcp_smoke.py

.PHONY: deploy
deploy: ## gcloud run deploy (builds from source)
	./scripts/deploy.sh

.PHONY: rollback
rollback: ## Rollback to previous Cloud Run revision
	./scripts/rollback.sh

.PHONY: logs
logs: ## Tail Cloud Run logs
	gcloud run services logs tail $(SERVICE) --region=$(REGION) --project=$(PROJECT)

.PHONY: pitch
pitch: ## Build Polish pitch deck PDF (Playwright + Chromium)
	@test -d $(PWD)/.venv || python3 -m venv $(PWD)/.venv
	@$(PWD)/.venv/bin/pip install -q -e ".[pitch]"
	@$(PWD)/.venv/bin/python -m playwright install chromium
	@$(PWD)/.venv/bin/python $(PWD)/docs/pitch/build_pdf.py

.PHONY: clean
clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage dist build
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
