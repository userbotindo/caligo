import pyrogram

from pyrogram.filters import command as cmd, edited, me
from datetime import datetime
from RobOto import roboto, command


class Ping:

    @roboto.command(
        cmd("ping", ".", case_sensitive=True) &
        ~edited &
        me
    )
    @command.desc("Check Userbot respond time")
    @command.usage(".ping into any chats")
    async def cmd_ping(client: pyrogram.Client, message: pyrogram.types.Message) -> None:
        start = datetime.now()
        end = datetime.now()
        ms = (end - start).microseconds / 1000
        return await message.edit_text(f"**PONG!**\n{ms} ms")
