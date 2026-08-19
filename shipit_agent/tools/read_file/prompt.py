"""Guidance the model sees alongside the read_file tool."""

DESCRIPTION = (
    "Read a file with line numbers. Reading is required before editing: an edit "
    "to a file this session has not read will be refused."
)

INSTRUCTIONS = (
    "Read a file before editing it. For a large file, read the region you need "
    "with offset and limit rather than the whole thing."
)
