.PHONY: up dev setup-local down logs migrate superuser test-python check-python test-rust test-web contracts check-contracts

COMPOSE_LOCAL = -f compose.yaml $(if $(wildcard compose.override.yaml),-f compose.override.yaml,)

setup-local:
	python3 scripts/setup_local_env.py
up: setup-local
	docker compose up --build -d --wait
dev: setup-local
	docker compose $(COMPOSE_LOCAL) -f compose.dev.yaml up --build -d --wait
down:
	docker compose down
logs:
	docker compose logs -f backend worker news-worker agent-worker market-data
migrate:
	docker compose run --rm migrate
superuser:
	docker compose exec backend python apps/backend/manage.py createsuperuser
test-python:
	docker compose $(COMPOSE_LOCAL) -f compose.dev.yaml run --build --rm backend pytest --ds=config.settings.test -p no:cacheprovider
check-python:
	docker compose $(COMPOSE_LOCAL) -f compose.dev.yaml run --build --rm backend ruff check .
	docker compose $(COMPOSE_LOCAL) -f compose.dev.yaml run --rm backend ruff format --check .
	docker compose $(COMPOSE_LOCAL) -f compose.dev.yaml run --rm backend mypy
test-rust:
	docker build --target checks -f services/market-data/Dockerfile .
test-web:
	docker build --target checks -f apps/web/Dockerfile .
contracts:
	docker compose $(COMPOSE_LOCAL) -f compose.dev.yaml run --build --rm -v "$(CURDIR)/contracts:/app/contracts" backend python scripts/export_contracts.py
check-contracts:
	docker compose $(COMPOSE_LOCAL) -f compose.dev.yaml run --build --rm backend python scripts/export_contracts.py --check
