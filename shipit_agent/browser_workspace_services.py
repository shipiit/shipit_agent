"""The Google Workspace services the browser Workspace tool can change."""

from __future__ import annotations

SERVICES = {
    "docs": ("https://docs.googleapis.com/v1/documents", "documentId"),
    "sheets": ("https://sheets.googleapis.com/v4/spreadsheets", "spreadsheetId"),
    "slides": ("https://slides.googleapis.com/v1/presentations", "presentationId"),
}

