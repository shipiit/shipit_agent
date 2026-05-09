"""``BrowserSession`` protocol + a Playwright-backed implementation + a mock for tests.

The protocol is small enough that anything quacking like a browser
(headless Chrome via Playwright, a remote VNC bridge, a stubbed
fixture in tests) plugs in.
"""

from __future__ import annotations

import base64
from typing import Any, Protocol


class BrowserSession(Protocol):
    """Minimum surface a browser must expose for the agent to drive it."""

    def screenshot(self) -> str:
        """Return a base64-encoded PNG/JPEG of the current viewport."""
        ...

    def click(self, x: int, y: int) -> None:
        """Click at the given pixel coordinates."""
        ...

    def type_text(self, text: str) -> None:
        """Type the given text into whatever has focus."""
        ...

    def key(self, key: str) -> None:
        """Press a special key (e.g. ``Enter``, ``Tab``, ``Escape``)."""
        ...

    def scroll(self, dx: int, dy: int) -> None:
        """Scroll by (dx, dy) pixels."""
        ...

    def navigate(self, url: str) -> None:
        """Navigate to a URL."""
        ...

    def close(self) -> None:
        """Tear down the browser."""
        ...


class MockBrowserSession:
    """Deterministic test double — records every call and returns canned screenshots.

    Useful for unit testing the agent loop without spawning a real browser.
    Every method call is appended to ``self.calls`` for assertions.
    """

    def __init__(
        self, *, screenshots: list[str] | None = None, viewport_size: tuple[int, int] = (1280, 720)
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._screenshots = screenshots or [_blank_png_b64()]
        self._screenshot_index = 0
        self.viewport_size = viewport_size
        self.url = ""

    # --- Protocol surface -----------------------------------------------
    def screenshot(self) -> str:
        self.calls.append(("screenshot", {}))
        s = self._screenshots[min(self._screenshot_index, len(self._screenshots) - 1)]
        self._screenshot_index += 1
        return s

    def click(self, x: int, y: int) -> None:
        self.calls.append(("click", {"x": x, "y": y}))

    def type_text(self, text: str) -> None:
        self.calls.append(("type", {"text": text}))

    def key(self, key: str) -> None:
        self.calls.append(("key", {"key": key}))

    def scroll(self, dx: int, dy: int) -> None:
        self.calls.append(("scroll", {"dx": dx, "dy": dy}))

    def navigate(self, url: str) -> None:
        self.url = url
        self.calls.append(("navigate", {"url": url}))

    def close(self) -> None:
        self.calls.append(("close", {}))


class PlaywrightBrowserSession:
    """Real-browser implementation backed by Playwright.

    Requires ``pip install playwright && playwright install chromium``.
    The Playwright import happens inside ``launch()`` so users without
    Playwright can still import this module and use ``MockBrowserSession``.

    Construct via the ``launch()`` classmethod (handles browser + page setup);
    ``close()`` the session when done. Also works as a context manager::

        with PlaywrightBrowserSession.launch(headless=True) as browser:
            agent = ComputerUseAgent(llm=llm, browser=browser, goal="...")
            result = agent.run()
    """

    def __init__(self, *, browser: Any, page: Any, viewport_size: tuple[int, int]) -> None:
        self._browser = browser
        self._page = page
        self.viewport_size = viewport_size

    @classmethod
    def launch(
        cls,
        *,
        headless: bool = True,
        viewport_size: tuple[int, int] = (1280, 720),
        start_url: str = "about:blank",
    ) -> "PlaywrightBrowserSession":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "PlaywrightBrowserSession requires Playwright. "
                "Install with: pip install playwright && playwright install chromium"
            ) from exc

        # Keep the playwright handle so we can stop() it later
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": viewport_size[0], "height": viewport_size[1]},
        )
        page = context.new_page()
        page.goto(start_url)

        session = cls(browser=browser, page=page, viewport_size=viewport_size)
        session._playwright = playwright  # type: ignore[attr-defined]
        return session

    # --- Protocol surface -----------------------------------------------
    def screenshot(self) -> str:
        png = self._page.screenshot(type="png")
        return base64.b64encode(png).decode("ascii")

    def click(self, x: int, y: int) -> None:
        self._page.mouse.click(x, y)

    def type_text(self, text: str) -> None:
        self._page.keyboard.type(text)

    def key(self, key: str) -> None:
        self._page.keyboard.press(key)

    def scroll(self, dx: int, dy: int) -> None:
        self._page.mouse.wheel(dx, dy)

    def navigate(self, url: str) -> None:
        self._page.goto(url)

    def close(self) -> None:
        try:
            self._browser.close()
        finally:
            playwright = getattr(self, "_playwright", None)
            if playwright is not None:
                playwright.stop()

    # --- Context manager sugar ------------------------------------------
    def __enter__(self) -> "PlaywrightBrowserSession":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# 1×1 transparent PNG, base64-encoded. Used as the default mock screenshot.
_BLANK_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjC"
    "B0C8AAAAASUVORK5CYII="
)


def _blank_png_b64() -> str:
    return _BLANK_PNG
