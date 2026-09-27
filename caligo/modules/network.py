import asyncio
import mimetypes
import os
import re
from datetime import datetime, timedelta
from typing import Any, ClassVar, Iterable, List, Literal, Optional, Set, Tuple

from pyrogram.types import (
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)

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


PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".wmv", ".3gp", ".m4v"}
AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wma"}


def get_media_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in PHOTO_EXTS:
        return "photo"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"

    mime, _ = mimetypes.guess_type(path)
    if mime:
        if mime.startswith("image/") and ext != ".gif":
            return "photo"
        if mime.startswith("video/") or ext == ".gif":
            return "video"
        if mime.startswith("audio/"):
            return "audio"

    return "document"


def chunk_list(items: List[Any], chunk_size: int = 10) -> Iterable[List[Any]]:
    for i in range(0, len(items), chunk_size):
        yield items[i : i + chunk_size]


async def send_single_media(
    client: Any,
    chat_id: int | str,
    file_path: str,
    media_type: str,
    thread_id: Optional[int],
    start_time: int,
    ctx: command.Context,
) -> Any:
    file_name = os.path.basename(file_path)
    prog_args = (start_time, "upload", ctx, file_name)

    if media_type == "photo":
        try:
            return await client.send_photo(
                chat_id,
                photo=file_path,
                caption=file_name,
                message_thread_id=thread_id,
                progress=prog_func,
                progress_args=prog_args,
            )
        except Exception:
            return await client.send_document(
                chat_id,
                document=file_path,
                force_document=True,
                message_thread_id=thread_id,
                progress=prog_func,
                progress_args=prog_args,
            )
    elif media_type == "video":
        try:
            return await client.send_video(
                chat_id,
                video=file_path,
                caption=file_name,
                supports_streaming=True,
                message_thread_id=thread_id,
                progress=prog_func,
                progress_args=prog_args,
            )
        except Exception:
            return await client.send_document(
                chat_id,
                document=file_path,
                force_document=True,
                message_thread_id=thread_id,
                progress=prog_func,
                progress_args=prog_args,
            )
    elif media_type == "audio":
        try:
            title = os.path.splitext(file_name)[0]
            return await client.send_audio(
                chat_id,
                audio=file_path,
                caption=file_name,
                title=title,
                message_thread_id=thread_id,
                progress=prog_func,
                progress_args=prog_args,
            )
        except Exception:
            return await client.send_document(
                chat_id,
                document=file_path,
                force_document=True,
                message_thread_id=thread_id,
                progress=prog_func,
                progress_args=prog_args,
            )
    else:
        return await client.send_document(
            chat_id,
            document=file_path,
            force_document=True,
            message_thread_id=thread_id,
            progress=prog_func,
            progress_args=prog_args,
        )


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
            is_match = False
            if reply_msg and reply_msg.id == msg_id:
                is_match = True
            elif ctx.input and ctx.input.isdigit() and int(ctx.input) == msg_id:
                is_match = True

            if is_match:
                task.cancel()
                self.tasks.discard((msg_id, task))
                break
        else:
            return "__The message you choose is not in task.__"

        await ctx.msg.delete()

    @command.desc("Download file from telegram server")
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
            if getattr(reply_msg, "media_group_id", None):
                media_group = await self.bot.client.get_media_group(
                    ctx.chat.id, reply_msg.id
                )
            else:
                media_group = [reply_msg]
        except Exception:
            media_group = [reply_msg]

        results = []
        for msg in media_group:
            if not msg.media:
                continue

            media = getattr(msg, msg.media.value, None)
            if not media:
                continue

            file_name = getattr(media, "file_name", None)
            if not file_name:
                ext = ".jpg" if msg.photo else (
                    ".mp4" if (msg.video or msg.animation or msg.video_note) else (
                        ".mp3" if msg.audio else (
                            ".ogg" if msg.voice else (
                                ".webp" if msg.sticker else ""
                            )
                        )
                    )
                )
                date_str = (getattr(media, "date", None) or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
                file_name = f"{msg.media.value}_{date_str}{ext}"

            task = self.bot.loop.create_task(
                self.bot.client.download_media(
                    msg,
                    progress=prog_func,
                    progress_args=(
                        start_time,
                        "download",
                        ctx,
                        file_name,
                    ),
                )
            )
            self.tasks.add((ctx.msg.id, task))
            try:
                result = await task
            except asyncio.CancelledError:
                return "__Transmission aborted.__"
            finally:
                self.tasks.discard((ctx.msg.id, task))

            results.append((msg.id, result, file_name))

        path = ""
        for msg_id, result, name in results:
            if not result:
                path += f"\n× Failed to download `{name}`"
                continue

            size_str = ""
            if isinstance(result, str) and os.path.isfile(result):
                size_str = f" ({util.misc.human_readable_bytes(os.path.getsize(result))})"

            path += f"\n× `{result}`{size_str}"

        if not path:
            return "__Failed to download media.__"

        return f"**Downloaded to:**\n{path}"

    @command.desc("Upload file or folder into telegram server")
    @command.alias("ul")
    @command.usage("[file/folder path] [-d/--doc]")
    async def cmd_upload(self, ctx: command.Context) -> Optional[str]:
        raw_input = ctx.input.strip()
        if not raw_input and ctx.msg.reply_to_message and ctx.msg.reply_to_message.text:
            raw_input = ctx.msg.reply_to_message.text.strip()

        if not raw_input:
            return "__Pass the file or folder path (or reply to a message with path).__"

        # Check for force document flag
        force_doc = False
        parts = raw_input.split()
        clean_parts = []
        for p in parts:
            if p in ("-d", "--doc", "--document", "-f", "--force-document"):
                force_doc = True
            else:
                clean_parts.append(p)

        target_path = " ".join(clean_parts).strip()
        if (target_path.startswith('"') and target_path.endswith('"')) or (
            target_path.startswith("'") and target_path.endswith("'")
        ):
            target_path = target_path[1:-1]

        target_path = os.path.abspath(os.path.expanduser(target_path))

        if not os.path.exists(target_path):
            return f"__Path `{target_path}` does not exist.__"

        start_time = util.time.sec()

        if os.path.isfile(target_path):
            await ctx.respond("Preparing to upload file...")
            media_type = "document" if force_doc else get_media_type(target_path)

            async def _upload_single() -> None:
                await send_single_media(
                    client=self.bot.client,
                    chat_id=ctx.msg.chat.id,
                    file_path=target_path,
                    media_type=media_type,
                    thread_id=ctx.msg.message_thread_id,
                    start_time=start_time,
                    ctx=ctx,
                )

            task = self.bot.loop.create_task(_upload_single())
            self.tasks.add((ctx.msg.id, task))
            try:
                await task
            except asyncio.CancelledError:
                return "__Transmission aborted.__"
            finally:
                self.tasks.discard((ctx.msg.id, task))

        elif os.path.isdir(target_path):
            entries = sorted(os.listdir(target_path))
            all_files = [
                os.path.join(target_path, f)
                for f in entries
                if os.path.isfile(os.path.join(target_path, f)) and not f.startswith(".")
            ]

            if not all_files:
                return f"__Directory `{target_path}` contains no files to upload.__"

            await ctx.respond(
                f"Preparing to upload {len(all_files)} files from folder..."
            )

            async def _upload_directory() -> None:
                if force_doc:
                    doc_chunks = list(chunk_list(all_files, 10))
                    total_chunks = len(doc_chunks)
                    for idx, chunk in enumerate(doc_chunks, 1):
                        if len(chunk) >= 2:
                            await ctx.respond(
                                f"Uploading document album ({idx}/{total_chunks})..."
                            )
                            media_group = [
                                InputMediaDocument(f, caption=os.path.basename(f))
                                for f in chunk
                            ]
                            try:
                                await self.bot.client.send_media_group(
                                    ctx.msg.chat.id,
                                    media=media_group,
                                    message_thread_id=ctx.msg.message_thread_id,
                                )
                            except Exception:
                                for f in chunk:
                                    await send_single_media(
                                        self.bot.client,
                                        ctx.msg.chat.id,
                                        f,
                                        "document",
                                        ctx.msg.message_thread_id,
                                        start_time,
                                        ctx,
                                    )
                        else:
                            await send_single_media(
                                self.bot.client,
                                ctx.msg.chat.id,
                                chunk[0],
                                "document",
                                ctx.msg.message_thread_id,
                                start_time,
                                ctx,
                            )
                else:
                    visual_files = [
                        f for f in all_files if get_media_type(f) in ("photo", "video")
                    ]
                    audio_files = [
                        f for f in all_files if get_media_type(f) == "audio"
                    ]
                    doc_files = [
                        f for f in all_files if get_media_type(f) == "document"
                    ]

                    # 1. Upload Visuals (Photos & Videos) as Media Albums
                    if visual_files:
                        visual_chunks = list(chunk_list(visual_files, 10))
                        total_v = len(visual_chunks)
                        for idx, chunk in enumerate(visual_chunks, 1):
                            if len(chunk) >= 2:
                                await ctx.respond(
                                    f"Uploading media album ({idx}/{total_v})..."
                                )
                                media_group = []
                                for f in chunk:
                                    fname = os.path.basename(f)
                                    if get_media_type(f) == "photo":
                                        media_group.append(
                                            InputMediaPhoto(f, caption=fname)
                                        )
                                    else:
                                        media_group.append(
                                            InputMediaVideo(
                                                f,
                                                caption=fname,
                                                supports_streaming=True,
                                            )
                                        )
                                try:
                                    await self.bot.client.send_media_group(
                                        ctx.msg.chat.id,
                                        media=media_group,
                                        message_thread_id=ctx.msg.message_thread_id,
                                    )
                                except Exception:
                                    for f in chunk:
                                        await send_single_media(
                                            self.bot.client,
                                            ctx.msg.chat.id,
                                            f,
                                            get_media_type(f),
                                            ctx.msg.message_thread_id,
                                            start_time,
                                            ctx,
                                        )
                            else:
                                f = chunk[0]
                                await send_single_media(
                                    self.bot.client,
                                    ctx.msg.chat.id,
                                    f,
                                    get_media_type(f),
                                    ctx.msg.message_thread_id,
                                    start_time,
                                    ctx,
                                )

                    # 2. Upload Audio Files as Music Albums
                    if audio_files:
                        audio_chunks = list(chunk_list(audio_files, 10))
                        total_a = len(audio_chunks)
                        for idx, chunk in enumerate(audio_chunks, 1):
                            if len(chunk) >= 2:
                                await ctx.respond(
                                    f"Uploading audio album ({idx}/{total_a})..."
                                )
                                media_group = [
                                    InputMediaAudio(
                                        f,
                                        caption=os.path.basename(f),
                                        title=os.path.splitext(os.path.basename(f))[0],
                                    )
                                    for f in chunk
                                ]
                                try:
                                    await self.bot.client.send_media_group(
                                        ctx.msg.chat.id,
                                        media=media_group,
                                        message_thread_id=ctx.msg.message_thread_id,
                                    )
                                except Exception:
                                    for f in chunk:
                                        await send_single_media(
                                            self.bot.client,
                                            ctx.msg.chat.id,
                                            f,
                                            "audio",
                                            ctx.msg.message_thread_id,
                                            start_time,
                                            ctx,
                                        )
                            else:
                                f = chunk[0]
                                await send_single_media(
                                    self.bot.client,
                                    ctx.msg.chat.id,
                                    f,
                                    "audio",
                                    ctx.msg.message_thread_id,
                                    start_time,
                                    ctx,
                                )

                    # 3. Upload Documents as Document Albums
                    if doc_files:
                        doc_chunks = list(chunk_list(doc_files, 10))
                        total_d = len(doc_chunks)
                        for idx, chunk in enumerate(doc_chunks, 1):
                            if len(chunk) >= 2:
                                await ctx.respond(
                                    f"Uploading document album ({idx}/{total_d})..."
                                )
                                media_group = [
                                    InputMediaDocument(
                                        f, caption=os.path.basename(f)
                                    )
                                    for f in chunk
                                ]
                                try:
                                    await self.bot.client.send_media_group(
                                        ctx.msg.chat.id,
                                        media=media_group,
                                        message_thread_id=ctx.msg.message_thread_id,
                                    )
                                except Exception:
                                    for f in chunk:
                                        await send_single_media(
                                            self.bot.client,
                                            ctx.msg.chat.id,
                                            f,
                                            "document",
                                            ctx.msg.message_thread_id,
                                            start_time,
                                            ctx,
                                        )
                            else:
                                f = chunk[0]
                                await send_single_media(
                                    self.bot.client,
                                    ctx.msg.chat.id,
                                    f,
                                    "document",
                                    ctx.msg.message_thread_id,
                                    start_time,
                                    ctx,
                                )

            task = self.bot.loop.create_task(_upload_directory())
            self.tasks.add((ctx.msg.id, task))
            try:
                await task
            except asyncio.CancelledError:
                return "__Transmission aborted.__"
            finally:
                self.tasks.discard((ctx.msg.id, task))

        await ctx.msg.delete()
