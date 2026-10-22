.PHONY: up down ps logs test test-web lint testcases loadtest report clean

up:
	cp -n .env.example .env || true
	docker compose up -d --build

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=100 api processor web

test:
	pytest -q

test-web:
	cd web/spa && npm test

lint:
	ruff check .

testcases:
	python -X utf8 -m scripts.eval_testcases --pace 2.5

loadtest:
	docker compose --profile loadtest run --rm k6

report:
	python -m loadtest.make_report reports/loadtest/raw.json -o reports/loadtest/report.html

clean:
	docker compose down -v --remove-orphans
