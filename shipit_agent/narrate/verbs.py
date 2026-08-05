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
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

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

# Longest target we will inline into a one-line label before eliding.
_TARGET_LIMIT = 60


def _clip(text: str, limit: int = _TARGET_LIMIT) -> str:
    """Collapse whitespace and elide to *limit* characters with an ellipsis."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    """``2, "file"`` → ``"2 files"``."""
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"


@dataclass(frozen=True, slots=True)
class VerbSpec:
    """How one tool narrates itself.

    ``past``/``present`` are the bare verbs (``"Read"`` / ``"Reading"``).
    ``noun`` drives count-aware labels — with ``noun="file"`` five calls read
    ``"Read 5 files"``; without one they read ``"Read 5 times"``.
    ``args`` lists argument names to try, in order, when picking the target.

    ``count_verb`` exists because a verb that reads well with a *target* often
    collides with its own noun in a count: ``edit_file`` wants ``Edited
    app.py`` but ``Made 3 edits``, and ``sql`` wants ``Queried users`` but
    ``Ran 3 queries``. Set it to the ``(past, present)`` pair that composes.
    """

    past: str
    present: str
    icon: str
    noun: str | None = None
    plural: str | None = None
    args: tuple[str, ...] = ()
    read_only: bool = False
    # Set when the verb already contains its object ("Listed blueprints",
    # "Used GitHub"), so the count-aware label falls back to "N times".
    intransitive: bool = False
    # ``(past, present)`` to use in place of ``past``/``present`` when the
    # label is count-aware. ``None`` reuses the plain verbs.
    count_verb: tuple[str, str] | None = None


# ── Icons ────────────────────────────────────────────────────────────────
# A deliberately small vocabulary: a reader should learn all of it at a glance.
FILE = "▤"
EDIT = "✎"
CODE = "❯"
WEB = "◍"
SEARCH = "⌕"
LINK = "⚯"
CREATE = "✚"
DATA = "⛁"
MAIL = "✉"
CHAT = "✱"
THINK = "◈"
MEMORY = "❋"
IMAGE = "◫"
DOC = "▦"
TOOL = "◆"
STOP = "■"

# ASCII stand-ins for terminals that can't render the above.
ASCII_ICONS = {
    FILE: "[]", EDIT: "*", CODE: ">_", WEB: "()", SEARCH: "?",
    LINK: "--", CREATE: "+", DATA: "=", MAIL: "@", CHAT: "~",
    THINK: "<>", MEMORY: "*", IMAGE: "[]", DOC: "#", TOOL: "+",
    STOP: "x",
}


VERBS: dict[str, VerbSpec] = {
    # ── files ────────────────────────────────────────────────────────────
    "read_file": VerbSpec("Read", "Reading", FILE, "file",
                          args=("path", "file", "filename"), read_only=True),
    "write_file": VerbSpec("Wrote", "Writing", FILE, "file",
                           args=("path", "file", "filename")),
    "edit_file": VerbSpec("Edited", "Editing", EDIT, "edit",
                          args=("path", "file", "filename"), count_verb=("Made", "Making")),
    "notebook_edit": VerbSpec("Edited notebook", "Editing notebook", EDIT,
                              "notebook", args=("path", "notebook_path"), count_verb=("Edited", "Editing")),
    "glob_files": VerbSpec("Searched for", "Searching for", SEARCH, "pattern",
                           args=("pattern", "glob"), read_only=True),
    "grep_files": VerbSpec("Searched for", "Searching for", SEARCH, "search",
                           plural="searches", args=("pattern", "query"),
                           read_only=True, count_verb=("Ran", "Running")),
    "workspace_files": VerbSpec("Listed workspace files", "Listing workspace files",
                                FILE, read_only=True, intransitive=True),
    "download_file": VerbSpec("Downloaded", "Downloading", WEB, "file",
                              args=("url", "path")),

    # ── shell & code ─────────────────────────────────────────────────────
    "bash": VerbSpec("Ran", "Running", CODE, "command",
                     args=("command", "cmd", "script")),
    "run_code": VerbSpec("Ran code", "Running code", CODE,
                         args=("code", "source"), intransitive=True),
    "git_ops": VerbSpec("Ran git", "Running git", CODE, "git command",
                        args=("operation", "op", "action"), count_verb=("Ran", "Running")),

    # ── web ──────────────────────────────────────────────────────────────
    "web_search": VerbSpec("Searched the web for", "Searching the web for", SEARCH,
                           "web search", plural="web searches",
                           args=("query", "q"), read_only=True, count_verb=("Ran", "Running")),
    "open_url": VerbSpec("Fetched", "Fetching", WEB, "page",
                         args=("url",), read_only=True),
    "playwright_browse": VerbSpec("Browsed", "Browsing", WEB, "page",
                                  args=("url", "action")),
    "deep_research": VerbSpec("Researched", "Researching", SEARCH, "topic",
                              args=("query", "topic"), read_only=True),

    # ── data ─────────────────────────────────────────────────────────────
    "sql": VerbSpec("Queried", "Querying", DATA, "query", plural="queries",
                    args=("query", "sql", "statement"), count_verb=("Ran", "Running")),
    "google_sheets": VerbSpec("Used Sheets", "Using Sheets", DATA, "sheet",
                              args=("spreadsheet_id", "action"), intransitive=True),
    "render_dashboard": VerbSpec("Built dashboard", "Building dashboard", DOC,
                                 "dashboard", args=("title",), count_verb=("Built", "Building")),

    # ── documents & artifacts ────────────────────────────────────────────
    "build_document": VerbSpec("Created", "Creating", DOC, "document",
                               args=("title", "kind")),
    "build_artifact": VerbSpec("Created", "Creating", CREATE, "artifact",
                               args=("name", "title")),
    "pdf": VerbSpec("Read PDF", "Reading PDF", DOC, "PDF",
                    args=("path", "url"), read_only=True, count_verb=("Read", "Reading")),
    "vision": VerbSpec("Looked at", "Looking at", IMAGE, "image",
                       args=("path", "url", "image"), read_only=True),

    # ── reasoning helpers ────────────────────────────────────────────────
    "plan_task": VerbSpec("Planned", "Planning", THINK, "plan",
                          args=("goal", "task"), read_only=True, count_verb=("Made", "Making")),
    "decompose_problem": VerbSpec("Decomposed", "Decomposing", THINK, "problem",
                                  args=("problem", "prompt"), read_only=True),
    "synthesize_evidence": VerbSpec("Synthesized evidence", "Synthesizing evidence",
                                    THINK, read_only=True, intransitive=True),
    "decision_matrix": VerbSpec("Weighed options", "Weighing options", THINK,
                                "decision", read_only=True, intransitive=True),
    "verify_output": VerbSpec("Verified", "Verifying", THINK, "check",
                              args=("claim", "output"), read_only=True),
    "build_prompt": VerbSpec("Built a prompt", "Building a prompt", THINK,
                             read_only=True, intransitive=True),
    "todo": VerbSpec("Updated the todo list", "Updating the todo list", THINK,
                     intransitive=True),
    "tool_search": VerbSpec("Looked for a tool", "Looking for a tool", SEARCH,
                            read_only=True, intransitive=True),
    "memory": VerbSpec("Recalled", "Recalling", MEMORY, "memory", plural="memories",
                       args=("query", "content")),

    # ── humans ───────────────────────────────────────────────────────────
    "ask_user": VerbSpec("Asked you", "Asking you", CHAT, "question",
                         args=("question", "prompt"), read_only=True),
    "ask_user_async": VerbSpec("Asked you", "Asking you", CHAT, "question",
                               args=("question", "prompt"), read_only=True),
    "give_up": VerbSpec("Stopped", "Stopping", STOP, args=("reason",),
                        read_only=True, intransitive=True),
    "human_review": VerbSpec("Requested review", "Requesting review", CHAT,
                             "review", args=("summary", "title"), read_only=True, count_verb=("Requested", "Requesting")),

    # ── connectors ───────────────────────────────────────────────────────
    "github": VerbSpec("Used GitHub", "Using GitHub", LINK, "GitHub call",
                       args=("action", "operation"), intransitive=True),
    "gitlab": VerbSpec("Used GitLab", "Using GitLab", LINK, "GitLab call",
                       args=("action", "operation"), intransitive=True),
    "jira": VerbSpec("Used Jira", "Using Jira", LINK, "Jira call",
                     args=("action", "operation"), intransitive=True),
    "linear": VerbSpec("Used Linear", "Using Linear", LINK, "Linear call",
                       args=("action", "operation"), intransitive=True),
    "slack": VerbSpec("Used Slack", "Using Slack", CHAT, "Slack call",
                      args=("action", "channel"), intransitive=True),
    "notion": VerbSpec("Used Notion", "Using Notion", DOC, "Notion call",
                       args=("action", "page_id"), intransitive=True),
    "confluence": VerbSpec("Used Confluence", "Using Confluence", DOC,
                           "Confluence call", args=("action", "page_id"), intransitive=True),
    "gmail_search": VerbSpec("Searched Gmail for", "Searching Gmail for", MAIL,
                             "mail search", plural="mail searches",
                             args=("query", "q"), read_only=True, count_verb=("Ran", "Running")),
    "google_calendar": VerbSpec("Used Calendar", "Using Calendar", DOC,
                                "calendar call", args=("action",), intransitive=True),
    "google_drive": VerbSpec("Used Drive", "Using Drive", FILE, "Drive call",
                             args=("action", "file_id"), intransitive=True),
    "salesforce": VerbSpec("Used Salesforce", "Using Salesforce", DATA,
                           "Salesforce call", args=("action", "object"), intransitive=True),
    "stripe": VerbSpec("Used Stripe", "Using Stripe", DATA, "Stripe call",
                       args=("action",), intransitive=True),
    "zendesk": VerbSpec("Used Zendesk", "Using Zendesk", CHAT, "Zendesk call",
                        args=("action",), intransitive=True),
    "figma": VerbSpec("Used Figma", "Using Figma", IMAGE, "Figma call",
                      args=("action", "file_key"), intransitive=True),
    "linkedin_search": VerbSpec("Searched LinkedIn for", "Searching LinkedIn for",
                                SEARCH, "search", plural="searches", args=("query",),
                                read_only=True, count_verb=("Ran", "Running")),
    "custom_api": VerbSpec("Called", "Calling", LINK, "API call",
                           args=("url", "endpoint"), count_verb=("Made", "Making")),
}


# ── Target extraction ────────────────────────────────────────────────────
# A few tools have a more interesting target than "the first argument".

def _first_code_line(args: dict[str, Any]) -> str | None:
    """First non-blank line of a code/command argument — the readable part."""
    for key in ("code", "command", "cmd", "source", "script", "query", "sql"):
        raw = args.get(key)
        if not isinstance(raw, str):
            continue
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped:
                return _clip(stripped)
    return None


def _url_host(args: dict[str, Any]) -> str | None:
    """A URL's host — ``https://github.com/x/y?z=1`` → ``github.com``."""
    raw = args.get("url")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        host = urlparse(raw).netloc
    except ValueError:
        host = ""
    return host or _clip(raw)


