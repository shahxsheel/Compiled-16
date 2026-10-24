PY ?= .venv/bin/python
PORT ?= 8000

setup:
	uv venv --python 3.11 .venv
	uv pip install --python $(PY) -r requirements.txt
	$(PY) -m playwright install chromium

test:
	$(PY) -m pytest -q

demo:
	$(PY) -m uvicorn hotpath.server:app --port $(PORT)
