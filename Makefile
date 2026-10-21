.PHONY: run test lint typecheck check index pdfs schemas calibrate docker

PORT ?= 8000

run:
	uv run uvicorn --factory app.main:create_app --reload --port $(PORT)

test:
	uv run pytest -q

lint:
	uv run ruff check .

typecheck:
	uv run mypy app mcp_servers ingest evaluation scripts/export_tool_schemas.py scripts/demo_runner.py

# Planning-artifact checks (facts vs outlines, Eval Set) and the corpus check.
check:
	uv run python scripts/check_facts_outlines.py .
	uv run python scripts/check_eval_set.py .
	uv run python scripts/check_corpus.py .

pdfs:
	uv run python scripts/build_pdfs.py

index:
	uv run python -m ingest.build_index

schemas:
	uv run python scripts/export_tool_schemas.py

calibrate:
	uv run python -m evaluation.calibrate_threshold

docker:
	docker build -t hr-agent .
	# .env is mounted, not passed with --env-file: Docker keeps inline comments as part of a value.
	docker run --rm -p 8000:8000 -v "$(CURDIR)/.env:/srv/.env:ro" hr-agent
