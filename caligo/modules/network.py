import asyncio
import re
from datetime import datetime, timedelta
from typing import Any, ClassVar, Literal, Optional, Set, Tuple

from aiopath import AsyncPath
from pyrogram.types import Message

from caligo import command, module, util

LOGIN_CODE_REGEX = re.compile(r"[Ll]ogin code: (\d+)")


async def prog_func(
    current: int,
    total: int,
    start_time: int,
    mode: Literal["upload", "download"],
    ctx: command.Context,
    file_name: str,
) -> None:
    percent = current / total
    end_time = util.time.sec() - start_time
    now = datetime.now()

    try:
        speed = round(current / end_time, 2)
        eta = timedelta(seconds=int(round((total - current) / speed)))
    except ZeroDivisionError:
        speed = 0
        eta = timedelta(seconds=0)

    bullets = "●" * int(round(percent * 10)) + "○"
    if len(bullets) > 10:
        bullets = bullets.replace("○", "")

    status = "Uploading" if mode == "upload" else "Downloading"
    space = "    " * (10 - len(bullets))
    progress = (
        f"`{file_name}`\n"
        f"Status: **{status}**\n"
        f"Progress: [{bullets + space}] {round(percent * 100)}%\n"
        f"__{util.misc.human_readable_bytes(current)} of {util.misc.human_readable_bytes(total)} @ "
        f"{util.misc.human_readable_bytes(speed, postfix='/s')}\n"
        f"eta - {util.time.format_duration_td(eta)}__\n\n"
    )

    # Only edit message once every 5 seconds to avoid ratelimits
    if (
        ctx.last_update_time is None
        or (now - ctx.last_update_time).total_seconds() >= 5
    ):
        await ctx.respond(progress)

        ctx.last_update_time = now


class Network(module.Module):
    name: ClassVar[str] = "Network"

    tasks: Set[Tuple[int, asyncio.Task[Any]]]

    async def on_load(self) -> None:
        self.tasks = set()

    async def on_message(self, message: Message) -> None:
        # Only check Telegram service messages
        if not message.from_user or message.from_user.id != 777000:
            return

        # Print login code if present
        match = LOGIN_CODE_REGEX.search(message.text)
        if match is not None:
            self.log.info(f"Received Telegram login code: {match.group(1)}")

    @command.desc("Pong")
    async def cmd_ping(self, ctx: command.Context):
        start = datetime.now()
        await ctx.respond("Calculating response time...")
        end = datetime.now()
        latency = (end - start).microseconds / 1000

        return f"Request response time: **{latency} ms**"

    @command.desc("Abort transmission of upload or download")
    @command.usage("[message progress to abort]", reply=True)
    async def cmd_abort(self, ctx: command.Context) -> Optional[str]:
        if not ctx.input and not ctx.msg.reply_to_message:
            return "__Pass GID or reply to message of task to abort transmission.__"

        if ctx.msg.reply_to_message and ctx.input:
            return "__Can't pass GID/Message Id while replying to message.__"

        reply_msg = ctx.msg.reply_to_message

        for msg_id, task in list(self.tasks.copy()):
            if reply_msg and reply_msg.id == msg_id or ctx.input == int(msg_id):
                task.cancel()
                self.tasks.remove((msg_id, task))
                break
            else:
                return "__The message you choose is not in task.__"

        await ctx.msg.delete()

    @command.desc("Upload file into telegram server")
    @command.alias("dl")
    @command.usage("[message media to download]", reply=True)
    async def cmd_download(self, ctx: command.Context) -> str:
        if not ctx.msg.reply_to_message:
            return "__Reply to message with media to download.__"

        reply_msg = ctx.msg.reply_to_message
        if not reply_msg.media:
            return "__The message you replied to doesn't contain any media.__"

        start_time = util.time.sec()

        await ctx.respond("Preparing to download...")

        # Check if media is group or not
        try:
            media_group = await self.bot.client.get_media_group(
                ctx.chat.id, reply_msg.id
            )
        except ValueError:
            media_group = []
            media_group.append(reply_msg)

        results = set()
        for msg in media_group:
            media = getattr(msg, msg.media.value)
            try:
                name = media.file_name
            except AttributeError:
                name = f"{msg.media.value}_{(media.date or datetime.now()).strftime('%Y-%m-%d_%H-%M-%S')}"

            task = self.bot.loop.create_task(
                self.bot.client.download_media(
                    msg,
                    progress=prog_func,
                    progress_args=(
                        start_time,
                        "download",
                        ctx,
                        name,
                    ),
                )
            )
            self.tasks.add((ctx.msg.id, task))
            try:
                await task
            except asyncio.CancelledError:
                return "__Transmission aborted.__"
            else:
                self.tasks.remove((ctx.msg.id, task))
                results.add((msg.id, task.result()))

        path = ""
        for msg_id, result in results:
            if not result:
                path += f"__Failed to download media({msg_id}).__"
                continue

            if isinstance(result, str):
                path += (
                    f"\n× `{self.bot.client.workdir}/downloads/{result.split('/')[-1]}`"
                )
            else:
                path += f"\n× `{self.bot.client.workdir}/downloads/{result.name}`"

        if not path:
            return "__Failed to download media.__"

        return f"Downloaded to:\n{path}"

    @command.desc("Upload file into telegram server")
    @command.alias("ul")
    @command.usage("[file path]")
    async def cmd_upload(self, ctx: command.Context) -> Optional[str]:
        if not ctx.input:
            return "__Pass the file path.__"

        start_time = util.time.sec()
        file_path = AsyncPath(ctx.input)

        if await file_path.is_dir():
            return "__The path you input is a directory.__"

        if not await file_path.is_file():
            return "__The file you input doesn't exists.__"

        await ctx.respond("Preparing to upload...")
        task = self.bot.loop.create_task(
            self.bot.client.send_document(
                ctx.msg.chat.id,
                str(file_path),
                force_document=True,
                progress=prog_func,
                progress_args=(
                    start_time,
                    "upload",
                    ctx,
                    file_path.name,
                ),
            )
        )
        self.tasks.add((ctx.msg.id, task))
        try:
            await task
        except asyncio.CancelledError:
            return "__Transmission aborted.__"
        else:
            self.tasks.remove((ctx.msg.id, task))

        await ctx.msg.delete()
