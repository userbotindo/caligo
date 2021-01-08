import os
import signal
import pyrogram

from typing import ClassVar

from ..launch import roboto
from ..module import Module


class Shutdown(Module):

    name: ClassVar[str] = "Shutdown"

    @roboto.register(
        cmd="shutdown",
        prefix=".",
        desc="test",
        usage="test"
    )
    async def cmd_shutdown(self, message: pyrogram.types.Message) -> None:
        await message.edit("`Shutdown`")
        d = "."
        for i in range(3):
            await message.edit(f"`Shutdown{d}`")
            await pyrogram.asyncio.sleep(1)
            d += "."
        await message.delete()
        return os.kill(os.getpid(), signal.SIGTERM)
