import pyrogram

from datetime import datetime
from RobOto import roboto


@roboto.on_message(
    pyrogram.filters.command("ping", ".", case_sensitive=True) &
    pyrogram.filters.me
)
async def ping(roboto, message: pyrogram.types.Message):
    start = datetime.now()
    end = datetime.now()
    ms = (end - start).microseconds / 1000
    return await message.edit_text(f"**PONG!**\n{ms} ms")
