"""Guidance the model sees alongside the glob tool."""

DESCRIPTION = (
    "Find files by name pattern (for example `src/**/*.py`). Returns paths "
    "sorted by modification time, most recent first."
)

INSTRUCTIONS = "Use glob rather than `find` or `ls -R`: it skips build and dependency directories and its output is bounded."
