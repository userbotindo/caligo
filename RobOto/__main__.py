import pyrogram

from datetime import datetime
from RobOto import roboto
from RobOto.core.logging import setup_log


@roboto.on_message(
    pyrogram.filters.regex(pattern=r"^.ping$") & pyrogram.filters.me
)
async def ping(roboto, message: pyrogram.types.Message):
    start = datetime.now()
    end = datetime.now()
    ms = (end - start).microseconds / 1000
    await message.edit_text(f"**PONG!**\n{ms} ms")


if __name__ == "__main__":
    setup_log()
    roboto.go()
