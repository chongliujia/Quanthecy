.PHONY: up dev setup-local down logs migrate superuser test-image test-python check-python test-rust test-web contracts check-contracts check test-down

COMPOSE_LOCAL = -f compose.yaml $(if $(wildcard compose.override.yaml),-f compose.override.yaml,)
COMPOSE_TEST = docker compose --env-file /dev/null -p quanthecy-tests -f compose.test.yaml

setup-local:
	python3 scripts/setup_local_env.py
up: setup-local
	docker compose up --build -d --wait
dev: setup-local
	docker compose $(COMPOSE_LOCAL) -f compose.dev.yaml up --build -d --wait
down:
	docker compose down
logs:
	docker compose logs -f backend worker news-worker agent-worker maintenance-worker market-data
migrate:
	docker compose run --rm migrate
superuser:
	docker compose exec backend python apps/backend/manage.py createsuperuser
test-image:
	$(COMPOSE_TEST) build python
test-python: test-image
	$(COMPOSE_TEST) run --rm -T python
check-python: test-image
	$(COMPOSE_TEST) run --rm --no-deps -T python ruff check .
	$(COMPOSE_TEST) run --rm --no-deps -T python ruff format --check .
	$(COMPOSE_TEST) run --rm --no-deps -T python mypy
	$(COMPOSE_TEST) run --rm -T python python apps/backend/manage.py check
	$(COMPOSE_TEST) run --rm -T python python apps/backend/manage.py makemigrations --check --dry-run
test-rust:
	docker build --target checks -f services/market-data/Dockerfile .
test-web:
	docker build --target checks -f apps/web/Dockerfile .
contracts: test-image
	$(COMPOSE_TEST) run --rm --no-deps -T -v "$(CURDIR)/contracts:/app/contracts" python python scripts/export_contracts.py
check-contracts: test-image
	$(COMPOSE_TEST) run --rm --no-deps -T python python scripts/export_contracts.py --check
check: check-python test-python check-contracts test-rust test-web
test-down:
	$(COMPOSE_TEST) down --remove-orphans
