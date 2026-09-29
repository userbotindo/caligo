import asyncio
import os
import sys
from html import escape
from typing import Any, ClassVar, Mapping, Optional

import speedtest
from anyio import Path as AsyncPath
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
        if not hasattr(self.bot, "delete_after"):
            self.bot.delete_after = 15.0
        if not hasattr(self.bot, "processing_status"):
            self.bot.processing_status = None

        if getattr(self.bot, "db", None) is not None:
            self.db = self.bot.db.get_collection(self.name.upper())
        else:
            self.db = None

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
            rs_thread_id: int = restart.get("status_thread_id")  # type: ignore
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
                    rs_chat_id,
                    f"Bot {updated}restarted in {duration}.",
                    message_thread_id=rs_thread_id,
                )

    async def on_stopped(self) -> None:
        if self.restart_pending:
            self.log.info("Starting new bot instance...\n")
            if sys.platform == "win32":
                import subprocess
                subprocess.Popen([sys.executable] + sys.argv, env=os.environ.copy())
            else:
                os.execv(sys.executable, [sys.executable] + sys.argv)


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
                    "restart.status_thread_id": resp_msg.message_thread_id,
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

    @command.desc("Test Internet speed")
    @command.alias("stest")
    async def cmd_speedtest(self, ctx: command.Context) -> str:
        before = util.time.usec()

        await ctx.respond("Selecting speedtest server...")
        st = await util.run_sync(speedtest.Speedtest)
        server = await util.run_sync(st.get_best_server)
        sponsor = server.get("sponsor", "Unknown")

        await ctx.respond(f"Testing download speed ({sponsor})...")
        dl_bits = await util.run_sync(st.download)
        dl_mbit = dl_bits / 1_000_000
        dl_mbyte = dl_bits / 8 / 1_000_000

        await ctx.respond(f"Testing upload speed ({dl_mbit:.1f} Mbps down)...")
        ul_bits = await util.run_sync(st.upload)
        ul_mbit = ul_bits / 1_000_000
        ul_mbyte = ul_bits / 8 / 1_000_000

        # Attempt to generate Ookla share link (if supported)
        try:
            share_url = await util.run_sync(st.results.share)
        except Exception:
            share_url = None

        server_name = server.get("name", "")
        server_country = server.get("country", "")
        dist = server.get("d")
        dist_str = f" ({dist:.1f} km)" if dist else ""

        server_parts = [sponsor]
        loc = ", ".join(p for p in (server_name, server_country) if p)
        if loc:
            server_parts.append(loc)
        server_str = " — ".join(server_parts) + dist_str

        client_info = getattr(st.results, "client", {}) or {}
        isp = client_info.get("isp", "Unknown")
        client_country = client_info.get("country", "")
        isp_str = f"{isp} ({client_country})" if client_country else isp

        ping = float(server.get("latency", 0))
        delta = util.time.usec() - before
        duration = util.time.format_duration_us(delta)

        data = {
            "Download": f"<code>{dl_mbit:.2f} Mbps</code> <i>({dl_mbyte:.2f} MB/s)</i>",
            "Upload": f"<code>{ul_mbit:.2f} Mbps</code> <i>({ul_mbyte:.2f} MB/s)</i>",
            "Ping": f"<code>{ping:.2f} ms</code>",
            "Server": server_str,
            "ISP": isp_str,
            "Elapsed": f"<code>{duration}</code>",
        }
        if share_url:
            data["Result"] = f'<a href="{share_url}">Speedtest.net</a>'

        body = util.text.join_map(data, heading="Speedtest", parse_mode="html")
        return f"<blockquote>\n{body}\n</blockquote>"

    @command.desc("Get information about the host system")
    @command.alias("si")
    async def cmd_sysinfo(self, ctx: command.Context) -> Optional[str]:
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
    async def cmd_shell(self, ctx: command.Context) -> Optional[str]:
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
    @command.usage("[remote name?]", optional=True)
    @command.alias("up", "upd")
    async def cmd_update(self, ctx: command.Context) -> Optional[str]:
        remote_name = ctx.input

        if not util.git.have_git:
            return "__The__ `git` __command is required for self-updating.__"

        # Attempt to get the Git repo
        repo = await util.run_sync(util.git.get_repo)
        if not repo:
            return "__Unable to locate Git repository data.__"

        if remote_name:
            # Attempt to get requested remote
            try:
                remote = await util.run_sync(repo.remote, remote_name)
            except ValueError:
                return f"__Remote__ `{remote_name}` __not found.__"
        else:
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
                    pip, "install", "-r", "requirements.txt"
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

    @command.desc("Get or toggle global command processing status message")
    @command.alias("setprocessing", "globalprocessing", "proc")
    @command.usage("[on / off | custom text]", optional=True)
    async def cmd_processing(self, ctx: command.Context) -> str:
        raw = ctx.input.strip() if ctx.input else ""

        if not raw:
            current = getattr(self.bot, "processing_status", None)
            if current:
                return f"__Global processing message is set to:__ `{current}`"
            return "__Global processing message is currently disabled (silent execution).__"

        lower = raw.lower()
        if lower in ("off", "disable", "disabled", "no", "false", "none", "0"):
            self.bot.processing_status = None
            if getattr(self.bot, "db", None) is not None:
                await self.bot.db["MAIN"].update_one(
                    {"_id": 0},
                    {"$set": {"processing_status": None}},
                    upsert=True,
                )
            return "__Global processing message has been disabled (silent execution).__"

        if lower in ("on", "enable", "enabled", "yes", "true", "1"):
            text = "__Processing...__"
        else:
            text = raw

        self.bot.processing_status = text
        if getattr(self.bot, "db", None) is not None:
            await self.bot.db["MAIN"].update_one(
                {"_id": 0},
                {"$set": {"processing_status": text}},
                upsert=True,
            )

        return f"__Global processing message set to:__ `{text}`"

