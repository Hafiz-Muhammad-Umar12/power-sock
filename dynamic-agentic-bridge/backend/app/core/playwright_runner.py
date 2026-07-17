"""
Playwright subprocess runner — isolates browser automation from the main
async event loop.

On Windows, Playwright requires ProactorEventLoop to launch Chromium as a
subprocess. FastAPI/asyncpg typically use SelectorEventLoop, which doesn't
support subprocesses on Windows. This module runs each Playwright call in a
FRESH dedicated daemon thread with its own ProactorEventLoop, guaranteeing
no lifecycle or concurrency edge cases.

Safe to use unconditionally on all platforms.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import sys
import threading
from typing import Awaitable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _run_coro_in_new_thread(coro: Awaitable[T]) -> T:
    """
    Run an async coroutine in a brand-new daemon thread with a fresh
    ProactorEventLoop.  BLOCKS the calling thread until complete.

    Called via ``loop.run_in_executor()`` so it never blocks the caller's
    event loop — only the executor thread is blocked.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def run_playwright_coro(coro: Awaitable[T]) -> T:
    """
    Run an async Playwright coroutine in an isolated thread with its own
    event loop, returning the result to the caller.

    Every call creates a **fresh** daemon thread and a **fresh** event loop.
    No thread pool, no shared state, no lifecycle coupling between calls.
    This eliminates:
    - Stale loops after uvicorn --reload hot-reload
    - Concurrency races when observe and execute overlap
    - Closed-loop reuse on sequential calls

    Usage::

        result = await run_playwright_coro(_do_observation(...))
    """
    if sys.platform == "win32":
        # On Windows, explicitly create a ProactorEventLoop in the worker
        # thread.  asyncio.new_event_loop() already picks ProactorEventLoop
        # on 3.8+, but being explicit makes intent clear and guards against
        # any future default change.
        #
        # We force this by patching the event-loop policy inside the worker
        # thread only — never touch the main thread's policy.

        def _target(future: concurrent.futures.Future) -> None:
            old_policy = asyncio.get_event_loop_policy()
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())  # type: ignore[attr-defined]
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(coro)
                    future.set_result(result)
                finally:
                    loop.close()
            except BaseException as exc:
                if not future.done():
                    future.set_exception(exc)
            finally:
                asyncio.set_event_loop_policy(old_policy)

    else:
        def _target(future: concurrent.futures.Future) -> None:
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(coro)
                future.set_result(result)
            finally:
                loop.close()

    caller_loop = asyncio.get_running_loop()
    future: concurrent.futures.Future[T] = concurrent.futures.Future()

    thread = threading.Thread(
        target=_target,
        args=(future,),
        daemon=True,
        name=f"pw-{threading.get_ident()}-{id(coro)}",
    )
    thread.start()

    # future.result() blocks — run it in the default executor so we
    # don't stall the caller's event loop.
    return await caller_loop.run_in_executor(None, future.result)
