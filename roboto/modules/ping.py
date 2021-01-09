import pyrogram

from datetime import datetime
from typing import ClassVar, Union, List

from ..core import roboto
from .. import module


class Ping(module.Module):

    name: ClassVar[str] = "Ping"
    command: Union[str, List[str]]
    desc: str
    usage: str

    @roboto.register(
        cmd="ping",
        prefix=".",
        desc="Pong",
        usage=""
    )
    async def cmd_ping(self, message: pyrogram.types.Message) -> None:
        if len(self.cmd) > 1:
            if self.cmd[1] == "help":
                return await message.edit(self.cmd_desc)
            else:
                return False
        start = datetime.now()
        end = datetime.now()
        ms = (end - start).microseconds / 1000
        return await message.edit_text(f"**PONG!**\n{ms} ms")
