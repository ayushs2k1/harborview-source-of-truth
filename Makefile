# Harborview Source of Truth
#
# One-command setup and run. macOS and Linux first; Windows is best-effort.
# `uv` is used when present, otherwise a plain venv - both end up at .venv/bin/python.

.DEFAULT_GOAL := help
SHELL := /bin/bash

VENV := .venv
PY := $(VENV)/bin/python
UV := $(shell command -v uv 2> /dev/null)

# The pinned sample date, so fixture runs never drift with the calendar (spec 21).
PINNED_AS_OF := 2026-09-21
DEMO_DIR := data/samples/healthcare/messy
CLEAN_DIR := data/samples/healthcare/clean

.PHONY: help setup dev api web demo test chaos lint fmt reset docs verify-clean samples

help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| sort | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Create the venv, install Python and web dependencies
ifdef UV
	uv venv $(VENV)
	VIRTUAL_ENV=$(VENV) uv pip install -e ".[dev]"
else
	python3 -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip setuptools wheel
	$(PY) -m pip install --quiet -e ".[dev]"
endif
	cd web && npm install
	@echo "Setup complete. Run 'make dev'."

dev: ## Run the API on :8000 and the web app on :5173
	@trap 'kill 0' EXIT INT TERM; \
	$(PY) -m uvicorn sot.api.app:app --host 127.0.0.1 --port 8000 --reload & \
	(cd web && npm run dev) & \
	wait

api: ## Run only the API
	$(PY) -m uvicorn sot.api.app:app --host 127.0.0.1 --port 8000 --reload

web: ## Run only the web app
	cd web && npm run dev

samples: ## Regenerate the sample data (deterministic, seeded)
	$(PY) scripts/generate_samples.py --seed 42

demo: ## Ingest the messy sample set and write a report
	$(PY) -m sot ingest $(DEMO_DIR)

verify-clean: ## Assert the clean sample raises nothing above INFO at the pinned date
	$(PY) -m sot ingest $(CLEAN_DIR) --as-of $(PINNED_AS_OF) --max-severity INFO

test: ## Run the test suite
	$(PY) -m pytest

chaos: ## Run the chaos deck and write the coverage report
	$(PY) -m pytest -m chaos

lint: ## Lint Python and typecheck the web app
	$(PY) -m ruff check sot tests scripts
	$(PY) -m ruff format --check sot tests scripts
	cd web && npx tsc -b --noEmit

fmt: ## Format Python sources
	$(PY) -m ruff format sot tests scripts
	$(PY) -m ruff check --fix sot tests scripts

docs: ## Regenerate docs/RULES.md from the rule registry
	$(PY) scripts/gen_rules_doc.py

reset: ## Delete the database, landed files, and reports
	rm -rf var reports
	mkdir -p var/landing var/pages reports
	touch var/.gitkeep reports/.gitkeep
	@echo "Reset. Decisions and run history are gone."
