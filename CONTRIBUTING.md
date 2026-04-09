# Contributing to shipit-agent

Thanks for your interest in contributing. This guide covers everything you need to know to set up a dev environment, make changes, and get them merged.

## Code of conduct

Be kind. Assume good faith. Focus on the code, not the person. Disagreements are fine; disrespect is not.

## How to contribute

### Reporting bugs

Open a [bug report](https://github.com/shipiit/shipit_agent/issues/new?template=bug_report.yml) with:

- A clear title
- Steps to reproduce (minimum code that triggers the issue)
- What you expected vs. what happened
- Your environment: Python version, OS, shipit-agent version, LLM provider
- Full stack trace if there's an exception

The more specific you are, the faster we can fix it.

### Proposing features

Open a [feature request](https://github.com/shipiit/shipit_agent/issues/new?template=feature_request.yml) first. Describe:

- What problem you're trying to solve
- Your proposed API (rough sketch is fine)
- Why this should live in shipit-agent core rather than userland code

For non-trivial features (new LLM adapter, new built-in tool, runtime changes), get agreement on the approach in the issue **before** writing code. Saves everyone time if the direction isn't right.

### Submitting a pull request

1. Fork the repo and create a feature branch from `main`
2. Make your changes (see [Development setup](#development-setup))
3. Run tests locally: `pytest -q`
4. Run pre-commit hooks: `pre-commit run --all-files`
5. Commit with a [conventional commit](https://www.conventionalcommits.org/) message (see [Commit style](#commit-style))
6. Push and open a PR against `main`
7. Fill out the PR template — describe what changed and why, link any related issue
8. CI will run tests, lint, and secret-scan. Address any failures.

## Development setup

### Prerequisites

- **Python 3.11 or 3.12** (3.13 support coming)
- **Git**
- (Optional) **Playwright** if you're working on `open_url` or browser-based tools

### Clone and install

```bash
git clone https://github.com/shipiit/shipit_agent.git
cd shipit_agent

# Create a virtualenv
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install in editable mode with dev extras
pip install -e '.[dev]'

# If you're working on LLM adapters, install provider SDKs too
pip install -e '.[all]'
```

### Install pre-commit hooks

```bash
pip install pre-commit
pre-commit install
```

Now every `git commit` will run: trailing whitespace trim, YAML/TOML validation, and gitleaks secret scan.

### Playwright (optional)

Only needed if you're touching `open_url_tool.py` or `playwright_browser_tool.py`:

```bash
pip install -e '.[playwright]'
playwright install chromium
```

### Run the test suite

```bash
pytest -q                    # fast, quiet
pytest -v                    # verbose
pytest tests/test_runtime.py # single file
pytest -k "reasoning"        # match by keyword
```

All tests should pass before you push. The CI runs `pytest -q` on Python 3.11 and 3.12.

### Run a real agent locally

```bash
cp .env.example .env
# Edit .env — set SHIPIT_LLM_PROVIDER and the matching credential env var
python examples/run_multi_tool_agent.py "What is 17 * 23? Use the code interpreter."
```

### Build the docs locally

```bash
pip install mkdocs-material mkdocs-git-revision-date-localized-plugin pymdown-extensions
mkdocs serve -a 127.0.0.1:8765
# Open http://127.0.0.1:8765
```

## Code style

- **Python 3.11+ syntax.** `from __future__ import annotations` at the top of every file.
- **Type hints everywhere.** `list[str]` not `List[str]`, `X | None` not `Optional[X]`.
- **Dataclasses with `slots=True`** for models and small structs.
- **Lazy imports inside functions** for optional dependencies (e.g. `from playwright.sync_api import sync_playwright` inside a method, not at module top).
- **No f-string emoji in file contents** unless the user explicitly asks — lean toward plain text.
- **Comments explain *why*, not *what*.** The code explains what.
- **Error handling at boundaries, not inside.** Validate at tool entry, trust internal code.

## Commit style

We use [Conventional Commits](https://www.conventionalcommits.org/). The format is:

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**

- `feat` — new feature
- `fix` — bug fix
- `docs` — documentation only
- `refactor` — code change that neither fixes a bug nor adds a feature
- `test` — adding or updating tests
- `chore` — build process, tooling, config
- `perf` — performance improvement
- `ci` — CI/CD config changes

**Scopes** (use any that fits):

`runtime`, `adapters`, `tools`, `mcp`, `stores`, `streaming`, `reasoning`, `bedrock`, `openai`, `anthropic`, `vertex`, `litellm`, `docs`, `ci`, `release`

**Examples:**

```
feat(vertex): support service-account JSON file + project/location kwargs

fix(bedrock): inject planner output as user message, not orphan tool-result

docs(guides): add reasoning & thinking steps guide

refactor(openai): extract _is_reasoning_model into a regex-based helper
```

## PR checklist

Before marking your PR as ready for review:

- [ ] Tests pass locally (`pytest -q`)
- [ ] Pre-commit hooks pass (`pre-commit run --all-files`)
- [ ] Added tests for new functionality
- [ ] Updated docs (`docs/`) if you changed public API
- [ ] Updated `CHANGELOG.md` under the `[Unreleased]` section
- [ ] No secrets, tokens, API keys, or `.env` contents in the diff
- [ ] No `.pyc`, `.DS_Store`, or other tracked build artifacts
- [ ] Commit messages follow conventional-commits format

## Adding a new LLM adapter

1. Create `shipit_agent/llms/<provider>_adapter.py` with a class implementing the `LLM` protocol (see `shipit_agent/llms/base.py`)
2. Extract reasoning content using `_extract_reasoning()` from `litellm_adapter.py` — **this is required** so reasoning events work end-to-end
3. Export from `shipit_agent/llms/__init__.py`
4. Add provider handling to `examples/run_multi_tool_agent.py:build_llm_from_env()`
5. Document in `docs/reference/adapters.md`
6. Add to `CHANGELOG.md` under `[Unreleased]`
7. Write a test in `tests/test_adapters.py` (stub LLM response, verify tool calls + reasoning extraction)

## Adding a new built-in tool

1. Create `shipit_agent/tools/<tool_name>/` with `__init__.py`, `<tool_name>_tool.py`, and `prompt.py`
2. Tool class must have: `name`, `description`, `prompt_instructions`, `schema()`, `run(context, **kwargs)`
3. Return `ToolOutput(text, metadata)` — do not raise for expected errors
4. Export from `shipit_agent/tools/__init__.py`
5. Add to `get_builtin_tools()` in `shipit_agent/builtins.py`
6. Document in `docs/guides/prebuilt-tools.md` and `docs/reference/tools.md`
7. Add to `CHANGELOG.md` under `[Unreleased]`
8. Write a test in `tests/test_tools.py`

## Release process (maintainers only)

1. Update `CHANGELOG.md` — move `[Unreleased]` items to a new versioned section
2. Bump version in `pyproject.toml`
3. Commit: `chore(release): prepare vX.Y.Z`
4. Tag: `git tag -a vX.Y.Z -m "vX.Y.Z"`
5. Push: `git push origin main --tags`
6. CI publishes to PyPI automatically via `.github/workflows/release.yml`
7. Docs auto-deploy via `.github/workflows/docs.yml`
8. Create a GitHub Release from the tag with the changelog section as notes

## Questions?

Open a [discussion](https://github.com/shipiit/shipit_agent/discussions) or an issue. We're friendly.
