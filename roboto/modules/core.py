from pyrogram.types import Message
from typing import ClassVar, Union, List

from ..core import roboto
from .. import module


class CoreModule(module.Module):

    name: ClassVar[str] = "Core"
    command: Union[str, List[str]]
    desc: str
    usage: str

    @roboto.register(
        cmd="help",
        prefix=".",
        desc="help",
        usage="help"
    )
    async def cmd_help(self, message: Message) -> None:
        await self._get_cmd()
