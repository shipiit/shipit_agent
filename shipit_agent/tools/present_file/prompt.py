"""Guidance surfaced to the model for the present_file tool."""

PRESENT_FILE_PROMPT = (
    "Use present_file to hand a finished file to the user as a downloadable, "
    "previewable deliverable — after you generate an image, speak audio, render "
    "a PDF, or save a document/spreadsheet. Pass the file's path (and an optional "
    "title). It does not create the file — create or save it first, then present "
    "it. Prefer presenting one clear final deliverable over pasting a path into prose."
)
