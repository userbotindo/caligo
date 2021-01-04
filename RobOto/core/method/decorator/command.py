import pyrogram

from pyrogram.filters import Filter
from typing import Callable

from RobOto.core.extention import RawClient


class Command(RawClient):
    def command(
        self=None,
        filters=None,
        group: int = 0,
    ) -> callable:

        def decorator(func: Callable) -> Callable:
            if isinstance(self, pyrogram.Client):
                self.add_handler(
                    pyrogram.handlers.MessageHandler(func, filters), group)
            elif isinstance(self, Filter) or self is None:
                func.handler = (
                    pyrogram.handlers.MessageHandler(func, self),
                    group if filters is None else filters
                )

            return func

        return decorator


def desc(_desc: str) -> Callable:
    """Sets description on a command function"""

    def decorator(func: Callable) -> Callable:
        setattr(func, "_command_description", _desc)
        return func

    return decorator


def usage(_usage: str) -> Callable:
    """Sets argument usage help on a command function."""

    def decorator(func: Callable) -> Callable:
        setattr(func, "_command_usage", _usage)
        return func

    return decorator
