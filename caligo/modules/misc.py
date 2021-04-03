import asyncio
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import ClassVar, Dict, Optional

from .. import command, module, util


class Misc(module.Module):
    name: ClassVar[str] = "Misc"

    stop_transmission: bool
    task: Dict[int, asyncio.Task]

    async def on_load(self) -> None:
        self.stop_transmission = False
        self.task = {}

        if (not self.bot.modules.get("Aria2") and
           not self.bot.modules.get("GoogleDrive")):
            del self.bot.commands["abort"]
            del self.bot.commands["upload"]

    @command.desc("Generate a LMGTFY link (Let Me Google That For You)")
    @command.usage("[search query]")
    async def cmd_lmgtfy(self, ctx: command.Context) -> str:
        query = ctx.input
        params = urllib.parse.urlencode({"q": query})

        return f"https://lmgtfy.com/?{params}"

    @command.desc("Upload file into telegram server")
    @command.usage("[file path]")
    async def cmd_upload(self, ctx: command.Context) -> Optional[str]:
        if not ctx.input:
            return "__Pass the file path.__"

        before = util.time.sec()
        file_path = Path(ctx.input)
        last_update_time = None

        if file_path.is_dir():
            await ctx.respond("__The path you input is a directory.__")
            return
        if not file_path.is_file():
            await ctx.respond("__The file you input doesn't exists.__")
            return

        human = util.misc.human_readable_bytes
        time = util.time.format_duration_td

        def prog_func(current: int, total: int) -> None:
            nonlocal last_update_time

            if self.stop_transmission:
                self.stop_transmission = False
                self.bot.client.stop_transmission()

            percent = current / total
            after = util.time.sec() - before
            now = datetime.now()

            try:
                speed = round(current / after, 2)
                eta = timedelta(seconds=int(round((current - current) / speed)))
            except ZeroDivisionError:
                speed = 0
                eta = timedelta(seconds=0)
            bullets = "●" * int(round(percent * 10)) + "○"
            if len(bullets) > 10:
                bullets = bullets.replace("○", "")

            space = '    ' * (10 - len(bullets))
            progress = (
                f"`{file_path.name}`\n"
                f"Status: **Uploading**\n"
                f"Progress: [{bullets + space}] {round(percent * 100)}%\n"
                f"__{human(current)} of {human(current)} @ "
                f"{human(speed, postfix='/s')}\neta - {time(eta)}__\n\n")
            # Only edit message once every 5 seconds to avoid ratelimits
            if last_update_time is None or (
                    now - last_update_time).total_seconds() >= 5:
                self.bot.loop.create_task(ctx.respond(progress))

                last_update_time = now

        task = self.bot.loop.create_task(
            self.bot.client.send_document(ctx.msg.chat.id,
                                          file_path,
                                          force_document=True,
                                          progress=prog_func))
        self.task[ctx.msg.message_id] = task
        done, _ = await asyncio.wait((task, asyncio.sleep(0.25)))
        del self.task[ctx.msg.message_id]
        for fut in done:
            fut.result()

        if task.result() is None:
            return "__Transmission aborted.__"

        return

    @command.desc("Abort transmission of upload or download")
    @command.usage("[file gid]", reply=True)
    async def cmd_abort(self, ctx) -> Optional[str]:
        if not ctx.input and not ctx.msg.reply_to_message:
            return "__Pass GID or reply to message of task to abort transmission.__"
        if ctx.msg.reply_to_message and ctx.input:
            return "__Can't pass gid while replying to message.__"
        drive = self.bot.modules.get("GoogleDrive")

        if ctx.msg.reply_to_message:
            reply_msg = ctx.msg.reply_to_message
            if (reply_msg.text.split("\n")[1].split(":")[-1].strip()
                    == "Downloading" and "GID" not in reply_msg.text):
                drive.stop_transmission = True
                await ctx.msg.delete()
                return

            msg_id = reply_msg.message_id
            if msg_id in self.task:
                self.stop_transmission = True
                await ctx.msg.delete()
                return

            for task in list(drive.task.keys()):
                if task == msg_id:
                    drive.task[task].cancel()
                    del drive.task[task]
                    break
            else:
                return "__The message you choose is not in task.__"

            await ctx.msg.delete()

            return

        aria2 = self.bot.modules.get("Aria2")
        gid = ctx.input
        ret = await aria2.cancelMirror(gid)

        return ret
