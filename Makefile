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

eval:               ## SPLIT=dev|heldout|all|test20 DATASET=data/official|data/corrected|data/seed7|... -> docs/eval_results/*.json
	$(PY) python eval/run_eval.py --split $(or $(SPLIT),dev) --dataset $(or $(DATASET),data/official) --publish

replay-preflight:   ## verify OCR, policy and retrieval model assets without model API calls
	$(PY) python scripts/preflight_replay.py

samples:            ## reproducible synthetic test documents, labels and both policies
	$(PY) python scripts/package_samples.py

lint:
	$(PY) ruff check backend/src eval datagen

.PHONY: api worker test-fast
api:                ## API + in-process worker on :8100 (Swagger at /docs)
	$(PY) uvicorn medishield.api.main:app --reload --port 8100

worker:             ## standalone queue worker (run the API with MEDISHIELD_WORKER=external)
	$(PY) python -m medishield.worker.queue

test-fast:          ## everything except the real-pipeline integration tests
	$(PY) pytest -q -m "not integration"

test-dynamo:        ## the same suite against DynamoDB (moto, no AWS account needed)
	MEDISHIELD_TEST_DB=dynamodb $(PY) pytest -q -m "not integration"

.PHONY: openapi web-types web web-build
openapi:            ## dump the API's OpenAPI schema for the frontend
	$(PY) python -c "import json,medishield.api.main as m; json.dump(m.app.openapi(), open('frontend/openapi.json','w'), indent=1)"

web-types: openapi  ## generate TypeScript types from the OpenAPI schema (end-to-end typing)
	scripts/web.sh npx openapi-typescript openapi.json -o src/lib/api-types.ts

web:                ## Next.js dev server on :3000 (needs `make api` on :8100, or set NEXT_PUBLIC_API_URL)
	scripts/web.sh run dev

web-build:
	scripts/web.sh run build

.PHONY: web-start e2e
web-start:          ## production build of the UI on :3001 (what gets deployed)
	scripts/web.sh run build && scripts/web.sh run start -- -p 3001

e2e:                ## full UI flow in Chrome against the production build (needs `make web-start`, and `make api` with MEDISHIELD_LLM_OFFLINE=1 CORS_ORIGINS=http://localhost:3001)
	cd frontend && WEB=http://localhost:3001 PATH=$$HOME/.local/node/bin:$$PATH node e2e/flow.mjs /tmp/medishield-e2e

.PHONY: report forensics redteam multilingual gates
gates:              ## quality gates over docs/eval_results (no model calls; CI runs this)
	$(PY) python eval/gates.py

report:             ## assemble docs/EVAL_REPORT.md from docs/eval_results/*.json
	$(PY) python eval/make_report.py

forensics:          ## tamper-detector evaluation (no model calls)
	$(PY) python eval/forensics_eval.py

multilingual:       ## generate the Spanish / Hindi dataset
	$(PY) python datagen/multilingual.py data/official data/multilingual

redteam:            ## build adversarial documents, run them, print the verdict (a few dollars)
	$(PY) python datagen/redteam.py data/official data/redteam
	$(PY) python eval/run_eval.py --dataset data/redteam --split all
	$(PY) python eval/redteam_report.py
	$(PY) python eval/redteam_policy.py
