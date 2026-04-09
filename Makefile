# shipit-agent — developer workflow automation
#
# Run `make help` to see all available targets.
#
# All targets are idempotent and safe to re-run. Destructive targets
# (clean, release, publish) are marked explicitly.

.DEFAULT_GOAL := help
SHELL := /bin/bash

# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────

# Auto-detect Python interpreter. Preference order:
#   1. $PYTHON env var (user override: `PYTHON=python3.12 make test`)
#   2. python3.11 (minimum supported, most commonly installed)
#   3. python3.12 (officially supported)
#   4. python3 (system default — may be a version we don't support)
#   5. python   (last-resort fallback)
PYTHON         ?= $(shell \
	command -v python3.11 2>/dev/null || \
	command -v python3.12 2>/dev/null || \
	command -v python3 2>/dev/null || \
	command -v python 2>/dev/null || \
	echo python3)
PIP            ?= $(PYTHON) -m pip
PYTEST         ?= $(PYTHON) -m pytest
VERSION        := $(shell grep -E '^version = ' pyproject.toml | cut -d'"' -f2)
DIST_DIR       := dist
DOCS_DIR       := docs
SITE_DIR       := site
MKDOCS_PORT    ?= 8765

# Colors for pretty output
BOLD           := \033[1m
DIM            := \033[2m
GREEN          := \033[32m
YELLOW         := \033[33m
BLUE           := \033[34m
RED            := \033[31m
RESET          := \033[0m

# ──────────────────────────────────────────────────────────────────────
# Help
# ──────────────────────────────────────────────────────────────────────

.PHONY: help
help: ## Show this help message
	@printf "$(BOLD)shipit-agent$(RESET) $(DIM)v$(VERSION)$(RESET)\n\n"
	@printf "$(BOLD)Usage:$(RESET)\n  make $(BLUE)<target>$(RESET)\n\n"
	@printf "$(BOLD)Targets:$(RESET)\n"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  $(BLUE)%-18s$(RESET) %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\n$(BOLD)Common workflows:$(RESET)\n"
	@printf "  $(DIM)First-time setup:$(RESET)   make install\n"
	@printf "  $(DIM)Daily development:$(RESET)  make test\n"
	@printf "  $(DIM)Before commit:$(RESET)      make check\n"
	@printf "  $(DIM)Docs preview:$(RESET)       make docs-serve\n"
	@printf "  $(DIM)Cut a release:$(RESET)      make release\n"

# ──────────────────────────────────────────────────────────────────────
# Setup
# ──────────────────────────────────────────────────────────────────────

.PHONY: install
install: ## Install package in editable mode with dev + all extras
	@printf "$(BLUE)→$(RESET) Installing shipit-agent in editable mode with dev+all extras...\n"
	$(PIP) install --upgrade pip
	$(PIP) install -e '.[dev,all]'
	@printf "$(GREEN)✓$(RESET) Install complete\n"

.PHONY: install-hooks
install-hooks: ## Install pre-commit hooks (runs checks on every git commit)
	@printf "$(BLUE)→$(RESET) Installing pre-commit hooks...\n"
	@$(PIP) install --quiet pre-commit
	@pre-commit install
	@pre-commit install --hook-type commit-msg 2>/dev/null || true
	@printf "$(GREEN)✓$(RESET) Pre-commit hooks installed. They will run on every git commit.\n"
	@printf "$(DIM)  Run 'make pre-commit' to scan all files now.$(RESET)\n"

.PHONY: install-docs
install-docs: ## Install docs tooling (MkDocs Material + plugins)
	@printf "$(BLUE)→$(RESET) Installing MkDocs Material + plugins...\n"
	$(PIP) install --quiet \
		mkdocs-material \
		mkdocs-git-revision-date-localized-plugin \
		pymdown-extensions
	@printf "$(GREEN)✓$(RESET) Docs tooling ready\n"

.PHONY: install-release
install-release: ## Install release tooling (build + twine)
	@printf "$(BLUE)→$(RESET) Installing build + twine...\n"
	$(PIP) install --quiet --upgrade build twine
	@printf "$(GREEN)✓$(RESET) Release tooling ready\n"

.PHONY: bootstrap
bootstrap: install install-hooks install-docs install-release ## Complete first-time setup (install everything)
	@printf "\n$(GREEN)$(BOLD)✓ Bootstrap complete.$(RESET)\n"
	@printf "$(DIM)Try:$(RESET) make test\n"

# ──────────────────────────────────────────────────────────────────────
# Testing
# ──────────────────────────────────────────────────────────────────────

.PHONY: test
test: ## Run the test suite (fast, quiet)
	@$(PYTEST) -q

.PHONY: test-verbose
test-verbose: ## Run tests with verbose output
	$(PYTEST) -v

.PHONY: test-cov
test-cov: ## Run tests with coverage report
	$(PIP) install --quiet coverage
	$(PYTHON) -m coverage run -m pytest -q
	$(PYTHON) -m coverage report
	$(PYTHON) -m coverage html
	@printf "$(GREEN)✓$(RESET) HTML coverage report: htmlcov/index.html\n"

.PHONY: test-one
test-one: ## Run a single test by keyword — usage: make test-one KEYWORD=reasoning
	@if [ -z "$(KEYWORD)" ]; then \
		printf "$(RED)error:$(RESET) set KEYWORD=<substring>\n"; exit 1; \
	fi
	$(PYTEST) -v -k "$(KEYWORD)"

# ──────────────────────────────────────────────────────────────────────
# Linting & formatting
# ──────────────────────────────────────────────────────────────────────

.PHONY: lint
lint: ## Run ruff linter (check only, no auto-fix)
	@$(PIP) install --quiet ruff
	ruff check .

.PHONY: lint-fix
lint-fix: ## Run ruff linter with auto-fix
	@$(PIP) install --quiet ruff
	ruff check --fix .

.PHONY: format
format: ## Format code with ruff
	@$(PIP) install --quiet ruff
	ruff format .

.PHONY: pre-commit
pre-commit: ## Run all pre-commit hooks on all files (scans entire repo)
	@$(PIP) install --quiet pre-commit
	pre-commit run --all-files

.PHONY: check
check: lint test gitleaks ## Run lint + tests + gitleaks (everything before commit)
	@printf "$(GREEN)✓$(RESET) All checks passed. Safe to commit.\n"

# ──────────────────────────────────────────────────────────────────────
# Security
# ──────────────────────────────────────────────────────────────────────

.PHONY: gitleaks
gitleaks: ## Run gitleaks secret scanner locally
	@if ! command -v gitleaks >/dev/null 2>&1; then \
		printf "$(YELLOW)!$(RESET) gitleaks not installed. Install with: brew install gitleaks\n"; \
		exit 1; \
	fi
	@gitleaks detect --config=.gitleaks.toml --source=. --redact --no-banner --exit-code=1

.PHONY: secrets-scan
secrets-scan: gitleaks ## Alias for gitleaks

# ──────────────────────────────────────────────────────────────────────
# Documentation
# ──────────────────────────────────────────────────────────────────────

.PHONY: docs
docs: ## Build the documentation site into ./site/
	@$(PYTHON) -m mkdocs build --clean
	@printf "$(GREEN)✓$(RESET) Docs built → $(SITE_DIR)/\n"

.PHONY: docs-serve
docs-serve: ## Serve docs locally with live-reload on http://127.0.0.1:$(MKDOCS_PORT)
	@printf "$(BLUE)→$(RESET) Starting MkDocs dev server on http://127.0.0.1:$(MKDOCS_PORT)\n"
	@$(PYTHON) -m mkdocs serve -a 127.0.0.1:$(MKDOCS_PORT)

.PHONY: docs-strict
docs-strict: ## Build docs in strict mode (fails on warnings, used in CI)
	$(PYTHON) -m mkdocs build --strict --clean

# ──────────────────────────────────────────────────────────────────────
# Build & release
# ──────────────────────────────────────────────────────────────────────

.PHONY: clean
clean: ## Remove build artifacts, caches, and site (destructive but local only)
	@printf "$(YELLOW)!$(RESET) Removing build/, dist/, site/, caches...\n"
	rm -rf build/ $(DIST_DIR)/ $(SITE_DIR)/ *.egg-info shipit_agent/*.egg-info
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	@printf "$(GREEN)✓$(RESET) Clean complete\n"

.PHONY: build
build: clean ## Build sdist + wheel into dist/
	@printf "$(BLUE)→$(RESET) Building shipit-agent v$(VERSION)...\n"
	$(PYTHON) -m build
	@printf "$(GREEN)✓$(RESET) Built:\n"
	@ls -lh $(DIST_DIR)/

.PHONY: build-check
build-check: build ## Build + validate dist with twine check
	@printf "$(BLUE)→$(RESET) Running twine check...\n"
	$(PYTHON) -m twine check $(DIST_DIR)/*
	@printf "$(GREEN)✓$(RESET) Distributions valid\n"

.PHONY: publish-test
publish-test: build-check ## Upload to TestPyPI (⚠ needs ~/.pypirc with [testpypi] section)
	@printf "$(YELLOW)!$(RESET) Uploading v$(VERSION) to TestPyPI...\n"
	$(PYTHON) -m twine upload --repository testpypi $(DIST_DIR)/*
	@printf "$(GREEN)✓$(RESET) TestPyPI upload complete\n"
	@printf "$(DIM)Verify:$(RESET) https://test.pypi.org/project/shipit-agent/$(VERSION)/\n"

.PHONY: publish
publish: build-check ## ⚠ IRREVERSIBLE — Upload to PyPI (needs ~/.pypirc)
	@printf "$(RED)$(BOLD)! IRREVERSIBLE$(RESET) About to publish v$(VERSION) to PyPI.\n"
	@printf "Once uploaded, this exact version can never be reused.\n"
	@read -p "Type 'yes' to continue: " confirm; \
	if [ "$$confirm" != "yes" ]; then \
		printf "$(YELLOW)Aborted.$(RESET)\n"; exit 1; \
	fi
	$(PYTHON) -m twine upload $(DIST_DIR)/*
	@printf "$(GREEN)$(BOLD)✓ Published!$(RESET)\n"
	@printf "$(DIM)Live at:$(RESET) https://pypi.org/project/shipit-agent/$(VERSION)/\n"

.PHONY: release
release: check build-check ## Cut a release (check + build + tag). Push manually.
	@printf "$(BLUE)→$(RESET) Tagging v$(VERSION)...\n"
	@if git rev-parse v$(VERSION) >/dev/null 2>&1; then \
		printf "$(RED)error:$(RESET) tag v$(VERSION) already exists. Bump version in pyproject.toml.\n"; exit 1; \
	fi
	git tag -a v$(VERSION) -m "shipit-agent $(VERSION)"
	@printf "$(GREEN)✓$(RESET) Tagged v$(VERSION) locally.\n"
	@printf "\n$(BOLD)Next steps:$(RESET)\n"
	@printf "  1. $(BLUE)git push origin main --tags$(RESET)   # triggers release.yml workflow\n"
	@printf "  2. $(BLUE)make publish$(RESET)                  # or let CI do it via OIDC\n"
	@printf "  3. Create GitHub release page from the tag\n"

# ──────────────────────────────────────────────────────────────────────
# Notebook & example runs
# ──────────────────────────────────────────────────────────────────────

.PHONY: notebook
notebook: ## Launch Jupyter on the streaming demo notebook
	@$(PIP) install --quiet jupyter
	$(PYTHON) -m jupyter notebook notebooks/04_agent_streaming_packets.ipynb

.PHONY: example
example: ## Run the multi-tool agent example
	$(PYTHON) examples/run_multi_tool_agent.py "Research the Bitcoin price and summarize."

# ──────────────────────────────────────────────────────────────────────
# Diagnostics
# ──────────────────────────────────────────────────────────────────────

.PHONY: doctor
doctor: ## Show environment diagnostics
	@printf "$(BOLD)Python version:$(RESET)   "; $(PYTHON) --version
	@printf "$(BOLD)Pip version:$(RESET)      "; $(PIP) --version
	@printf "$(BOLD)Package version:$(RESET)  $(VERSION)\n"
	@printf "$(BOLD)Working directory:$(RESET) $$(pwd)\n"
	@printf "$(BOLD)Git branch:$(RESET)       $$(git branch --show-current 2>/dev/null || echo 'not a git repo')\n"
	@printf "$(BOLD)Git status:$(RESET)\n"
	@git status --short 2>/dev/null || echo "  not a git repo"
	@printf "$(BOLD)Installed shipit_agent:$(RESET)\n"
	@$(PYTHON) -c "import shipit_agent; print('  version:', shipit_agent.__version__); print('  path:', shipit_agent.__file__)" 2>/dev/null || printf "  $(RED)not importable$(RESET)\n"

.PHONY: version
version: ## Print the current package version
	@echo $(VERSION)
