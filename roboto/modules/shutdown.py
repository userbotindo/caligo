import os
import signal
import pyrogram

from typing import ClassVar

from ..core import roboto
from .. import module


class Shutdown(module.Module):

    name: ClassVar[str] = "Shutdown"

    @roboto.register(
        cmd="shutdown",
        prefix=".",
        desc="Safely shutdown this bot.",
        usage=""
    )
    async def cmd_shutdown(self, message: pyrogram.types.Message) -> None:
        if len(self.cmd) > 1:
            if self.cmd[1] == "help":
                return await message.edit(self.cmd_desc)
            else:
                return False
        await message.edit("`Shutdown`")
        d = "."
        for i in range(3):
            await message.edit(f"`Shutdown{d}`")
            await pyrogram.asyncio.sleep(1)
            d += "."
        await message.delete()
        return os.kill(os.getpid(), signal.SIGTERM)
