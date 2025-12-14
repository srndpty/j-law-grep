SHELL := /bin/sh
COMPOSE := docker compose -f deploy/docker-compose.yml --env-file .env

export MSYS2_ARG_CONV_EXCL = *

INDEX_INPUT ?= indexer/sample_corpus

.PHONY: up down ps restart-backend reindex api-smoke

up:
	$(COMPOSE) up -d --build

reindex:
  $(COMPOSE) run --rm backend python -m indexer.main --input /app/$(INDEX_INPUT) --provider opensearch

down:
	$(COMPOSE) down -v

ps:
	$(COMPOSE) ps

restart-backend:
	$(COMPOSE) restart backend

api-smoke:
	curl -sS http://localhost:8000/api/search -X POST \
	  -H 'Content-Type: application/json' \
	  -d '{"q": "民法 709条", "mode": "literal", "filters": {"law": "民法"}, "size": 5, "page": 1}' | \
	  python -c "import json,sys; d=json.load(sys.stdin); h=d.get('hits', []); print(json.dumps(h[0], ensure_ascii=False, indent=2) if h else 'no hits')"
