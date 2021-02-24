from typing import List
import asyncio

import pyrogram

from .. import command, module


class Echo(module.Module):
    name = "Echo"
    disabled = False

    async def on_message(self, event: pyrogram.types.Message) -> None:
        self.log.info(f"Received message: {event.text}")

    async def on_message_delete(self, event: List[pyrogram.types.Message]) -> None:
        self.log.info(f"Received deleted message: {event}")

    @command.desc("Simple echo/test command")
    @command.alias("echotest", "test")
    @command.usage("[text to echo?, or reply]", optional=True, reply=True)
    async def cmd_echo(self, ctx: command.Context) -> str:
        await ctx.msg.edit("processing")
        await asyncio.sleep(1)

        return "It works!"
