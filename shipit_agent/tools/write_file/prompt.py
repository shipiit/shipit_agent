"""Guidance the model sees alongside the write_file tool."""

DESCRIPTION = (
    "Create a new file with the given content. Refuses if the file already "
    "exists — use edit_file to change an existing file."
)

INSTRUCTIONS = (
    "write_file creates; edit_file changes. If a write is refused because the "
    "file exists, read it and edit rather than choosing a new name."
)
