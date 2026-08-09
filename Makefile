.DEFAULT_GOAL := help
VENV := venv
PY := $(VENV)/bin/python

.PHONY: help setup dev run test lint fix cov docker-build docker-run clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Create the virtualenv and install all dependencies
	python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt -r requirements-dev.txt
	@test -f .env || cp .env.example .env

dev: ## Run with auto-reload on http://localhost:8000
	$(VENV)/bin/uvicorn app.main:app --reload --port 8000

run: ## Run without reload (closest to production)
	$(VENV)/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers

test: ## Run the test suite
	$(PY) -m pytest

cov: ## Run the test suite with a coverage report
	$(PY) -m pytest --cov=app --cov-report=term-missing

lint: ## Check formatting and lint rules
	$(VENV)/bin/ruff check app tests api

fix: ## Apply the lint fixes that are safe to automate
	$(VENV)/bin/ruff check --fix app tests api

docker-build: ## Build the production image
	docker build -t medico-extractor:latest .

docker-run: ## Run the production image with .env
	docker run --rm -p 8000:8000 --env-file .env medico-extractor:latest

clean: ## Remove caches and build artefacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
