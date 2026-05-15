# openmsaify-trading — Makefile
.PHONY: help install test lint format clean docker-build docker-run deploy status logs stop

PYTHON   ?= python3
PIP      ?= pip3
BASE     := $(CURDIR)

help:
	@echo "openmsaify-trading Makefile"
	@echo ""
	@echo "  make install       - Install package in dev mode"
	@echo "  make test          - Run pytest"
	@echo "  make lint          - Ruff lint"
	@echo "  make format        - Ruff format"
	@echo "  make clean         - Remove caches"
	@echo "  make docker-build  - Build Docker image"
	@echo "  make docker-run    - Run Docker container"
	@echo "  make deploy        - Install + enable systemd service"
	@echo "  make status        - Service status"
	@echo "  make logs          - Tail daemon logs"
	@echo "  make stop          - Stop service"

install:
	$(PIP) install -e .

test:
	$(PYTHON) -m pytest -x -q

lint:
	ruff check trading/ tests/

format:
	ruff format trading/ tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache dist build *.egg-info

docker-build:
	docker build -f deploy/Dockerfile -t openmsaify-paper:latest .

docker-run:
	docker run -d --name paper-trade --env-file .env openmsaify-paper:latest

deploy:
	bash deploy/deploy.sh

status:
	systemctl status paper-trade --no-pager

logs:
	journalctl -u paper-trade -f --no-pager

stop:
	systemctl stop paper-trade
