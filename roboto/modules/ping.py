import pyrogram

from datetime import datetime
from typing import ClassVar, Union, List

from ..launch import roboto
from ..module import Module


class Ping(Module):

    name: ClassVar[str] = "Ping"
    command: Union[str, List[str]]
    desc: str
    usage: str

    @roboto.register(
        cmd="ping",
        prefix=".",
        desc="test",
        usage="test"
    )
    async def cmd_ping(self, message: pyrogram.types.Message) -> None:
        start = datetime.now()
        end = datetime.now()
        ms = (end - start).microseconds / 1000
        return await message.edit_text(f"**PONG!**\n{ms} ms")
