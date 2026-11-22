"""Ejecución de tareas largas en eventos background con progreso en vivo."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

Notify = Callable[[str], None]


async def run_with_progress(
    state: Any,
    log_attr: str,
    job: Callable[[Notify], Any] | Callable[[Notify], Awaitable[Any]],
    is_async: bool = False,
    keep: int = 8,
) -> Any:
    """Ejecuta ``job(notify)`` (en un hilo si es síncrono) y refleja los mensajes en ``state``."""
    messages: list[str] = []
    notify: Notify = messages.append
    coro = job(notify) if is_async else asyncio.to_thread(job, notify)
    task = asyncio.ensure_future(coro)
    shown = 0
    while not task.done():
        await asyncio.sleep(0.4)
        if len(messages) != shown:
            shown = len(messages)
            async with state:
                setattr(state, log_attr, messages[-keep:])
    async with state:
        setattr(state, log_attr, messages[-keep:])
    return await task
