PYTHON ?= python3

.PHONY: install run

install:
	uv tool install --force .

run:
	uv run transient --reload
