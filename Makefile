VENV := .venv
PY := $(VENV)/bin/python
WEB := apps/web

.PHONY: setup dev down test test-py test-web lint e2e gen-types

setup:
	python3 -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements-dev.txt
	cd $(WEB) && npm install --silent

dev:
	docker compose up

down:
	docker compose down

test: test-py test-web

test-py:
	$(PY) -m pytest

test-web:
	cd $(WEB) && npx vitest run

lint:
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/mypy
	cd $(WEB) && npx tsc --noEmit && npx eslint .

e2e:
	$(PY) scripts/e2e.py $(if $(LLM),--llm,)

gen-types:
	@echo "Phase 3에서 구현: OpenAPI → packages/shared TS 타입" && exit 1
