import pyrogram

from pyrogram.filters import Filter
from typing import Callable

from RobOto.core.extention import RawClient


class OnCommand(RawClient):
    def on_command(
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
