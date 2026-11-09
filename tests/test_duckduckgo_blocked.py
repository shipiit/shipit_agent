"""DuckDuckGo's bot check is reported, not mistaken for "no results".

DuckDuckGo answers automated requests with HTTP 202 and an "anomaly" challenge
page. The provider parsed that as zero results, so agents silently searched
nothing; it now raises and names the providers that work with a key.
"""

from __future__ import annotations

import io

import pytest

from shipit_agent.tools.web_search import providers
from shipit_agent.tools.web_search.providers import DuckDuckGoSearchProvider

RESULT = (
    '<a rel="nofollow" class="result__a" href="https://www.python.org/">Welcome to <b>Python</b>.org</a>'
    '<a class="result__snippet" href="https://www.python.org/">The official home of Python.</a>'
)
CHALLENGE = '<html><body><form id="challenge-form" action="/anomaly.js"><div class="anomaly-modal__title">Unfortunately, bots use DuckDuckGo too.</div></form></body></html>'


class _Response(io.BytesIO):
    def __init__(self, body: str, status: int) -> None:
        super().__init__(body.encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _serve(monkeypatch: pytest.MonkeyPatch, body: str, status: int = 200) -> None:
    monkeypatch.setattr(providers, "urlopen", lambda *_a, **_k: _Response(body, status))


def test_results_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, RESULT)
    assert DuckDuckGoSearchProvider().search("python") == [
        {"title": "Welcome to Python .org", "url": "https://www.python.org/", "snippet": "The official home of Python."}
    ]


def test_a_bot_check_raises_with_what_to_do(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, CHALLENGE, status=202)
    with pytest.raises(RuntimeError, match="(?i)bot check.*brave.*serper.*tavily"):
        DuckDuckGoSearchProvider().search("python")


def test_a_real_empty_page_is_still_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, "<html><body><div class='no-results'>No results.</div></body></html>")
    assert DuckDuckGoSearchProvider().search("zzqqxx") == []
