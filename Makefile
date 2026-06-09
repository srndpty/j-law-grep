SHELL := /bin/sh
COMPOSE := docker compose -f deploy/docker-compose.yml --env-file .env
POWERSHELL := powershell.exe -NoProfile -ExecutionPolicy Bypass -Command
PYTHON ?= python scripts/precommit-python.py

-include .env

export MSYS2_ARG_CONV_EXCL = *

INDEX_INPUT ?= indexer/sample_corpus
PROGRESS ?= 1
BULK_CHUNK ?= 200
BULK_MAX_MB ?= 2
INDEX_ALIAS ?= $(if $(OPENSEARCH_INDEX),$(OPENSEARCH_INDEX),jlaw-current)
DIET_INPUT ?= indexer/diet_data
DIET_ALIAS ?= $(if $(OPENSEARCH_DIET_INDEX),$(OPENSEARCH_DIET_INDEX),jdiet-current)
DIET_DELAY_SECONDS ?= 3
DIET_FROM_DATE ?=
DIET_UNTIL_DATE ?=
GOLDEN_FILE ?= tests/golden_queries/sample.json
MANIFEST ?= indexer/data/manifest.json
HOST_OPENSEARCH ?= http://127.0.0.1:9200
REPORT_DIR ?= tmp/reindex-reports/$(shell date -u +%Y%m%d-%H%M%S)

.PHONY: up down ps build-backend restart-backend lint typecheck test coverage frontend-coverage frontend-coverage-win frontend-check frontend-check-win check setup-dev setup-dev-uv diet-fetch diet-fetch-range diet-fetch-backfill reindex reindex-diet reindex-versioned reindex-dev validate-index golden golden-full bench-search warning-summary index-report cleanup-indices rollback-index health-smoke api-smoke frontend-smoke smoke

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

ifeq ($(OS),Windows_NT)
frontend-coverage:
	$(POWERSHELL) "Set-Location frontend; npm.cmd run coverage"

frontend-check:
	$(POWERSHELL) "Set-Location frontend; npm.cmd run check"
else
frontend-coverage:
	cd frontend && npm run coverage

frontend-check:
	cd frontend && npm run check
endif

frontend-coverage-win:
	$(POWERSHELL) "Set-Location frontend; npm.cmd run coverage"

frontend-check-win:
	$(POWERSHELL) "Set-Location frontend; npm.cmd run check"

check: lint typecheck test frontend-check

setup-dev:
	$(PYTHON) -m pip install -r requirements-dev.txt
	cd frontend && npm ci

setup-dev-uv:
	uv pip install -r requirements-dev.txt
	cd frontend && npm ci

diet-fetch:
	$(PYTHON) -m indexer.diet_importer --output $(DIET_INPUT) $(DIET_ARGS)

diet-fetch-range:
	@test -n "$(DIET_FROM_DATE)" || (echo "Set DIET_FROM_DATE=YYYY-MM-DD"; exit 2)
	@test -n "$(DIET_UNTIL_DATE)" || (echo "Set DIET_UNTIL_DATE=YYYY-MM-DD"; exit 2)
	$(PYTHON) -m indexer.diet_importer --output $(DIET_INPUT) --all-houses --from-date $(DIET_FROM_DATE) --until-date $(DIET_UNTIL_DATE) --delay-seconds $(DIET_DELAY_SECONDS) $(DIET_ARGS)

diet-fetch-backfill:
	@test -n "$(DIET_SESSION_TO)" || (echo "Set DIET_SESSION_TO=<latest session number>"; exit 2)
	$(PYTHON) -m indexer.diet_importer --output $(DIET_INPUT) --all-houses --session-from 1 --session-to $(DIET_SESSION_TO) --delay-seconds $(DIET_DELAY_SECONDS) $(DIET_ARGS)

