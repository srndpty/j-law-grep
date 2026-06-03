SHELL := /bin/sh
COMPOSE := docker compose -f deploy/docker-compose.yml --env-file .env
POWERSHELL := powershell.exe -NoProfile -ExecutionPolicy Bypass -Command
PYTHON ?= python scripts/precommit-python.py

export MSYS2_ARG_CONV_EXCL = *

INDEX_INPUT ?= indexer/sample_corpus
PROGRESS ?= 1
BULK_CHUNK ?= 1000
BULK_MAX_MB ?= 40
INDEX_ALIAS ?= jlaw-current
GOLDEN_FILE ?= tests/golden_queries/sample.json
MANIFEST ?= indexer/data/manifest.json

.PHONY: up down ps build-backend restart-backend lint typecheck test coverage frontend-check check reindex reindex-versioned validate-index golden health-smoke api-smoke frontend-smoke smoke

up:
	$(COMPOSE) up -d --build --remove-orphans

build-backend:
	$(COMPOSE) build backend

lint:
	$(PYTHON) -m ruff check backend indexer tests
	$(PYTHON) -m ruff format --check backend indexer tests

typecheck:
	$(PYTHON) -m mypy backend indexer tests

test:
	$(PYTHON) -m pytest

coverage:
	$(PYTHON) -m pytest --cov=backend --cov=indexer --cov-report=term-missing

frontend-check:
	$(POWERSHELL) "Set-Location frontend; npm run check"

check: lint typecheck test frontend-check

reindex:
	@if [ "$(INDEX_INPUT)" = "indexer/sample_corpus" ]; then \
		$(COMPOSE) build backend; \
		$(COMPOSE) run --rm backend python -m indexer.main --input /app/$(INDEX_INPUT) --provider opensearch $(if $(PROGRESS),--progress,) --chunk-size $(BULK_CHUNK) --max-bulk-mb $(BULK_MAX_MB) --write-manifest; \
	else \
		OPENSEARCH_HOST=http://localhost:9200 python -m indexer.main --input $(INDEX_INPUT) --provider opensearch $(if $(PROGRESS),--progress,) --chunk-size $(BULK_CHUNK) --max-bulk-mb $(BULK_MAX_MB) --write-manifest; \
	fi

reindex-versioned:
	@if [ "$(INDEX_INPUT)" = "indexer/sample_corpus" ]; then \
		$(COMPOSE) build backend; \
		$(COMPOSE) run --rm backend python -m indexer.main --input /app/$(INDEX_INPUT) --provider opensearch $(if $(PROGRESS),--progress,) --chunk-size $(BULK_CHUNK) --max-bulk-mb $(BULK_MAX_MB) --write-manifest --versioned --alias $(INDEX_ALIAS); \
	else \
		OPENSEARCH_HOST=http://localhost:9200 python -m indexer.main --input $(INDEX_INPUT) --provider opensearch $(if $(PROGRESS),--progress,) --chunk-size $(BULK_CHUNK) --max-bulk-mb $(BULK_MAX_MB) --write-manifest --versioned --alias $(INDEX_ALIAS); \
	fi

golden: build-backend
	$(COMPOSE) run --rm backend python -m indexer.golden --file /app/$(GOLDEN_FILE)

validate-index:
	OPENSEARCH_HOST=http://localhost:9200 python -m indexer.validate_index --manifest $(MANIFEST) --index $(INDEX_ALIAS)

health-smoke:
	curl -sS http://localhost:8000/healthz
	curl -sS http://localhost:8000/readyz
	curl -sS http://localhost:8000/metrics

down:
	$(COMPOSE) down -v --remove-orphans

ps:
	$(COMPOSE) ps

restart-backend:
	$(COMPOSE) restart backend

api-smoke:
	python scripts/smoke_search.py api-smoke http://localhost:8000

frontend-smoke:
	@echo "frontend (5173) -> /api/search proxy -> backend reachability"
	python scripts/smoke_search.py frontend-smoke http://localhost:5173

smoke: health-smoke api-smoke frontend-smoke
	@echo "smoke OK: healthz/readyz/metrics + backend /api/search + frontend proxy"
