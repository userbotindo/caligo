import pyrogram

from pyrogram.filters import me, channel, edited, command
from typing import Callable, Union, List, Optional


def desc(_desc: str) -> callable:

    def desc_decorator(func: Callable) -> callable:
        setattr(func, "_cmd_description", _desc)
        return func

    return desc_decorator


def usage(_usage: str) -> callable:

    def usage_decorator(func: Callable) -> callable:
        setattr(func, "_cmd_usage", _usage)
        return func

    return usage_decorator


class Command:

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
            _filters = command(commands=cmd, prefixes=prefix, case_sensitive=True) & me

            if disable_edited is True:
                _filters &= ~edited
            if disable_channel is True:
                _filters &= ~channel

            self.add_handler(pyrogram.handlers.MessageHandler(func, _filters), group)
            setattr(func, "_cmd_description", desc)
            setattr(func, "_cmd_usage", usage)

            return func

        return decorator
