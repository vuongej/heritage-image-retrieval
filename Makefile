.PHONY: up down seed eval loadtest report test lint logs ps clean

up:
	cp -n .env.example .env || true
	docker compose up -d --build

down:
	docker compose down -v

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=100 api worker

seed:
	docker compose run --rm api python -m scripts.seed_from_csv

eval:
	docker compose run --rm api python -m evals.harness --goldset evals/goldset

loadtest:
	docker compose --profile loadtest run --rm k6 run /scripts/loadtest.js --out json=/reports/raw.json

report:
	docker compose run --rm api python -m loadtest.make_report /reports/raw.json -o /reports/report.html

test:
	docker compose run --rm api pytest -q

lint:
	docker compose run --rm api ruff check .

clean:
	docker compose down -v --remove-orphans
