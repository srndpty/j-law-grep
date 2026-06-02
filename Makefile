SHELL := /bin/sh
COMPOSE := docker compose -f deploy/docker-compose.yml --env-file .env

export MSYS2_ARG_CONV_EXCL = *

INDEX_INPUT ?= indexer/sample_corpus
PROGRESS ?= 1
BULK_CHUNK ?= 1000
BULK_MAX_MB ?= 40
INDEX_ALIAS ?= jlaw-current
GOLDEN_FILE ?= tests/golden_queries/sample.json
MANIFEST ?= indexer/data/manifest.json

.PHONY: up down ps build-backend restart-backend reindex reindex-versioned validate-index golden api-smoke

up:
	$(COMPOSE) up -d --build --remove-orphans

build-backend:
	$(COMPOSE) build backend

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

down:
	$(COMPOSE) down -v --remove-orphans

ps:
	$(COMPOSE) ps

restart-backend:
	$(COMPOSE) restart backend

api-smoke:
	curl -sS http://localhost:8000/api/search -X POST \
	  -H 'Content-Type: application/json' \
	  -d '{"q": "民法 709条", "mode": "literal", "filters": {"law": "民法"}, "size": 5, "page": 1}' | \
	  python -c "import json,sys; d=json.load(sys.stdin); h=d.get('hits', []); print(json.dumps(h[0], ensure_ascii=False, indent=2) if h else 'no hits')"
