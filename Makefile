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
# Current package version (read from pyproject.toml). Used for display and
# `make release` which tags the current version as-is. Intentionally named
# CURRENT_VERSION so it doesn't shadow the user-supplied `VERSION=x.y.z` arg
# that `make bump` and `make new-release` accept.
CURRENT_VERSION := $(shell grep -E '^version = ' pyproject.toml | cut -d'"' -f2)
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
	@printf "$(BOLD)shipit-agent$(RESET) $(DIM)v$(CURRENT_VERSION)$(RESET)\n\n"
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
	@printf "$(BLUE)→$(RESET) Building shipit-agent v$(CURRENT_VERSION)...\n"
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
	@printf "$(YELLOW)!$(RESET) Uploading v$(CURRENT_VERSION) to TestPyPI...\n"
	$(PYTHON) -m twine upload --repository testpypi $(DIST_DIR)/*
	@printf "$(GREEN)✓$(RESET) TestPyPI upload complete\n"
	@printf "$(DIM)Verify:$(RESET) https://test.pypi.org/project/shipit-agent/$(CURRENT_VERSION)/\n"

.PHONY: publish
publish: build-check ## ⚠ IRREVERSIBLE — Upload to PyPI (needs ~/.pypirc)
	@printf "$(RED)$(BOLD)! IRREVERSIBLE$(RESET) About to publish v$(CURRENT_VERSION) to PyPI.\n"
	@printf "Once uploaded, this exact version can never be reused.\n"
	@read -p "Type 'yes' to continue: " confirm; \
	if [ "$$confirm" != "yes" ]; then \
		printf "$(YELLOW)Aborted.$(RESET)\n"; exit 1; \
	fi
	$(PYTHON) -m twine upload $(DIST_DIR)/*
	@printf "$(GREEN)$(BOLD)✓ Published!$(RESET)\n"
	@printf "$(DIM)Live at:$(RESET) https://pypi.org/project/shipit-agent/$(CURRENT_VERSION)/\n"

.PHONY: bump
bump: ## Bump version across pyproject.toml + CHANGELOGs — usage: make bump VERSION=1.0.2
	@if [ -z "$(VERSION)" ]; then \
		printf "$(RED)error:$(RESET) set VERSION=x.y.z\n"; \
		printf "$(DIM)example:$(RESET) make bump VERSION=1.0.2\n"; exit 1; \
	fi
	@$(PYTHON) scripts/bump_version.py $(VERSION)

.PHONY: new-release
new-release: ## Full release prep: bump version + test + lint + gitleaks + build + twine check. Usage: make new-release VERSION=1.0.2
	@if [ -z "$(VERSION)" ]; then \
		printf "$(RED)error:$(RESET) set VERSION=x.y.z\n"; \
		printf "$(DIM)example:$(RESET) make new-release VERSION=1.0.2\n"; \
		printf "\nThis command will:\n"; \
		printf "  1. Bump version in pyproject.toml + CHANGELOG.md + docs/changelog.md\n"; \
		printf "  2. Run pytest (all tests must pass)\n"; \
		printf "  3. Run gitleaks (no leaks allowed)\n"; \
		printf "  4. Build sdist + wheel into dist/\n"; \
		printf "  5. Validate with twine check\n"; \
		printf "\n$(YELLOW)It does NOT commit, tag, push, or publish — you do that manually.$(RESET)\n"; \
		exit 1; \
	fi
	@printf "$(BOLD)$(BLUE)━━━ Release prep for v$(VERSION) ━━━$(RESET)\n\n"
	@printf "$(BOLD)Step 1/5 — Bump version$(RESET)\n"
	@$(PYTHON) scripts/bump_version.py $(VERSION)
	@printf "\n$(BOLD)Step 2/5 — Run tests$(RESET)\n"
	@$(MAKE) --no-print-directory test
	@printf "\n$(BOLD)Step 3/5 — Scan for secrets$(RESET)\n"
	@$(MAKE) --no-print-directory gitleaks
	@printf "\n$(BOLD)Step 4/5 — Build distributions$(RESET)\n"
	@$(MAKE) --no-print-directory build
	@printf "\n$(BOLD)Step 5/5 — Validate with twine$(RESET)\n"
	@$(PYTHON) -m twine check $(DIST_DIR)/*
	@printf "\n$(GREEN)$(BOLD)✓ Release prep complete for v$(VERSION)$(RESET)\n\n"
	@printf "$(BOLD)What happens next (run these in order):$(RESET)\n"
	@printf "  $(DIM)# Review everything first$(RESET)\n"
	@printf "  git diff\n"
	@printf "  git status\n"
	@printf "\n"
	@printf "  $(DIM)# Edit CHANGELOG.md — fill in real release notes$(RESET)\n"
	@printf "  \n"
	@printf "  $(DIM)# Commit everything$(RESET)\n"
	@printf "  git add -A && git commit -m 'release: v$(VERSION)'\n"
	@printf "\n"
	@printf "  $(DIM)# Tag + push$(RESET)\n"
	@printf "  git tag -a v$(VERSION) -m 'shipit-agent $(VERSION)'\n"
	@printf "  git push origin main --tags\n"
	@printf "\n"
	@printf "  $(DIM)# Publish to PyPI (asks for confirmation)$(RESET)\n"
	@printf "  make publish\n"
	@printf "\n"
	@printf "$(DIM)All of the above are YOUR commands — nothing destructive has been run yet.$(RESET)\n"

.PHONY: ship
ship: new-release ## Alias for new-release
	@true

.PHONY: tag
tag: ## Create + push the git tag for CURRENT_VERSION (uses gh under the hood)
	@if git rev-parse v$(CURRENT_VERSION) >/dev/null 2>&1; then \
		printf "$(YELLOW)!$(RESET) tag v$(CURRENT_VERSION) already exists locally\n"; \
	else \
		printf "$(BLUE)→$(RESET) Creating tag v$(CURRENT_VERSION)...\n"; \
		git tag -a v$(CURRENT_VERSION) -m "shipit-agent $(CURRENT_VERSION)"; \
		printf "$(GREEN)✓$(RESET) Tagged v$(CURRENT_VERSION) locally\n"; \
	fi
	@printf "$(BLUE)→$(RESET) Pushing tag to origin...\n"
	git push origin v$(CURRENT_VERSION)
	@printf "$(GREEN)✓$(RESET) Tag pushed: https://github.com/shipiit/shipit_agent/releases/tag/v$(CURRENT_VERSION)\n"

.PHONY: changelog-show
changelog-show: ## Print the CHANGELOG section for CURRENT_VERSION
	@$(PYTHON) scripts/extract_changelog_section.py $(CURRENT_VERSION)

.PHONY: github-release
github-release: build-check ## Create a GitHub Release for CURRENT_VERSION (notes from CHANGELOG, attaches dist/*)
	@if ! command -v gh >/dev/null 2>&1; then \
		printf "$(RED)error:$(RESET) GitHub CLI (gh) is not installed.\n"; \
		printf "$(DIM)install:$(RESET) brew install gh\n"; \
		printf "$(DIM)login:$(RESET)   gh auth login\n"; \
		exit 1; \
	fi
	@if ! gh auth status >/dev/null 2>&1; then \
		printf "$(RED)error:$(RESET) gh CLI is not logged in. Run: gh auth login\n"; \
		exit 1; \
	fi
	@if ! git rev-parse v$(CURRENT_VERSION) >/dev/null 2>&1; then \
		printf "$(RED)error:$(RESET) tag v$(CURRENT_VERSION) does not exist locally.\n"; \
		printf "$(DIM)create it:$(RESET) make tag\n"; \
		exit 1; \
	fi
	@printf "$(BLUE)→$(RESET) Extracting release notes for v$(CURRENT_VERSION) from CHANGELOG.md...\n"
	@$(PYTHON) scripts/extract_changelog_section.py $(CURRENT_VERSION) > /tmp/_shipit_release_notes.md
	@printf "$(DIM)Notes preview (first 10 lines):$(RESET)\n"
	@head -10 /tmp/_shipit_release_notes.md | sed 's/^/    /'
	@printf "$(DIM)...$(RESET)\n\n"
	@if gh release view v$(CURRENT_VERSION) >/dev/null 2>&1; then \
		printf "$(YELLOW)!$(RESET) Release v$(CURRENT_VERSION) already exists on GitHub. Updating...\n"; \
		gh release edit v$(CURRENT_VERSION) \
			--title "v$(CURRENT_VERSION)" \
			--notes-file /tmp/_shipit_release_notes.md \
			--latest; \
		gh release upload v$(CURRENT_VERSION) $(DIST_DIR)/* --clobber; \
	else \
		printf "$(BLUE)→$(RESET) Creating GitHub Release v$(CURRENT_VERSION)...\n"; \
		gh release create v$(CURRENT_VERSION) \
			--title "v$(CURRENT_VERSION)" \
			--notes-file /tmp/_shipit_release_notes.md \
			--latest \
			$(DIST_DIR)/*; \
	fi
	@rm -f /tmp/_shipit_release_notes.md
	@printf "\n$(GREEN)$(BOLD)✓ GitHub Release published$(RESET)\n"
	@printf "$(DIM)View at:$(RESET) https://github.com/shipiit/shipit_agent/releases/tag/v$(CURRENT_VERSION)\n"

.PHONY: ship-it
ship-it: ## ⚠ FULL RELEASE: tag + push + publish to PyPI + GitHub Release. CURRENT_VERSION must be ready.
	@printf "$(BOLD)$(BLUE)━━━ Full release of v$(CURRENT_VERSION) ━━━$(RESET)\n\n"
	@printf "This will run, $(BOLD)IN ORDER$(RESET):\n"
	@printf "  1. $(BLUE)make check$(RESET)            (lint + tests + gitleaks)\n"
	@printf "  2. $(BLUE)make build-check$(RESET)      (build sdist + wheel + twine check)\n"
	@printf "  3. $(BLUE)make tag$(RESET)              (create + push git tag)\n"
	@printf "  4. $(BLUE)make publish$(RESET)          ($(RED)IRREVERSIBLE$(RESET) — uploads to PyPI)\n"
	@printf "  5. $(BLUE)make github-release$(RESET)   (creates GitHub Release with notes + dist artifacts)\n\n"
	@read -p "Type 'ship it' to proceed: " confirm; \
	if [ "$$confirm" != "ship it" ]; then \
		printf "$(YELLOW)Aborted.$(RESET)\n"; exit 1; \
	fi
	@$(MAKE) --no-print-directory check
	@$(MAKE) --no-print-directory build-check
	@$(MAKE) --no-print-directory tag
	@$(MAKE) --no-print-directory publish
	@$(MAKE) --no-print-directory github-release
	@printf "\n$(GREEN)$(BOLD)🚀 Released v$(CURRENT_VERSION)!$(RESET)\n"
	@printf "$(DIM)PyPI:$(RESET)   https://pypi.org/project/shipit-agent/$(CURRENT_VERSION)/\n"
	@printf "$(DIM)GitHub:$(RESET) https://github.com/shipiit/shipit_agent/releases/tag/v$(CURRENT_VERSION)\n"

.PHONY: release
release: check build-check ## Cut a release from CURRENT version (check + build + tag). Use new-release to bump first.
	@printf "$(BLUE)→$(RESET) Tagging v$(CURRENT_VERSION)...\n"
	@if git rev-parse v$(CURRENT_VERSION) >/dev/null 2>&1; then \
		printf "$(RED)error:$(RESET) tag v$(CURRENT_VERSION) already exists. Use 'make new-release VERSION=x.y.z' to bump first.\n"; exit 1; \
	fi
	git tag -a v$(CURRENT_VERSION) -m "shipit-agent $(CURRENT_VERSION)"
	@printf "$(GREEN)✓$(RESET) Tagged v$(CURRENT_VERSION) locally.\n"
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
	@printf "$(BOLD)Package version:$(RESET)  $(CURRENT_VERSION)\n"
	@printf "$(BOLD)Working directory:$(RESET) $$(pwd)\n"
	@printf "$(BOLD)Git branch:$(RESET)       $$(git branch --show-current 2>/dev/null || echo 'not a git repo')\n"
	@printf "$(BOLD)Git status:$(RESET)\n"
	@git status --short 2>/dev/null || echo "  not a git repo"
	@printf "$(BOLD)Installed shipit_agent:$(RESET)\n"
	@$(PYTHON) -c "import shipit_agent; print('  version:', shipit_agent.__version__); print('  path:', shipit_agent.__file__)" 2>/dev/null || printf "  $(RED)not importable$(RESET)\n"

.PHONY: version
version: ## Print the current package version
	@echo $(CURRENT_VERSION)
