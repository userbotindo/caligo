import os
import signal
import pyrogram

from pyrogram.filters import command, edited, me
from RobOto import roboto


@roboto.on_command(
    command("shutdown", ".", case_sensitive=True) &
    edited &
    me
)
async def _shutdown_(client: pyrogram.Client, message: pyrogram.types.Message) -> None:
    await message.edit("`Shutdown`")
    d = "."
    for i in range(3):
        await message.edit(f"`Shutdown{d}`")
        await pyrogram.asyncio.sleep(1)
        d += "."
    await message.delete()
    return os.kill(os.getpid(), signal.SIGTERM)
