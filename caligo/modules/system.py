import asyncio
import os
import inspect
import re
import io
import sys
import traceback
from typing import Any, ClassVar, Dict, Optional, Union, Tuple

import pyrogram
from meval import meval

from .. import command, module, util


class SystemModule(module.Module):
    name: ClassVar[str] = "System"
    lock: asyncio.Lock
    restart_pending: bool

    async def on_load(self):
        self.restart_pending = False
        self.lock = asyncio.Lock()

        self.db = self.bot.get_db("system")

    @command.desc("Run a snippet in a shell")
    @command.usage("[shell snippet]")
    @command.alias("sh")
    async def cmd_shell(self, ctx: command.Context) -> str:
        if not ctx.cmd:
            return "Give me code to run"
        snip = tuple(map(lambda x: (x), ctx.cmd))
        text = " ".join(ctx.cmd)

        await ctx.respond("Running snippet...")
        before = util.time.usec()

        try:
            stdout, _, ret = await util.system.run_command(
                *snip, timeout=120
            )
        except FileNotFoundError as E:
            after = util.time.usec()
            return (
                f"**In:**\n```{text}```\n\n"
                "**Out:**\n\n"
                f"⚠️ Error executing command:\n```{util.error.format_exception(E)}```\n\n"
                f"Time: {util.time.format_duration_us(after - before)}"
            )
        except asyncio.TimeoutError:
            after = util.time.usec()
            return (
                f"**In:**\n```{text}```\n\n"
                "**Out:**\n\n"
                "🕑 Snippet failed to finish within 2 minutes.\n\n"
                f"Time: {util.time.format_duration_us(after - before)}"
            )

        after = util.time.usec()

        el_us = after - before
        el_str = f"\nTime: {util.time.format_duration_us(el_us)}"

        if not stdout:
            stdout = "[no output]"
        elif stdout[-1:] != "\n":
            stdout += "\n"

        err = f"⚠️ Return code: {ret}" if ret != 0 else ""
        return f"**In:**\n```{text}```\n\n**Out:**\n\n```{stdout}```{err}{el_str}"

    @command.desc("Evaluate code")
    @command.usage("[code snippet]")
    @command.alias("ev", "exec")
    async def cmd_eval(self, ctx: command.Context) -> str:
        if not ctx.cmd:
            return "Give me code to evaluate."
        code = " ".join(ctx.cmd)
        out_buf = io.StringIO()

        async def _eval() -> Tuple[str, str]:
            async def send(*args: Any, **kwargs: Any) -> pyrogram.types.Message:
                return await ctx.msg.reply(*args, **kwargs)

            def _print(*args: Any, **kwargs: Any) -> None:
                if "file" not in kwargs:
                    kwargs["file"] = out_buf

                return print(*args, **kwargs)

            eval_vars = {
                # Contextual info
                "self": self,
                "ctx": ctx,
                "bot": self.bot,
                "loop": self.bot.loop,
                "client": self.bot.client,
                "commands": self.bot.commands,
                "listeners": self.bot.listeners,
                "modules": self.bot.modules,
                "stdout": out_buf,
                # Convenience aliases
                "context": ctx,
                "msg": ctx.msg,
                "message": ctx.msg,
                "db": self.bot.db,
                # Helper functions
                "send": send,
                "print": _print,
                # Built-in modules
                "inspect": inspect,
                "os": os,
                "re": re,
                "sys": sys,
                "traceback": traceback,
                # Third-party modules
                "pyrogram": pyrogram,
                # Custom modules
                "command": command,
                "module": module,
                "util": util,
            }

            try:
                return "", await meval(code, globals(), **eval_vars)
            except Exception as e:
                # Find first traceback frame involving the snippet
                first_snip_idx = -1
                tb = traceback.extract_tb(e.__traceback__)
                for i, frame in enumerate(tb):
                    if frame.filename == "<string>" or frame.filename.endswith(
                        "ast.py"
                    ):
                        first_snip_idx = i
                        break

                # Re-raise exception if it wasn't caused by the snippet
                if first_snip_idx == -1:
                    raise e

                # Return formatted stripped traceback
                stripped_tb = tb[first_snip_idx:]
                formatted_tb = util.error.format_exception(e, tb=stripped_tb)
                return "⚠️ Error executing snippet\n\n", formatted_tb

        before = util.time.usec()
        prefix, result = await _eval()
        after = util.time.usec()

        # Always write result if no output has been collected thus far
        if not out_buf.getvalue() or result is not None:
            print(result, file=out_buf)

        el_us = after - before
        el_str = util.time.format_duration_us(el_us)

        out = out_buf.getvalue()
        # Strip only ONE final newline to compensate for our message formatting
        if out.endswith("\n"):
            out = out[:-1]

        return f"""{prefix}**In:**
```{code}```

**Out:**
```{out}```

Time: {el_str}"""

    @command.desc("Stop this bot")
    async def cmd_stop(self, ctx: command.Context) -> None:
        await ctx.respond("Stopping bot...")
        self.bot.stop_manual = True
        await ctx.respond("Stopped")
        await self.bot.stop()

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
        async with self.lock:
            await self.db.update_one(
                {"_id": self.bot.uid},
                {
                    "$addToSet": {
                        "restart": {
                            "status_chat_id": resp_msg.chat.id,
                            "status_message_id": resp_msg.message_id,
                            "time": restart_time or util.time.usec(),
                            "reason": reason
                        }
                    }
                },
                upsert=True
            )
        # Initiate the restart
        self.restart_pending = True
        self.log.info("Preparing to restart...")
        await self.bot.stop()

    async def on_start(self, time_us: int) -> None:
        # Update restart status message if applicable
        data: Optional[Dict[Union[str, int]]] = await self.db.find_one({"_id": self.bot.uid})
        if data is not None:
            restart = data.get("restart")[0]
            # Fetch status message info
            rs_time: Optional[int] = restart.get("time")
            rs_chat_id: Optional[int] = restart.get("status_chat_id")
            rs_message_id: Optional[int] = restart.get("status_message_id")
            rs_reason: Optional[str] = restart.get("restart_reason")

            # Delete DB keys first in case message editing fails
            async with self.lock:
                await self.db.delete_one({"_id": self.bot.uid})

            # Bail out if we're missing necessary values
            if rs_chat_id is None or rs_message_id is None:
                return

            # Show message
            updated = "updated and " if rs_reason == "update" else ""
            duration = util.time.format_duration_us(util.time.usec() - rs_time)
            self.log.info(f"Bot {updated}restarted in {duration}")
            status_msg = await self.bot.client.get_messages(rs_chat_id, rs_message_id)
            await self.bot.respond(status_msg, f"Bot {updated}restarted in {duration}.")

    async def on_stopped(self) -> None:
        if self.restart_pending:
            self.log.info("Starting new bot instance...\n")
            # This is safe because original arguments are reused. skipcq: BAN-B606
            os.execv(sys.executable, (sys.executable, "-m", "caligo"))
            sys.exit()
