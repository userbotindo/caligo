import os
import signal
import pyrogram

from RobOto import roboto


@roboto.on_message(
    pyrogram.filters.command("shutdown", ".", case_sensitive=True) &
    ~pyrogram.filters.edited &
    pyrogram.filters.me
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
