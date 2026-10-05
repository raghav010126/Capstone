# Keep the virtualenv outside the (OneDrive-synced) project folder.
export UV_PROJECT_ENVIRONMENT ?= $(HOME)/.cache/medishield/venv
PY := uv run --python 3.12

.PHONY: setup dataset dataset-seed7 test
setup:
	uv sync --python 3.12

dataset:            ## official dataset (seed 42) + ground truth + member/claim records
	$(PY) python datagen/harness.py --seed 42 --out data/official
	$(PY) python eval/truth.py data/official
	$(PY) python datagen/records.py data/official

dataset-seed7:      ## unseen generalisation set - never inspect while developing
	$(PY) python datagen/harness.py --seed 7 --out data/seed7
	$(PY) python eval/truth.py data/seed7
	$(PY) python datagen/records.py data/seed7

test:
	$(PY) pytest -q

.PHONY: gold eval lint
gold:               ## retrieval gold set, built from the policy text
	$(PY) python eval/build_retrieval_gold.py data/official

eval:               ## dev split (prompt iteration happens here only) -> docs/EVAL_REPORT.md
	$(PY) python eval/run_eval.py --split $(or $(SPLIT),dev) --dataset $(or $(DATASET),data/official)

lint:
	$(PY) ruff check backend/src eval datagen