_TARGET_EXTRACTORS: dict[str, Callable[[dict[str, Any]], str | None]] = {
    "bash": _first_code_line,
    "run_code": _first_code_line,
    "sql": _first_code_line,
    "open_url": _url_host,
    "download_file": _url_host,
    "playwright_browse": _url_host,
    "custom_api": _url_host,
}


def _fallback_target(args: dict[str, Any]) -> str | None:
    """First short scalar argument — the best guess for an unknown tool."""
    for value in args.values():
        if isinstance(value, str) and value.strip():
            return _clip(value)
        if isinstance(value, (int, float, bool)):
            return str(value)
    return None


def _extract_target(name: str, args: dict[str, Any], spec: VerbSpec | None) -> str | None:
    extractor = _TARGET_EXTRACTORS.get(name)
    if extractor is not None:
        found = extractor(args)
        if found:
            return found
    if spec is not None:
        for key in spec.args:
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                return _clip(value)
            if isinstance(value, (int, float)):
                return str(value)
        # A spec that names no argument (or whose arguments are absent) still
        # falls through to the generic guess rather than showing nothing.
    return _fallback_target(args)


# ── Humanizing fallback for tools we've never seen ───────────────────────

_VOWELS = "aeiou"

# Irregular pasts, restricted to verbs that actually show up at the head of a
# tool name (`do_thing`, `get_user`, `send_message`, `undo_merge`).
_PAST_IRREGULAR = {
    "do": "did", "go": "went", "get": "got", "set": "set", "put": "put",
    "cut": "cut", "run": "ran", "read": "read", "write": "wrote",
    "make": "made", "find": "found", "build": "built", "send": "sent",
    "spend": "spent", "split": "split", "shut": "shut", "hit": "hit",
    "quit": "quit", "let": "let", "cost": "cost", "take": "took",
    "tell": "told", "think": "thought", "teach": "taught", "buy": "bought",
    "bring": "brought", "catch": "caught", "choose": "chose", "come": "came",
    "draw": "drew", "drive": "drove", "feed": "fed", "feel": "felt",
    "hold": "held", "keep": "kept", "leave": "left", "lose": "lost",
    "meet": "met", "pay": "paid", "say": "said", "see": "saw", "sell": "sold",
    "sit": "sat", "break": "broke", "hide": "hid", "rise": "rose",
    "win": "won", "undo": "undid", "rerun": "reran", "reset": "reset",
    "upset": "upset", "forget": "forgot", "understand": "understood",
    "rewrite": "rewrote", "reread": "reread", "resend": "resent",
}

