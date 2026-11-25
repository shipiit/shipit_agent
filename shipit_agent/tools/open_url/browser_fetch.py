"""open_url's browser path: render the page in Chromium, checking every request it makes."""

from __future__ import annotations

from typing import Any

from .html_text import _strip_html
from .safe_fetch import checked_address
from .url_safety import URLNotAllowedError


def _guard_route(route: Any) -> None:
    """A browser request goes ahead only to a public http(s) address; data and blob URLs stay local."""
    url = str(route.request.url)
    if url.startswith(("data:", "blob:")):
        route.continue_()
        return
    try:
        checked_address(url)
    except URLNotAllowedError:
        route.abort("blockedbyclient")
        return
    route.continue_()


class BrowserFetchMixin:
    """``_fetch_via_playwright`` for :class:`OpenURLTool`."""

    allow_private_hosts: bool
    headless: bool
    timeout: float
    user_agent: str
    wait_until: str

    def _fetch_via_playwright(self, url: str) -> tuple[str, str, dict]:
        """Returns (text, page_title, metadata). Raises on failure."""
        from shipit_agent.tools._playwright import run_playwright_sync

        def _do_fetch() -> tuple[str, str, dict]:
            from playwright.sync_api import (
                sync_playwright,
            )  # local import — optional dep

            timeout_ms = int(self.timeout * 1000)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                try:
                    context = browser.new_context(
                        user_agent=self.user_agent,
                        viewport={"width": 1280, "height": 800},
                        locale="en-US",
                    )
                    if not self.allow_private_hosts:
                        # Every request the page makes, its own scripts' and
                        # redirects included, is checked: a page must not be
                        # able to read an internal address into its text.
                        context.route("**/*", _guard_route)
                    page = context.new_page()
                    response = page.goto(
                        url, wait_until=self.wait_until, timeout=timeout_ms
                    )
                    status = response.status if response is not None else None
                    if status is not None and status >= 400:
                        raise RuntimeError(f"HTTP {status} from {url}")

                    # A SPA often has only a loading shell at DOMContentLoaded.
                    # Give its network/render pass a bounded chance to settle
                    # before reading the body; never make network-idle a hard
                    # requirement because analytics can keep connections open.
                    try:
                        page.wait_for_load_state(
                            "networkidle", timeout=min(timeout_ms, 10_000)
                        )
                    except Exception:
                        pass

                    # Prefer visible body text; fall back to full rendered HTML.
                    try:
                        text = page.evaluate(
                            "() => document.body && document.body.innerText || ''"
                        )
                    except Exception:
                        text = ""
                    if not text:
                        text = _strip_html(page.content())

                    title = ""
                    try:
                        title = page.title() or ""
                    except Exception:
                        pass

                    if not self.allow_private_hosts:
                        checked_address(page.url)  # where the redirects ended
                    metadata = {
                        "fetch_method": "playwright",
                        "status_code": status,
                        "final_url": page.url,
                        "title": title,
                    }
                    return text, title, metadata
                finally:
                    browser.close()

        return run_playwright_sync(_do_fetch)
