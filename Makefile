.DEFAULT_GOAL := help
COMMANDS := setup dev build lint typecheck test test-integration test-heavy generated-check ui-smoke graph graph-check kb kb-check package package-test gx-install gx-bundle
.PHONY: help framework-check framework-ready ai-doctor ci-check version version-check version-write evidence $(COMMANDS)

help:
	@python3 scripts/dev_framework.py help

framework-check:
	python3 scripts/dev_framework.py check

framework-ready:
	python3 scripts/dev_framework.py ready

ai-doctor:
	python3 scripts/dev_framework.py doctor

ci-check:
	python3 scripts/dev_framework.py ci

version:
	python3 scripts/version.py

version-check:
	python3 scripts/version.py --check

version-write:
	python3 scripts/version.py --write

evidence:
	python3 scripts/dev_framework.py evidence ui

$(COMMANDS):
	python3 scripts/dev_framework.py run $@
