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
from pyrogram.enums import ParseMode

from caligo import command, module, util


class Debug(module.Module):
    name: ClassVar[str] = "Debug"

    @command.desc("Pong")
    async def cmd_ping(self, ctx: command.Context):
        start = datetime.now()
        await ctx.respond("Calculating response time...")
        end = datetime.now()
        latency = (end - start).microseconds / 1000

        return f"Request response time: **{latency} ms**"

    @command.desc("Get the code of a command")
    @command.usage("[command name]")
    async def cmd_src(self, ctx: command.Context) -> Optional[str]:
        cmd_name = ctx.input

        if cmd_name not in self.bot.commands:
            return f"__Command__ `{cmd_name}` __doesn't exist.__"

        src = await util.run_sync(inspect.getsource, self.bot.commands[cmd_name].func)
        # Strip first level of indentation
        filtered_src = re.sub(r"^ {4}", "", src, flags=re.MULTILINE)

        await ctx.respond(
            f"<pre language='python'>{filtered_src}</pre>", parse_mode=ParseMode.HTML
        )

    @command.desc("Get all contextually relevant IDs")
    @command.alias("user")
    async def cmd_id(self, ctx: command.Context) -> None:
        lines = []

        if ctx.msg.chat.id:
            lines.append(f"Chat ID: `{ctx.msg.chat.id}`")

        lines.append(f"My user ID: `{self.bot.uid}`")

        if ctx.msg.reply_to_message:
            reply_msg = ctx.msg.reply_to_message
            sender = reply_msg.from_user
            lines.append(f"Message ID: `{reply_msg.id}`")

            if sender:
                lines.append(f"Message author ID: `{sender.id}`")

            if reply_msg.forward_from:
                lines.append(
                    f"Forwarded message author ID: `{reply_msg.forward_from.id}`"
                )

            f_chat = None
            if reply_msg.forward_from_chat:
                f_chat = reply_msg.forward_from_chat

                lines.append(f"Forwarded message {f_chat.type} ID: `{f_chat.id}`")

            f_msg_id = None
            if reply_msg.forward_from_message_id:
                f_msg_id = reply_msg.forward_from_message_id
                lines.append(f"Forwarded message original ID: `{f_msg_id}`")

            if f_chat is not None and f_msg_id is not None:
                uname = f_chat.username
                if uname is not None:
                    lines.append(
                        "[Link to forwarded message]"
                        f"(https://t.me/{uname}/{f_msg_id})"
                    )
                else:
                    lines.append(
                        "[Link to forwarded message]"
                        f"(https://t.me/{f_chat.id}/{f_msg_id})"
                    )

        text = (
            util.tg.pretty_print_entity(lines)
            .replace("'", "")
            .replace("list", "**List**")
        )
        await ctx.respond(text, disable_web_page_preview=True)

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
