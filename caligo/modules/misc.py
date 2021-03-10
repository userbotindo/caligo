import urllib.parse
from typing import ClassVar

from .. import command, module


class Misc(module.Module):
    name: ClassVar[str] = "Misc"

    @command.desc("Generate a LMGTFY link (Let Me Google That For You)")
    @command.usage("[search query]")
    async def cmd_lmgtfy(self, ctx: command.Context) -> str:
        query = ctx.input
        params = urllib.parse.urlencode({"q": query})

        return f"https://lmgtfy.com/?{params}"
