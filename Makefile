PY ?= .venv/bin/python
PORT ?= 8000

.PHONY: setup test demo demo-show demo-fake bench

setup:
	uv venv --python 3.11 .venv
	uv pip install --python $(PY) -r requirements.txt
	$(PY) -m playwright install chromium

test:
	$(PY) -m pytest -q

demo:
	$(PY) -m hotpath --port $(PORT)

demo-show:
	$(PY) -m hotpath --port $(PORT) --show

demo-fake:
	$(PY) -m hotpath --port $(PORT) --fake

bench:
	$(PY) bench.py
