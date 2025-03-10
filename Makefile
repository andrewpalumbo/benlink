.PHONY: docs

all: docs

docs:
	pdoc ./src/benlink -o docs --logo /logo.svg
	cp ./assets/logo-transparent.svg docs/logo.svg

preview-docs:
	python3 -m http.server --directory docs