# Multi-syllable verbs whose final consonant doubles before ``-ing`` — English
# stress rules decide this and we can't infer stress, so they're listed.
_DOUBLING = {
    "commit", "submit", "permit", "transmit", "omit", "emit", "admit",
    "refer", "prefer", "defer", "infer", "occur", "recur", "incur",
    "control", "patrol", "compel", "expel", "propel", "rebel", "forget",
    "begin", "upset", "reset", "unwrap", "format", "regret", "prefer",
}
_NEVER_DOUBLE = {"visit", "limit", "edit", "exit", "inherit", "profit", "target"}


def _doubles_final_consonant(word: str) -> bool:
    """Does ``-ing`` double the last letter? ``run→running``, ``send→sending``."""
    if word in _NEVER_DOUBLE:
        return False
    if word in _DOUBLING:
        return True
    if len(word) < 3 or len(word) > 5:
        return False
    # Consonant–vowel–consonant, final not w/x/y (``show→showing``).
    return (
        word[-1] not in _VOWELS
        and word[-1] not in "wxy"
        and word[-2] in _VOWELS
        and word[-3] not in _VOWELS
    )


def _past_tense(word: str) -> str:
    irregular = _PAST_IRREGULAR.get(word)
    if irregular:
        return irregular.capitalize()
    if word.endswith("e"):
        return (word + "d").capitalize()
    if word.endswith("y") and len(word) > 1 and word[-2] not in _VOWELS:
        return (word[:-1] + "ied").capitalize()
    if _doubles_final_consonant(word):
        return (word + word[-1] + "ed").capitalize()
    return (word + "ed").capitalize()


