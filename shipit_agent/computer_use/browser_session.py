"""``BrowserSession`` protocol + a Playwright-backed implementation + a mock for tests.

The protocol is small enough that anything quacking like a browser
(headless Chrome via Playwright, a remote VNC bridge, a stubbed
fixture in tests) plugs in.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Protocol, TypeVar

_T = TypeVar("_T")


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

    **Works inside Jupyter / asyncio.** Playwright's *sync* API refuses to run
    when an asyncio event loop is already running (e.g. in a notebook). To stay
    a simple synchronous API while avoiding that, every Playwright call is run
    on a single dedicated worker thread that has no event loop — so the same
    code works in scripts, notebooks, and async web frameworks alike.
    """

    def __init__(
        self,
        *,
        executor: ThreadPoolExecutor,
        browser: Any,
        page: Any,
        playwright: Any,
        viewport_size: tuple[int, int],
    ) -> None:
        self._executor = executor
        self._browser = browser
        self._page = page
        self._playwright = playwright
        self.viewport_size = viewport_size

    def _run(self, fn: Callable[[], _T]) -> _T:
        """Marshal a Playwright call onto the dedicated browser thread.

        Playwright objects are thread-affine and the sync API can't run inside
        a live asyncio loop, so all access is confined to one loop-free thread.
        """
        return self._executor.submit(fn).result()

    @classmethod
    def launch(
        cls,
        *,
        headless: bool = True,
        viewport_size: tuple[int, int] = (1280, 720),
        start_url: str = "about:blank",
        storage_state: str | None = None,
        slow_mo: float = 0.0,
        settle_ms: int = 500,
    ) -> "PlaywrightBrowserSession":
        """Start a browser session.

        ``storage_state`` points at a Playwright storage-state JSON file
        (cookies + localStorage). If the file exists it is loaded — so
        consent walls accepted in an earlier run stay accepted; the agent
        handles them itself the first time either way. Save the current
        state at any point with :meth:`save_storage_state`.

        ``slow_mo`` (milliseconds) slows every Playwright operation — set
        ~200 with ``headless=False`` to *watch* the agent work. ``settle_ms``
        is the pause after each action before control returns, so the next
        screenshot shows the page AFTER it reacted (dropdowns opened,
        navigation painted) instead of mid-animation.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "PlaywrightBrowserSession requires Playwright. "
                "Install with: pip install playwright && playwright install chromium"
            ) from exc

        executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="shipit-playwright"
        )

        def _start() -> tuple[Any, Any, Any]:
            # Runs on the worker thread (no asyncio loop) → sync API is happy.
            import os

            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=headless, slow_mo=slow_mo)
            context_kwargs: dict[str, Any] = {
                "viewport": {"width": viewport_size[0], "height": viewport_size[1]},
                # 1:1 CSS-pixel screenshots on Retina/HiDPI displays, so the
                # coordinates the model reads off the screenshot are EXACTLY
                # the coordinates mouse.click() expects.
                "device_scale_factor": 1,
            }
            if storage_state and os.path.exists(storage_state):
                context_kwargs["storage_state"] = storage_state
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.goto(start_url)
            return playwright, browser, page

        try:
            playwright, browser, page = executor.submit(_start).result()
        except Exception:
            executor.shutdown(wait=False)
            raise

        session = cls(
            executor=executor,
            browser=browser,
            page=page,
            playwright=playwright,
            viewport_size=viewport_size,
        )
        session._storage_state_path = storage_state
        session._settle_ms = max(0, int(settle_ms))
        return session

    def _settle(self) -> None:
        """Give the page time to react before the next screenshot."""
        ms = getattr(self, "_settle_ms", 0)
        if ms:
            self._run(lambda: self._page.wait_for_timeout(ms))

    def save_storage_state(self, path: str | None = None) -> str:
        """Persist cookies + localStorage (e.g. accepted consent) to disk.

        Reuse the file via ``launch(storage_state=...)`` so future runs skip
        every consent wall the agent already clicked through. Returns the
        path written.
        """
        target = path or getattr(self, "_storage_state_path", None)
        if not target:
            raise ValueError(
                "No path: pass save_storage_state(path=...) or launch with "
                "storage_state=..."
            )
        self._run(lambda: self._page.context.storage_state(path=target))
        return target

    # --- Protocol surface -----------------------------------------------
    def screenshot(self) -> str:
        png = self._run(lambda: self._page.screenshot(type="png"))
        return base64.b64encode(png).decode("ascii")

    def click(self, x: int, y: int) -> None:
        self._run(lambda: self._page.mouse.click(x, y))
        self._settle()

    def type_text(self, text: str) -> None:
        # delay= makes keystrokes visible and lets autocomplete widgets react
        self._run(lambda: self._page.keyboard.type(text, delay=40))
        self._settle()

    def key(self, key: str) -> None:
        self._run(lambda: self._page.keyboard.press(key))
        self._settle()

    def scroll(self, dx: int, dy: int) -> None:
        self._run(lambda: self._page.mouse.wheel(dx, dy))
        self._settle()

    def navigate(self, url: str) -> None:
        self._run(lambda: self._page.goto(url))
        self._settle()

    def close(self) -> None:
        def _close() -> None:
            try:
                self._browser.close()
            finally:
                if self._playwright is not None:
                    self._playwright.stop()

        try:
            self._run(_close)
        finally:
            self._executor.shutdown(wait=True)

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
