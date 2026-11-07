"""Tool call → human sentence.

The transcript never shows a raw tool name. Every call becomes a **verb and a
target** the way a colleague would narrate it — ``Read app.py``, ``Ran code
const risk = scoreAccounts(…``, ``Fetched github.com`` — in the present tense
while it runs and the past tense once it lands::

    >>> summarize("read_file", {"path": "app.py"}).past_label()
    'Read app.py'
    >>> summarize("read_file", {"path": "app.py"}).present_label()
    'Reading app.py'
    >>> describe_count("write_file", 5)
    'Wrote 5 files'

Three layers, in priority order:

1. :data:`VERBS` — a hand-written spec per built-in tool.
2. :data:`_TARGET_EXTRACTORS` — per-tool logic for the interesting argument
   (a URL's host, a code snippet's first line).
3. A humanizing fallback for MCP servers, custom tools, and anything else that
   was never in the table — ``search_issues`` becomes ``Searched issues``.

The fallback is why this is a dict and not an exhaustive match: shipit has 50
built-ins plus an open-ended set of MCP tools with arbitrary names.

The package: ``spec`` (the spec and icons), ``table`` (the built-ins),
``targets``, ``humanize``, and ``registry`` (registration and summaries).
"""

from __future__ import annotations

from .registry import (
    ToolSummary as ToolSummary,
    describe_count as describe_count,
    describe_count_present as describe_count_present,
    icon_for as icon_for,
    is_read_only as is_read_only,
    register_verb as register_verb,
    register_verbs as register_verbs,
    registered_verbs as registered_verbs,
    spec_for as spec_for,
    summarize as summarize,
    unregister_verb as unregister_verb,
)
from .spec import (
    APP as APP,
    ASCII_ICONS as ASCII_ICONS,
    CHAT as CHAT,
    CODE as CODE,
    CREATE as CREATE,
    DATA as DATA,
    DOC as DOC,
    EDIT as EDIT,
    FILE as FILE,
    IMAGE as IMAGE,
    LINK as LINK,
    MAIL as MAIL,
    MEMORY as MEMORY,
    SEARCH as SEARCH,
    STOP as STOP,
    THINK as THINK,
    TOOL as TOOL,
    VerbSpec as VerbSpec,
    WEB as WEB,
    pluralize as pluralize,
)
from .table import (
    VERBS as VERBS,
)

__all__ = [
    "VerbSpec",
    "ToolSummary",
    "VERBS",
    "summarize",
    "describe_count",
    "describe_count_present",
    "icon_for",
    "is_read_only",
    "pluralize",
]
