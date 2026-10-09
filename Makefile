VENV := .venv
PY := $(VENV)/bin/python
WEB := apps/web

.PHONY: setup dev down migrate api worker web test test-py test-web lint e2e gen-types

setup:
	python3 -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements-dev.txt
	cd $(WEB) && npm install --silent

dev:
	docker compose up

down:
	docker compose down

migrate:
	cd apps/api && ../../$(VENV)/bin/alembic upgrade head

api:
	cd apps/api && PYTHONPATH=../.. ../../$(VENV)/bin/uvicorn app.main:app --reload --port 8000 --reload-dir app --reload-dir ../../worker

# macOS는 fork된 자식에서 Objective-C 런타임이 죽을 수 있어 fork 없는 SimpleWorker를 쓴다
worker:
	PYTHONPATH=.:apps/api $(VENV)/bin/rq worker cut --url redis://localhost:6379/0 --worker-class rq.worker.SimpleWorker

web:
	cd $(WEB) && npm run dev

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
	PYTHONPATH=apps/api $(PY) -c "import json; from app.main import app; print(json.dumps(app.openapi()))" > packages/shared/openapi.json
	cd $(WEB) && npx openapi-typescript ../../packages/shared/openapi.json -o ../../packages/shared/api.ts
