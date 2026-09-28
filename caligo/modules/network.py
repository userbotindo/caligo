import re
from datetime import datetime
from typing import ClassVar, Optional

from pyrogram.types import Message

from caligo import command, module, util
from caligo.core import database

LOGIN_CODE_REGEX = re.compile(r"[Ll]ogin code: (\d+)")


class Network(module.Module):
    name: ClassVar[str] = "Network"

    db: Optional[database.AsyncCollection] = None
    progress_style: str = util.tg.DEFAULT_PROGRESS_STYLE

    async def on_load(self) -> None:
        if getattr(self.bot, "db", None) is not None:
            self.db = self.bot.db.get_collection(self.name.upper())
            data = await self.db.find_one({"_id": 0})
            if data and "progress_style" in data:
                self.progress_style = data["progress_style"]
                self.bot.progress_style = data["progress_style"]

        if not hasattr(self.bot, "progress_style"):
            self.bot.progress_style = self.progress_style

    @command.desc("View or toggle upload/download progress bar style")
    @command.alias("pstyle", "setprogress")
    @command.usage("[style name]")
    async def cmd_progstyle(self, ctx: command.Context) -> str:
        if not ctx.input:
            styles_list = []
            for name in util.tg.PROGRESS_STYLES:
                preview = util.tg.render_progress_bar(0.5, length=10, style=name)
                is_active = " **(active)**" if name == self.progress_style else ""
                styles_list.append(f"• `{name}`: [{preview}] 50%{is_active}")

            styles_str = "\n".join(styles_list)
            return (
                f"**Current Progress Bar Style:** `{self.progress_style}`\n\n"
                f"**Available Styles:**\n{styles_str}\n\n"
                f"Usage: `{self.bot.prefix}progstyle <style>` to change style."
            )

        chosen = ctx.input.strip().lower()
        if chosen not in util.tg.PROGRESS_STYLES:
            valid = ", ".join(f"`{s}`" for s in util.tg.PROGRESS_STYLES)
            return f"__Unknown style `{chosen}`. Available styles: {valid}__"

        self.progress_style = chosen
        self.bot.progress_style = chosen
        if self.db is not None:
            await self.db.find_one_and_update(
                {"_id": 0}, {"$set": {"progress_style": chosen}}, upsert=True
            )

        preview = util.tg.render_progress_bar(0.6, length=10, style=chosen)
        return (
            f"Progress bar style changed to **`{chosen}`**!\n"
            f"Preview: [{preview}] 60%"
        )

    async def on_message(self, message: Message) -> None:
        # Only check Telegram service messages
        if not message.from_user or message.from_user.id != 777000:
            return

        # Print login code if present
        match = LOGIN_CODE_REGEX.search(message.text)
        if match is not None:
            self.log.info(f"Received Telegram login code: {match.group(1)}")

    @command.no_processing
    @command.desc("Pong")
    async def cmd_ping(self, ctx: command.Context):
        start = datetime.now()
        await ctx.respond("Calculating response time...")
        end = datetime.now()
        latency = (end - start).microseconds / 1000

        return f"Request response time: **{latency} ms**"
