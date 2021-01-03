import pyrogram

from datetime import datetime
from RobOto import roboto


@roboto.on_message(
    pyrogram.filters.command("ping", ".", case_sensitive=True) &
    ~pyrogram.filters.edited &
    pyrogram.filters.me
)
async def ping(client: pyrogram.Client, message: pyrogram.types.Message) -> None:
    start = datetime.now()
    end = datetime.now()
    ms = (end - start).microseconds / 1000
    return await message.edit_text(f"**PONG!**\n{ms} ms")
