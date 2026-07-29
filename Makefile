SHELL := /bin/sh

.PHONY: sanity-check test verify

sanity-check:
	./tools/sanity-check

test:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(CURDIR)/src" python3 -m unittest discover -s tests

verify:
	./tools/verify
