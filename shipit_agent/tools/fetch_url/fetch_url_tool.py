"""Fetch a URL and return its text.

Without this the model answers from training data and states the guess as fact,
which is the failure that is hardest for a reader to detect.
"""

from __future__ import annotations

import html as html_module
import re
import urllib.error
import urllib.request
from typing import Any, Callable

from shipit_agent.tools._shared import ToolBase
from shipit_agent.tools.fetch_url.prompt import DESCRIPTION, INSTRUCTIONS

__all__ = ["FetchUrlTool"]

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_BLANKS = re.compile(r"\n{3,}")


def html_to_text(html: str) -> str:
    """Readable text from HTML, with no parser dependency.

    Deliberately crude: scripts and styles removed, tags stripped, entities
    unescaped, blank runs collapsed. A real extractor does better, but this never
    raises and adds nothing to install, and the model reads prose either way.
    """
    text = _SCRIPT.sub(" ", html)
    text = _TAG.sub(" ", text)
    text = html_module.unescape(text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANKS.sub("\n\n", text).strip()


class FetchUrlTool(ToolBase):
    name = "fetch_url"
    description = DESCRIPTION
    prompt_instructions = INSTRUCTIONS

    def __init__(
        self,
        workspace: Any = None,
        *,
        timeout: int = 20,
        allowed_schemes: frozenset[str] = frozenset({"http", "https"}),
        opener: Callable[[str, int], tuple[int, str, str]] | None = None,
    ) -> None:
        super().__init__(workspace)
        self.timeout = timeout
        self.allowed_schemes = allowed_schemes
        self._opener = opener or self._urlopen

    @staticmethod
    def _urlopen(url: str, timeout: int) -> tuple[int, str, str]:
        request = urllib.request.Request(url, headers={"User-Agent": "shipit-agent/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return (
                response.status,
                response.headers.get_content_type(),
                response.read().decode(charset, errors="replace"),
            )

    def schema(self) -> dict[str, Any]:
        return self.build_schema(
            {
                "url": {"type": "string", "description": "The URL to fetch."},
                "raw": {
                    "type": "boolean",
                    "description": "Return the body unprocessed instead of text.",
                },
            },
            ["url"],
        )

    def run(self, context: Any = None, **kwargs: Any) -> Any:
        url = str(kwargs.get("url", "")).strip()
        if not url:
            return self.fail("No url given.")
        scheme = url.split(":", 1)[0].lower()
        if scheme not in self.allowed_schemes:
            # file:// and friends are refused: a fetch tool that reads local
            # paths is a file reader with none of the file reader's contracts.
            return self.fail(
                f"Scheme {scheme!r} is not allowed. Permitted: "
                f"{', '.join(sorted(self.allowed_schemes))}."
            )

        try:
            status, content_type, body = self._opener(url, self.timeout)
        except urllib.error.HTTPError as error:
            return self.fail(f"{url} returned HTTP {error.code}.")
        except Exception as error:  # noqa: BLE001
            return self.fail(f"Could not fetch {url}: {error}")

        text = (
            body
            if kwargs.get("raw")
            else (html_to_text(body) if "html" in (content_type or "") else body)
        )
        return self.ok(
            text,
            hint="Fetch a more specific page.",
            url=url,
            status=status,
            content_type=content_type,
        )
