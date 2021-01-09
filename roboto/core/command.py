import pyrogram

from pyrogram.filters import me, channel, edited
from typing import Callable, Union, List, Optional

from .base import Base
from .custom_filter import CustomCommandFilter


class Command(Base, CustomCommandFilter):

    def register(
        self,
        cmd: Union[str, List[str]],
        prefix: str,
        desc: Optional[str] = str(),
        usage: Optional[str] = str(),
        disable_edited: Optional[bool] = True,
        disable_channel: Optional[bool] = True,
        group: Optional[int] = 0,
    ) -> callable:

        def decorator(func: Callable) -> Callable:
            _filters = self.command(
                commands=cmd,
                prefixes=prefix,
                desc=desc,
                usage=usage
            ) & me

            if disable_edited is True:
                _filters &= ~edited
            if disable_channel is True:
                _filters &= ~channel

            self.add_handler(pyrogram.handlers.MessageHandler(func, _filters), group)
            setattr(func, "_cmd", cmd)
            setattr(func, "_cmd_description", desc)
            setattr(func, "_cmd_usage", usage)

            return func

        return decorator