# Standard reindex: build a fresh versioned index, validate schema + golden
# queries against it, then atomically switch the alias. The old index stays
# live (and the new one is deleted) if any gate fails.
# Set GOLDEN_FILE= (empty) to skip the golden gate, e.g. for the full corpus
# until tests/golden_queries has corpus-appropriate cases.
reindex:
	@if [ "$(INDEX_INPUT)" != "indexer/sample_corpus" ] && [ "$(GOLDEN_FILE)" = "tests/golden_queries/sample.json" ]; then \
		echo "ERROR: sample golden is only for indexer/sample_corpus. Use GOLDEN_FILE= or a corpus-specific golden file."; \
		exit 2; \
	fi
	@if [ "$(INDEX_INPUT)" = "indexer/sample_corpus" ]; then \
		$(COMPOSE) build backend; \
		$(COMPOSE) run --rm backend python -m indexer.main --input /app/$(INDEX_INPUT) --provider opensearch $(if $(PROGRESS),--progress,) --chunk-size $(BULK_CHUNK) --max-bulk-mb $(BULK_MAX_MB) --write-manifest --versioned --alias $(INDEX_ALIAS) --report-dir /app/$(REPORT_DIR) $(if $(GOLDEN_FILE),--golden /app/$(GOLDEN_FILE),); \
	else \
		OPENSEARCH_HOST=$(HOST_OPENSEARCH) $(PYTHON) -m indexer.main --input $(INDEX_INPUT) --provider opensearch $(if $(PROGRESS),--progress,) --chunk-size $(BULK_CHUNK) --max-bulk-mb $(BULK_MAX_MB) --write-manifest --versioned --alias $(INDEX_ALIAS) --report-dir $(REPORT_DIR) $(if $(GOLDEN_FILE),--golden $(GOLDEN_FILE),); \
	fi

reindex-diet:
	$(MAKE) reindex INDEX_INPUT=$(DIET_INPUT) INDEX_ALIAS=$(DIET_ALIAS) GOLDEN_FILE=

# Backward-compatible alias for the standard versioned reindex.
reindex-versioned: reindex

# Dev-only fast path: index in place without versioning or alias switch.
# Deleted documents from the previous build may linger; not for production.
reindex-dev:
	@if [ "$(INDEX_INPUT)" = "indexer/sample_corpus" ]; then \
		$(COMPOSE) build backend; \
		$(COMPOSE) run --rm backend python -m indexer.main --input /app/$(INDEX_INPUT) --provider opensearch $(if $(PROGRESS),--progress,) --chunk-size $(BULK_CHUNK) --max-bulk-mb $(BULK_MAX_MB) --write-manifest; \
	else \
		OPENSEARCH_HOST=$(HOST_OPENSEARCH) $(PYTHON) -m indexer.main --input $(INDEX_INPUT) --provider opensearch $(if $(PROGRESS),--progress,) --chunk-size $(BULK_CHUNK) --max-bulk-mb $(BULK_MAX_MB) --write-manifest; \
	fi

golden: build-backend
	$(COMPOSE) run --rm backend python -m indexer.golden --file /app/$(GOLDEN_FILE)

golden-full:
	OPENSEARCH_HOST=$(HOST_OPENSEARCH) python -m indexer.golden --file tests/golden_queries/full_corpus.json --size 20

bench-search:
	OPENSEARCH_HOST=$(HOST_OPENSEARCH) python -m indexer.golden --file $(GOLDEN_FILE) --size 20 --report tmp/search_bench.jsonl --markdown tmp/search_bench.md

warning-summary:
	python -m indexer.warning_summary indexer/data/import_warnings.jsonl --json-out tmp/warnings_summary.json

validate-index:
	OPENSEARCH_HOST=$(HOST_OPENSEARCH) python -m indexer.validate_index --manifest $(MANIFEST) --index $(INDEX_ALIAS)

index-report:
	OPENSEARCH_HOST=$(HOST_OPENSEARCH) python -m indexer.index_report --alias $(INDEX_ALIAS) --json-out tmp/index_report.json

cleanup-indices:
	OPENSEARCH_HOST=$(HOST_OPENSEARCH) python -m indexer.cleanup_indices --alias $(INDEX_ALIAS) --keep 3

rollback-index:
	@test -n "$(TO_INDEX)" || (echo "Set TO_INDEX=<concrete-index>"; exit 2)
	OPENSEARCH_HOST=$(HOST_OPENSEARCH) python -m indexer.rollback_index --alias $(INDEX_ALIAS) --to $(TO_INDEX)

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
