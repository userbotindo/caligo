from typing import Callable

from RobOto.core.extention import RawClient


class CommandExt(RawClient):
    def command_desc(self, _desc: str) -> Callable:
        """Sets description on a command function"""

        def decorator(func: Callable) -> Callable:
            setattr(func, "_command_description", _desc)
            return func

        return decorator

    def command_usage(self, _usage: str) -> Callable:
        """Sets argument usage help on a command function."""

        def decorator(func: Callable) -> Callable:
            setattr(func, "_command_usage", _usage)
            return func

        return decorator
