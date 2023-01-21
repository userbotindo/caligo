import inspect
import io
import os
import re
import sys
import traceback
from datetime import datetime
from html import escape
from typing import Any, ClassVar, Optional, Tuple

import pyrogram
from meval import meval

from caligo import command, module, util


class DebugModule(module.Module):
    name: ClassVar[str] = "Debug"

    @command.desc("Pong")
    async def cmd_ping(self, ctx: command.Context):
        start = datetime.now()
        await ctx.respond("Calculating response time...")
        end = datetime.now()
        latency = (end - start).microseconds / 1000

        return f"Request response time: **{latency} ms**"

    @command.desc("Evaluate code")
    @command.usage("[code snippet]")
    @command.alias("exec")
    async def cmd_eval(self, ctx: command.Context) -> Optional[str]:
        code = ctx.input
        if not code:
            return "Give me code to evaluate."

        out_buf = io.StringIO()

        async def _eval() -> Tuple[str, Optional[str]]:
            # Message sending helper for convenience
            async def send(*args: Any, **kwargs: Any) -> pyrogram.types.Message:
                return await ctx.msg.reply(*args, **kwargs)

            # Print wrapper to capture output
            # We don't override sys.stdout to avoid interfering with other output
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
                # Bot
                "command": command,
                "module": module,
                "util": util,
            }

            try:
                return "", await meval(code, globals(), **eval_vars)
            except Exception as e:  # skipcq: PYL-W0703
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

        if len(out) > 4096:
            with io.BytesIO(str.encode(out)) as out_file:
                out_file.name = "eval.text"
                await ctx.msg.reply_document(
                    document=out_file, caption=code, disable_notification=True
                )

            return None

        await ctx.respond(
            f"""{prefix}<b>Input:</b>
<pre language="python">{escape(code)}</pre>
<b>Output:</b>
<pre language="python">{escape(out)}</pre>

Time: {el_str}""",
            parse_mode=pyrogram.enums.parse_mode.ParseMode.HTML,
        )
