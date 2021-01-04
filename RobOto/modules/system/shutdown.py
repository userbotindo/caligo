import os
import signal
import pyrogram

from pyrogram.filters import command, edited, me
from RobOto import roboto


@roboto.command(
    command("shutdown", ".", case_sensitive=True) &
    ~edited &
    me
)
@roboto.command_desc("Shutdown the current session")
@roboto.command_usage(".shutdown into any chats")
async def _shutdown_(client: pyrogram.Client, message: pyrogram.types.Message) -> None:
    await message.edit("`Shutdown`")
    d = "."
    for i in range(3):
        await message.edit(f"`Shutdown{d}`")
        await pyrogram.asyncio.sleep(1)
        d += "."
    await message.delete()
    return os.kill(os.getpid(), signal.SIGTERM)
