.PHONY: install init-db serve worker test check migrate

install:
	python -m pip install -e ".[test]"

init-db:
	polymarket-lab init-db

migrate:
	alembic upgrade head

serve:
	polymarket-lab serve

worker:
	polymarket-lab paper-worker

test:
	pytest -q

check:
	python -m compileall -q app tests migrations
	pytest -q
