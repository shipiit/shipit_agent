"""Guidance the model sees alongside the grep tool."""

DESCRIPTION = (
    "Search file contents with a regular expression. Returns matching lines with "
    "their file and line number, grouped by file."
)

INSTRUCTIONS = "Narrow with a glob before widening the pattern. A search returning hundreds of hits has answered nothing and cost a great deal."
