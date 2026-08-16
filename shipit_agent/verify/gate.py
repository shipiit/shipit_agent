"""The verify gate — the decisions the loop makes around the ledger.

Three pure helpers so the (risky) loop wiring stays a thin call site:

- :func:`is_verifiable_path` — did this edit touch something a test could cover?
  A README or LICENSE edit must never demand a test run.
- :func:`classify_command` — is a shell command one of the project's verify
  commands (so its exit code should be recorded as pass/fail evidence)?
- :func:`build_verify_nudge` — the synthetic message the loop injects when a turn
  edited code without fresh passing evidence: it names the actual command to run
  and the last failure, and tells the model to run → read → fix → summarise.
"""

from __future__ import annotations

from pathlib import Path

from .ledger import VerificationStatus

#: Extensions/paths whose edit never needs verification — prose, config docs,
#: licences. Everything else is treated as potentially test-covered code.
_NON_CODE_SUFFIXES = frozenset({
    ".md", ".markdown", ".rst", ".txt", ".adoc", ".org",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".lock",
})
_NON_CODE_NAMES = frozenset({
    "license", "licence", "notice", "authors", "contributors",
    "changelog", "readme", "code_of_conduct", ".gitignore", ".gitattributes",
})


def is_verifiable_path(path: str | Path) -> bool:
    """True if editing ``path`` is the kind of change a test could catch."""
    p = Path(str(path))
    if p.suffix.lower() in _NON_CODE_SUFFIXES:
        return False
    stem = p.name.lower()
    if stem in _NON_CODE_NAMES or p.stem.lower() in _NON_CODE_NAMES:
        return False
    return True


def any_verifiable(paths: list[str]) -> bool:
    """Did a turn touch at least one file worth verifying?"""
    return any(is_verifiable_path(p) for p in paths)


def classify_command(command: str, verify_commands: list[str]) -> bool:
    """Is ``command`` one of the project's verify commands?

    A canonical match — the detected command appears as a token-ish substring of
    what actually ran (``cd x && pytest tests/ -q`` matches ``pytest``). Kept
    deliberately loose: a false positive records real exit-code evidence, which
    is exactly what we want; a false negative just misses one pass.
    """
    if not command or not verify_commands:
        return False
    lowered = command.lower()
    for verify in verify_commands:
        head = verify.lower().split()[0] if verify.split() else ""
        # Match the tool head (pytest / npm / make) — the run may add flags/paths.
        if head and head in lowered:
            return True
    return False


def build_verify_nudge(
    status: VerificationStatus, verify_commands: list[str]
) -> str:
    """The message injected when edited code lacks fresh passing evidence."""
    commands = ", ".join(f"`{c}`" for c in verify_commands) or "the project's tests"
    failure = ""
    if status.last_passed is False and status.last_summary:
        failure = (
            f" The last run of {('`' + status.last_command + '`') if status.last_command else 'the tests'} "
            f"FAILED:\n{status.last_summary.strip()[:800]}\n"
        )
    return (
        "[System: You edited code in this turn, but the workspace has no fresh "
        f"passing verification. Run {commands} now, read any failure, repair the "
        f"code, and summarise what passed.{failure} Do not report the task as done "
        "until a verification command has passed on the current code.]"
    )