def _present_tense(word: str) -> str:
    if word.endswith("ie"):  # tie → tying
        return (word[:-2] + "ying").capitalize()
    if word.endswith("e") and not word.endswith(("ee", "oe", "ye")):
        return (word[:-1] + "ing").capitalize()
    if _doubles_final_consonant(word):
        return (word + word[-1] + "ing").capitalize()
    return (word + "ing").capitalize()


def _humanize(name: str) -> VerbSpec:
    """Derive a plausible verb from a tool name we have no spec for.

    ``search_issues`` → *Searched issues* / *Searching issues*. MCP tools
    routinely arrive as ``server__do_thing``; the server prefix is dropped.
    """
    cleaned = re.split(r"__|\.", name)[-1] or name
    words = [w for w in re.split(r"[_\-\s]+", cleaned) if w]
    if not words:
        return VerbSpec("Used a tool", "Using a tool", TOOL, intransitive=True)
    head, rest = words[0].lower(), " ".join(words[1:])
    past = _past_tense(head)
    present = _present_tense(head)
    if rest:
        return VerbSpec(f"{past} {rest}", f"{present} {rest}", TOOL,
                        noun="call", intransitive=True)
    return VerbSpec(past, present, TOOL, noun="call")


# Caller-supplied specs, consulted ahead of the built-in table so a project can
# narrate its own tools (or re-narrate ours) without editing this module.
_OVERRIDES: dict[str, VerbSpec] = {}


