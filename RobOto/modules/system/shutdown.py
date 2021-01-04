import os
import signal
import pyrogram

from pyrogram.filters import command as cmd, edited, me
from RobOto import roboto, command


class Shutdown:

    @roboto.command(
        cmd("shutdown", ".", case_sensitive=True) &
        ~edited &
        me
    )
    @command.desc("Shutdown the current session")
    @command.usage(".shutdown into any chats")
    async def cmd_shutdown(client: pyrogram.Client, message: pyrogram.types.Message) -> None:
        await message.edit("`Shutdown`")
        d = "."
        for i in range(3):
            await message.edit(f"`Shutdown{d}`")
            await pyrogram.asyncio.sleep(1)
            d += "."
        await message.delete()
        return os.kill(os.getpid(), signal.SIGTERM)
