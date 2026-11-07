"""Verbs for tools never seen before: `search_issues` becomes "Searched issues"."""

from __future__ import annotations

import re

from .spec import TOOL, VerbSpec

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


#: Leading words that really are verbs, and so may be conjugated.
#:
#: The fallback used to conjugate whatever came first in the name, which is
#: right for ``get_echo`` and wrong for every tool named
#: ``<namespace>_<thing>`` — the shape almost all MCP servers use. It
#: produced "Rling search" from ``rl_search`` and "Slacking post message"
#: from ``slack_post_message``: confident, grammatical-looking nonsense in
#: the one line a user reads to know what the agent is doing.
#:
#: An allowlist rather than a heuristic, because there is no reliable way to
#: tell a verb from a namespace by shape — "post", "search" and "list" are
#: all three parts of speech — and guessing wrong is what this replaced.
_LEADING_VERBS = frozenset({
    "add", "analyze", "analyse", "append", "apply", "archive", "ask",
    "assign", "attach", "build", "call", "cancel", "check", "clear",
    "clone", "close", "collect", "compare", "compile", "compute",
    "connect", "convert", "copy", "count", "crawl", "create", "delete",
    "deploy", "describe", "detect", "disable", "do", "download", "edit",
    "enable", "execute", "explain", "export", "extract", "fetch", "filter",
    "find", "finish", "format", "generate", "get", "grep", "import",
    "index", "insert", "inspect", "install", "invite", "invoke", "join",
    "list", "load", "lock", "lookup", "make", "merge", "move", "open",
    "parse", "patch", "pause", "ping", "poll", "post", "predict",
    "prepare", "preview", "publish", "pull", "push", "query", "read",
    "refresh", "register", "reject", "release", "remove", "rename",
    "render", "reply", "report", "request", "reset", "resolve", "restart",
    "restore", "resume", "retrieve", "review", "revoke", "rollback", "run",
    "save", "scan", "schedule", "search", "select", "send", "set", "share",
    "show", "sign", "sort", "split", "start", "stop", "store", "submit",
    "subscribe", "summarize", "summarise", "sync", "tag", "test",
    "transcribe", "translate", "trigger", "unlock", "update", "upload",
    "upsert", "validate", "verify", "view", "wait", "watch", "write",
})


def _humanize(name: str) -> VerbSpec:
    """Derive a plausible verb from a tool name we have no spec for.

    ``search_issues`` → *Searched issues* / *Searching issues*. MCP tools
    routinely arrive as ``server__do_thing``; the server prefix is dropped.

    When the leading word is not a verb — ``rl_search``, ``slack_post_message``
    — nothing is conjugated. The call is narrated as "Running rl search",
    which is honest about not knowing the tool instead of inventing a word
    for it.
    """
    cleaned = re.split(r"__|\.", name)[-1] or name
    words = [w for w in re.split(r"[_\-\s]+", cleaned) if w]
    if not words:
        return VerbSpec("Used a tool", "Using a tool", TOOL, intransitive=True)
    head, rest = words[0].lower(), " ".join(words[1:])
    if head not in _LEADING_VERBS:
        label = " ".join(words)
        return VerbSpec(f"Ran {label}", f"Running {label}", TOOL,
                        noun="call", intransitive=True)
    past = _past_tense(head)
    present = _present_tense(head)
    if rest:
        return VerbSpec(f"{past} {rest}", f"{present} {rest}", TOOL,
                        noun="call", intransitive=True)
    return VerbSpec(past, present, TOOL, noun="call")


# Caller-supplied specs, consulted ahead of the built-in table so a project can
# narrate its own tools (or re-narrate ours) without editing this module.
