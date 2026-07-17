PYTHON ?= python
VENV ?= .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python
PYTEST := $(VENV)/bin/pytest

.PHONY: venv install test compile build docker clean

venv:
	$(PYTHON) -m venv $(VENV)

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt
	$(PIP) install -e .

test:
	$(PYTEST) -q

compile:
	$(PY) -m compileall -q src

build: compile
	$(PIP) install build
	$(PY) -m build

docker:
	docker build -t policy-gateway:latest .

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache htmlcov
	find src tests -type d -name __pycache__ -prune -exec rm -rf {} +
