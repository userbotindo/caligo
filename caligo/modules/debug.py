from datetime import datetime
from typing import ClassVar

import aiohttp

from .. import command, module, util


class DebugModule(module.Module):
    name: ClassVar[str] = "Debug"

    @command.desc("Pong")
    async def cmd_ping(self, ctx: command.Context):
        start = datetime.now()
        await ctx.respond("Calculating response time...")
        end = datetime.now()
        latency = (end - start).microseconds / 1000

        return f"Request response time: **{latency} ms**"

    @command.desc("Paste message text to Dogbin")
    @command.alias("deldog", "dogbin")
    @command.usage(
        "[text to paste?, or upload/reply to message or file]", optional=True
    )
    async def cmd_dog(self, ctx: command.Context) -> str:
        input_text = ctx.input

        status, text = await util.tg.get_text_input(ctx, input_text)
        if not status:
            if isinstance(text, str):
                return text

            return "__Unknown error.__"

        await ctx.respond("Uploading text to [Dogbin](https://del.dog/)...")

        async with self.bot.http.post("https://del.dog/documents", data=text) as resp:
            try:
                resp_data = await resp.json()
            except aiohttp.ContentTypeError:
                return "__Dogbin is currently experiencing issues. Try again later.__"

            return f'https://del.dog/{resp_data["key"]}'
