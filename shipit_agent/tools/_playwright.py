from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

T = TypeVar("T")


def run_playwright_sync(task: Callable[[], T]) -> T:
    """Run sync Playwright safely inside notebooks and other async environments."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return task()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="shipit-playwright") as executor:
        return executor.submit(task).result()
