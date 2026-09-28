from typing import ClassVar, Optional

from caligo import command, module


class AutoDelete(module.Module):
    name: ClassVar[str] = "AutoDelete"

    async def on_load(self) -> None:
        if not hasattr(self.bot, "delete_after"):
            self.bot.delete_after = 15.0

    @command.desc("Get or set global command output auto-delete duration (in seconds)")
    @command.alias("deleteafter", "autodelete", "deldecay", "da")
    @command.usage("[seconds | 'off' / 'disable']", optional=True)
    async def cmd_autodel(self, ctx: command.Context) -> str:
        raw = ctx.input.strip().lower() if ctx.input else ""

        if not raw:
            current = getattr(self.bot, "delete_after", None)
            if current:
                sec_str = int(current) if current == int(current) else current
                return f"__Auto-delete is set to__ `{sec_str}` __seconds.__"
            return "__Auto-delete is currently disabled.__"

        if raw in ("off", "disable", "disabled", "no", "false", "none", "0"):
            self.bot.delete_after = None
            if getattr(self.bot, "db", None) is not None:
                await self.bot.db["MAIN"].update_one(
                    {"_id": 0},
                    {"$set": {"delete_after": None}},
                    upsert=True,
                )
            return "__Auto-delete has been disabled.__"

        try:
            val = float(raw)
            if val <= 0:
                self.bot.delete_after = None
                if getattr(self.bot, "db", None) is not None:
                    await self.bot.db["MAIN"].update_one(
                        {"_id": 0},
                        {"$set": {"delete_after": None}},
                        upsert=True,
                    )
                return "__Auto-delete has been disabled.__"

            self.bot.delete_after = val
            if getattr(self.bot, "db", None) is not None:
                await self.bot.db["MAIN"].update_one(
                    {"_id": 0},
                    {"$set": {"delete_after": val}},
                    upsert=True,
                )
            sec_str = int(val) if val == int(val) else val
            return f"__Auto-delete duration set to__ `{sec_str}` __seconds.__"
        except ValueError:
            return "__Invalid duration. Pass number of seconds (e.g. `15`) or `off`.__"
