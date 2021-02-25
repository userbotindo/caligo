import asyncio
import functools
from typing import Any, Callable, TypeVar

from pyrogram import Client

Result = TypeVar("Result")


async def run_sync(
    client: Client,
    func: Callable[..., Result],
    *args: Any,
    **kwargs: Any
) -> Result:
    """Runs the given sync function (optionally with arguments) on a separate thread."""

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(client.executor, functools.partial(func, *args, **kwargs))
