"""
Playwright subprocess runner — isolates browser automation from the main
async event loop.

On Windows, Playwright requires ProactorEventLoop to launch Chromium as a
subprocess. FastAPI/asyncpg typically use SelectorEventLoop, which doesn't
support subprocesses on Windows. This module runs all Playwright work in a
dedicated daemon thread with its own event loop, solving the conflict.

Safe to use unconditionally on all platforms.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from typing import Any, Awaitable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Single-thread pool — Playwright calls are sequential within one
# observation/execution, so one thread is sufficient.
_executor: concurrent.futures.ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _get_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="playwright",
                )
    return _executor


def _thread_target(coro, future: concurrent.futures.Future) -> None:
    """Run a coroutine in a fresh event loop on this thread, resolving *future*."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(coro)
        future.set_result(result)
    except BaseException as exc:
        future.set_exception(exc)
    finally:
        loop.close()


async def run_playwright_coro(coro: Awaitable[T]) -> T:
    """
    Run an async Playwright coroutine in an isolated thread with its own
    event loop, returning the result to the caller.

    Usage::

        result = await run_playwright_coro(_do_observation(...))

    The inner coroutine may freely use ``await`` — it runs in a real
    event loop, just not the one driving FastAPI / asyncpg.
    """
    loop = asyncio.get_running_loop()
    future: concurrent.futures.Future[T] = concurrent.futures.Future()

    thread = threading.Thread(
        target=_thread_target,
        args=(coro, future),
        daemon=True,
        name="playwright-worker",
    )
    thread.start()

    # Await the future without blocking the caller's event loop
    return await loop.run_in_executor(None, future.result)
