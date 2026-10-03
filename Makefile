# Thin wrapper around `python -m navigator <stage>`. On Windows without make,
# use `./run.ps1 <target>` (same target names).
PY ?= python

.PHONY: setup ingest extract verify geocode lookups changes summaries all eval test smoke api ingest-doc rerun-live

setup:
	$(PY) -m pip install -e ".[dev,llm]"

ingest extract verify geocode lookups changes summaries all eval:
	$(PY) -m navigator $@

test:
	$(PY) -m pytest -q

smoke:
	$(PY) -m pytest -q -m smoke

api:
	$(PY) -m navigator api

ingest-doc rerun-live:
	$(PY) -m navigator $@ $(DOC)
