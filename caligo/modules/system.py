import asyncio
import os
import sys
from html import escape
from typing import Any, ClassVar, Mapping, Optional

from aiopath import AsyncPath
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from caligo import command, module, util
from caligo.core import database


class System(module.Module):
    name: ClassVar[str] = "System"

    db: database.AsyncCollection
    restart_pending: bool

    async def on_load(self):
        self.restart_pending = False

        self.db = self.bot.db.get_collection(self.name.upper())

    async def on_start(self, time_us: int) -> None:  # skipcq: PYL-W0613
        # Update restart status message if applicable
        data: Optional[Mapping[str, Mapping[str, Any]]] = await self.db.find_one(
            {"_id": 0}
        )
        if data is not None:
            restart = data["restart"]
            # Fetch status message info
            rs_time: Optional[int] = restart.get("time")
            rs_chat_id: Optional[int] = restart.get("status_chat_id")
            rs_message_id: Optional[int] = restart.get("status_message_id")
            rs_reason: Optional[str] = restart.get("reason")

            # Delete DB keys first in case message editing fails
            await self.db.delete_one({"_id": 0})

            # Bail out if we're missing necessary values
            if rs_chat_id is None or rs_message_id is None or rs_time is None:
                return

            # Show message
            updated = "updated and " if rs_reason == "update" else ""
            duration = util.time.format_duration_us(util.time.usec() - rs_time)
            self.log.info("Bot %srestarted in %s", updated, duration)

            status_msg: Message = await self.bot.client.get_messages(
                rs_chat_id, rs_message_id
            )  # type: ignore
            try:
                await self.bot.respond(
                    status_msg, f"Bot {updated}restarted in {duration}.", mode="repost"
                )
            except AttributeError:
                await self.bot.client.send_message(
                    rs_chat_id, f"Bot {updated}restarted in {duration}."
                )

    async def on_stopped(self) -> None:
        if self.restart_pending:
            self.log.info("Starting new bot instance...\n")
            # This is safe because original arguments are reused. skipcq: BAN-B606
            os.execv(sys.executable, (sys.executable, "-m", "caligo"))

    @command.desc("Stop this bot")
    async def cmd_stop(self, ctx: command.Context) -> None:
        await ctx.respond("Stopping bot...")
        self.bot.__idle__.cancel()

    @command.desc("Restart this bot")
    @command.alias("re", "rst")
    async def cmd_restart(
        self,
        ctx: command.Context,
        *,
        restart_time: Optional[int] = None,
        reason="manual",
    ) -> None:
        resp_msg = await ctx.respond("Restarting bot...")

        # Save time and status message so we can update it after restarting
        await self.db.update_one(
            {"_id": 0},
            {
                "$set": {
                    "restart.status_chat_id": resp_msg.chat.id,
                    "restart.status_message_id": resp_msg.id,
                    "restart.time": restart_time or util.time.usec(),
                    "restart.reason": reason,
                }
            },
            upsert=True,
        )
        # Initiate the restart
        self.restart_pending = True
        self.log.info("Preparing to restart...")
        self.bot.__idle__.cancel()

    @command.desc("Get information about the host system")
    @command.alias("si")
    async def cmd_sysinfo(self, ctx: command.Context) -> str | None:
        await ctx.respond("Collecting system information...")

        try:
            stdout, _, ret = await util.system.run_command(
                "neofetch", "--stdout", timeout=60
            )
        except asyncio.TimeoutError:
            return "🕑 `neofetch` failed to finish within 1 minute."
        except FileNotFoundError:
            return (
                "❌ [neofetch](https://github.com/dylanaraps/neofetch) "
                "must be installed on the host system."
            )

        err = f"⚠️ Return code: {ret}" if ret != 0 else ""
        sysinfo = "\n".join(stdout.split("\n")[2:]) if ret == 0 else stdout
        await ctx.respond(
            f"""<pre language="bash">{escape(sysinfo)}</pre>{err}""",
            parse_mode=ParseMode.HTML,
        )

    @command.desc("Run a snippet in a shell")
    @command.usage("[shell snippet]")
    @command.alias("sh")
    async def cmd_shell(self, ctx: command.Context) -> str | None:
        snip = ctx.input
        if not snip:
            return "Give me command to run."

        await ctx.respond("Running snippet...")
        before = util.time.usec()

        try:
            stdout, _, ret = await util.system.run_command(
                snip, shell=True, timeout=120  # skipcq: BAN-B604
            )
        except FileNotFoundError as E:
            after = util.time.usec()
            await ctx.respond(
                f"""<b>Input</b>:<pre language="bash">{escape(snip)}</pre>
<b>Output</b>:
⚠️ Error executing command:
<pre language="bash">{escape(util.error.format_exception(E))}</pre>

f"Time: {util.time.format_duration_us(after - before)}""",
                parse_mode=ParseMode.HTML,
            )
            return
        except asyncio.TimeoutError:
            after = util.time.usec()
            await ctx.respond(
                f"""<b>Input</b>:
<pre language="bash">{escape(snip)}</pre>
<b>Output</b>:
🕑 Snippet failed to finish within 2 minutes."""
                f"Time: {util.time.format_duration_us(after - before)}",
                parse_mode=ParseMode.HTML,
            )
            return

        after = util.time.usec()

        el_us = after - before
        el_str = f"\nTime: {util.time.format_duration_us(el_us)}"

        if not stdout:
            stdout = "[no output]"
        elif stdout[-1:] != "\n":
            stdout += "\n"

        stdout = self.bot.redact_message(stdout)
        err = f"⚠️ Return code: {ret}" if ret != 0 else ""
        await ctx.respond(
            f"""<b>Input</b>:
<pre language="bash">{escape(snip)}</pre>
<b>Output</b>:
<pre language="bash">{escape(stdout)}</pre>{err}{el_str}""",
            parse_mode=ParseMode.HTML,
        )

    @command.desc("Update this bot from Git and restart")
    @command.usage("[deploy flag?]", optional=True)
    @command.alias("up", "upd")
    async def cmd_update(self, ctx: command.Context) -> Optional[str]:
        if not util.git.have_git:
            return "__The__ `git` __command is required for self-updating.__"

        # Attempt to get the Git repo
        repo = await util.run_sync(util.git.get_repo)
        if not repo:
            return "__Unable to locate Git repository data.__"

        # Get current branch's tracking remote
        remote = await util.run_sync(util.git.get_current_remote)
        if remote is None:
            return f"__Current branch__ `{repo.active_branch.name}` __is not tracking a remote.__"

        # Save time and old commit for diffing
        update_time = util.time.usec()
        old_commit = await util.run_sync(repo.commit)

        # Pull from remote
        await ctx.respond(f"Pulling changes from `{remote}`...")
        await util.run_sync(remote.pull)

        # Return early if no changes were pulled
        diff = old_commit.diff()
        if not diff:
            return "No updates found."

        # Check for dependency changes
        if any(change.a_path == "poetry.lock" for change in diff):
            # Update dependencies automatically if running in venv
            prefix = util.system.get_venv_path()
            if prefix:
                pip = str(AsyncPath(prefix) / "bin" / "pip")

                await ctx.respond("Updating dependencies...")
                stdout, _, ret = await util.system.run_command(
                    pip, "install", repo.working_tree_dir
                )
                if ret != 0:
                    return f"""⚠️ Error updating dependencies:
```{stdout}```
Fix the issue manually and then restart the bot."""
            else:
                return """Successfully pulled updates.
**Update dependencies manually** to avoid errors, then restart the bot for the update to take effect.
Dependency updates are automatic if you're running the bot in a virtualenv."""

        # Restart after updating
        return await self.cmd_restart(ctx, restart_time=update_time, reason="update")
