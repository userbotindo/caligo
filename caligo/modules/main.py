from collections import defaultdict
from hashlib import sha256
from typing import ClassVar, MutableMapping

from aiopath import AsyncPath
from bson.binary import Binary
from pyrogram.raw.functions.updates.get_state import GetState

from caligo import command, module, util


class Main(module.Module):
    name: ClassVar[str] = "Main"

    async def on_load(self) -> None:
        self.db = self.bot.db[self.name.capitalize()]

    async def on_stop(self) -> None:
        return

        # skipcq: PYL-W0101
        file = AsyncPath("caligo/caligo.session")
        if not await file.exists():
            return

        data = await self.bot.client.invoke(GetState())
        await self.db.update_one(
            {"_id": sha256(self.bot.config["api_id"].encode()).hexdigest()},
            {
                "$set": {
                    "session": Binary(await file.read_bytes()),
                    "date": data.date,
                    "pts": data.pts,
                    "qts": data.qts,
                    "seq": data.seq,
                }
            },
            upsert=True,
        )

    @command.desc("List the commands")
    @command.usage("[filter: command or module name?]", optional=True)
    async def cmd_help(self, ctx: command.Context):
        filt = ctx.input
        modules: MutableMapping[str, MutableMapping[str, str]] = defaultdict(dict)

        # Handle command filters
        if filt and filt not in self.bot.modules:
            if filt in self.bot.commands:
                cmd = self.bot.commands[filt]

                # Generate aliases section
                aliases = f"`{'`, `'.join(cmd.aliases)}`" if cmd.aliases else "none"

                # Generate parameters section
                if cmd.usage is None:
                    args_desc = "none"
                else:
                    args_desc = cmd.usage

                    if cmd.usage_optional:
                        args_desc += " (optional)"
                    if cmd.usage_reply:
                        args_desc += " (also accepts replies)"

                # Show info card
                return f"""`{cmd.name}`: **{cmd.desc if cmd.desc else '__No description provided.__'}**
Module: {cmd.module.name}
Aliases: {aliases}
Expected parameters: {args_desc}"""

            return "__That filter didn't match any commands or modules.__"

        # Show full help
        for name, cmd in self.bot.commands.items():
            # Check if a filter is being used
            if filt:
                # Ignore commands that aren't part of the filtered module
                if cmd.module.name != filt:
                    continue
            else:
                # Don't count aliases as separate commands
                if name != cmd.name:
                    continue

            desc = cmd.desc if cmd.desc else "__No description provided__"
            aliases = ""
            if cmd.aliases:
                aliases = f' (aliases: {", ".join(cmd.aliases)})'

            mod_name = type(cmd.module).name
            modules[mod_name][cmd.name] = desc + aliases

        response = None
        for mod_name, commands in sorted(modules.items()):
            section = util.text.join_map(commands, heading=mod_name)
            add_len = len(section) + 2
            if response and (len(response) + add_len > util.tg.MESSAGE_CHAR_LIMIT):
                await ctx.respond_multi(response)
                response = None

            if response:
                response += "\n\n" + section
            else:
                response = section

        if response:
            await ctx.respond_multi(response)
