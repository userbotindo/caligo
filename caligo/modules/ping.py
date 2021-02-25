from datetime import datetime
from typing import ClassVar

from .. import command, module


class Ping(module.Module):
    name: ClassVar[str] = "Ping"

    @command.desc("Pong")
    async def cmd_ping(self, ctx: command.Context):
        start = datetime.now()
        await ctx.respond("Calculating response time...")
        end = datetime.now()
        latency = (end - start).microseconds / 1000

        return f"Request response time: **{latency} ms**"