def register_verb(name: str, spec: VerbSpec) -> None:
    """Teach the Narrator how one tool narrates itself.

    Overrides the built-in table, so this works both for tools shipit has
    never heard of and for changing how a built-in reads::

        from shipit_agent.narrate import VerbSpec, register_verb

        register_verb(
            "deploy_service",
            VerbSpec("Deployed", "Deploying", "✚", noun="service",
                     args=("service", "name")),
        )

    Without a registration, an unknown tool still narrates — the humanizing
    fallback turns ``deploy_service`` into *Deployed service* — so this is for
    when you want better than the guess, not to avoid a crash.
    """
    if not isinstance(spec, VerbSpec):
        raise TypeError(f"expected VerbSpec, got {type(spec).__name__}")
    _OVERRIDES[name] = spec


def register_verbs(specs: dict[str, VerbSpec]) -> None:
    """Register several at once — see :func:`register_verb`."""
    for name, spec in (specs or {}).items():
        register_verb(name, spec)


def unregister_verb(name: str) -> None:
    """Drop a registration, restoring the built-in (or the fallback)."""
    _OVERRIDES.pop(name, None)


def registered_verbs() -> dict[str, VerbSpec]:
    """The currently registered overrides (a copy)."""
    return dict(_OVERRIDES)


def spec_for(name: str) -> VerbSpec:
    """The :class:`VerbSpec` for *name*.

    Resolution order: caller registrations, then the built-in table, then the
    humanizing fallback.
    """
    return _OVERRIDES.get(name) or VERBS.get(name) or _humanize(name)


def icon_for(name: str) -> str:
    """The glyph for a tool, for the left gutter of a transcript row."""
    return spec_for(name).icon


def is_read_only(name: str, tool: Any = None) -> bool:
    """Whether a call is an *observation* rather than an action.

    A tool's own ``read_only`` attribute wins — the same precedence the
    permission engine uses — so a custom tool can declare itself.
    """
    declared = getattr(tool, "read_only", None)
    if isinstance(declared, bool):
        return declared
    # Registrations first, then the built-in table — same order as spec_for.
    # A tool in neither falls through to the permission heuristics rather than
    # to the humanized fallback, whose read_only default is a guess.
    known = _OVERRIDES.get(name) or VERBS.get(name)
    if known is not None:
        return known.read_only
    from shipit_agent.permissions import PermissionEngine

    return PermissionEngine().is_read_only(name, tool)


@dataclass(frozen=True, slots=True)
class ToolSummary:
    """One call, narrated. ``target`` is ``None`` for an intransitive verb."""

    name: str
    past: str
    present: str
    target: str | None
    icon: str
    read_only: bool

    def past_label(self) -> str:
        """``Read app.py`` — what the transcript shows once the call lands."""
        return f"{self.past} {self.target}" if self.target else self.past

    def present_label(self) -> str:
        """``Reading app.py`` — what it shows while the call is in flight."""
        return f"{self.present} {self.target}" if self.target else self.present


def summarize(name: str, arguments: dict[str, Any] | None = None) -> ToolSummary:
    """Narrate a single tool call.

    Never raises and never returns an empty label: an unknown tool with
    unreadable arguments still yields something a human can read.
    """
    args = dict(arguments or {})
    spec = spec_for(name)
    target = _extract_target(name, args, spec)
    return ToolSummary(
        name=name,
        past=spec.past,
        present=spec.present,
        target=target,
        icon=spec.icon,
        read_only=is_read_only(name),
    )


def _count_phrase(spec: VerbSpec, count: int) -> str:
    if spec.noun:
        return pluralize(count, spec.noun, spec.plural)
    return pluralize(count, "time")


def describe_count(name: str, count: int) -> str:
    """Count-aware past label — ``Wrote 5 files``, ``Ran code 3 times``.

    A single call reads as the plain verb, so ``Made 1 edit`` never appears.
    """
    spec = spec_for(name)
    if count <= 1:
        return spec.past
    if spec.intransitive:
        return f"{spec.past} {pluralize(count, 'time')}"
    verb = spec.count_verb[0] if spec.count_verb else spec.past
    return f"{verb} {_count_phrase(spec, count)}"


def describe_count_present(name: str, count: int) -> str:
    """Count-aware present label — ``Writing 5 files``."""
    spec = spec_for(name)
    if count <= 1:
        return spec.present
    if spec.intransitive:
        return f"{spec.present} {pluralize(count, 'time')}"
    verb = spec.count_verb[1] if spec.count_verb else spec.present
    return f"{verb} {_count_phrase(spec, count)}"
