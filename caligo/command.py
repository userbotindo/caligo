from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional, Sequence, Union

import pyrogram

if TYPE_CHECKING:
    from .core import Bot

CommandFunc = Union[
    Callable[..., Coroutine[Any, Any, None]],
    Callable[..., Coroutine[Any, Any, Optional[str]]],
]
Decorator = Callable[[CommandFunc], CommandFunc]


def desc(_desc: str) -> Decorator:
    """Sets description on a command function."""

    def desc_decorator(func: CommandFunc) -> CommandFunc:
        setattr(func, "_cmd_description", _desc)
        return func

    return desc_decorator


def usage(_usage: str, optional: bool = False, reply: bool = False) -> Decorator:
    """Sets argument usage help on a command function."""

    def usage_decorator(func: CommandFunc) -> CommandFunc:
        setattr(func, "_cmd_usage", _usage)
        setattr(func, "_cmd_usage_optional", optional)
        setattr(func, "_cmd_usage_reply", reply)
        return func

    return usage_decorator


def alias(*aliases: str) -> Decorator:
    """Sets aliases on a command function."""

    def alias_decorator(func: CommandFunc) -> CommandFunc:
        setattr(func, "_cmd_aliases", aliases)
        return func

    return alias_decorator


class Command:
    name: str
    desc: str
    usage: str
    usage_optional: bool
    usage_reply: bool
    aliases: Sequence[str]
    module: Any
    func: CommandFunc

    def __init__(self, name: str, mod: Any, func: CommandFunc) -> None:
        self.name = name
        self.desc = getattr(func, "_cmd_description", None)
        self.usage = getattr(func, "_cmd_usage", None)
        self.usage_optional = getattr(func, "_cmd_usage_optional", False)
        self.usage_reply = getattr(func, "_cmd_usage_reply", False)
        self.aliases = getattr(func, "_cmd_aliases", [])
        self.module = mod
        self.func = func


class Context:
    bot: "Bot"
    msg: pyrogram.types.Message
    cmd_length: int

    def __init__(
        self,
        bot: "Bot",
        msg: pyrogram.types.Message,
        cmd_len: int
    ) -> None:
        self.bot = bot
        self.msg = msg
        self.cmd_len = cmd_len

        self.response = None
        self.response_mode = None

    async def respond(
        self,
        text: Optional[str] = None,
        *,
        mode: Optional[str] = None,
        redact: Optional[bool] = None,
        msg: Optional[pyrogram.types.Message] = None,
        reuse_response: bool = False,
        **kwargs: Any,
    ) -> pyrogram.types.Message:

        self.response = await self.bot.respond(
            msg or self.msg,
            text,
            mode=mode,
            redact=redact,
            response=self.response
            if reuse_response and mode == self.response_mode
            else None,
            **kwargs,
        )
        self.response_mode = mode
        return self.response
