import asyncio
import os
import re
from datetime import datetime
from typing import Any, ClassVar, Optional, Set, Tuple

from pyrogram.types import Message

from caligo import command, module, util
from caligo.core import database

LOGIN_CODE_REGEX = re.compile(r"[Ll]ogin code: (\d+)")


class Network(module.Module):
    name: ClassVar[str] = "Network"

    tasks: Set[Tuple[int, asyncio.Task[Any]]]
    db: Optional[database.AsyncCollection] = None
    progress_style: str = util.tg.DEFAULT_PROGRESS_STYLE

    async def on_load(self) -> None:
        self.tasks = set()
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
                if msg.photo:
                    ext = ".jpg"
                elif msg.video or msg.animation or msg.video_note:
                    ext = ".mp4"
                elif msg.audio:
                    ext = ".mp3"
                elif msg.voice:
                    ext = ".ogg"
                elif msg.sticker:
                    if getattr(msg.sticker, "is_animated", False):
                        ext = ".tgs"
                    elif getattr(msg.sticker, "is_video", False):
                        ext = ".webm"
                    else:
                        ext = ".webp"
                else:
                    ext = ""

                date_str = (getattr(media, "date", None) or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
                file_name = f"{msg.media.value}_{date_str}{ext}"

            prog_cb = util.tg.create_progress_callback(
                ctx=ctx,
                start_time=start_time,
                mode="download",
                file_name=file_name,
                style=self.progress_style,
            )
            task = self.bot.loop.create_task(
                self.bot.client.download_media(
                    msg,
                    progress=prog_cb,
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
    @command.usage("[file/folder path] [-d/--doc] [-s/--sticker]")
    async def cmd_upload(self, ctx: command.Context) -> Optional[str]:
        raw_input = ctx.input.strip()
        if not raw_input and ctx.msg.reply_to_message and ctx.msg.reply_to_message.text:
            raw_input = ctx.msg.reply_to_message.text.strip()

        if not raw_input:
            return "__Pass the file or folder path (or reply to a message with path).__"

        # Check for flags
        force_doc = False
        force_sticker = False
        parts = raw_input.split()
        clean_parts = []
        for p in parts:
            if p in ("-d", "--doc", "--document", "-f", "--force-document"):
                force_doc = True
            elif p in ("-s", "--sticker"):
                force_sticker = True
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

        async def _send_file(file_path: str, m_type: Optional[str] = None) -> Any:
            prog_cb = util.tg.create_progress_callback(
                ctx=ctx,
                start_time=start_time,
                mode="upload",
                file_name=os.path.basename(file_path),
                style=self.progress_style,
            )
            return await util.tg.send_media(
                client=self.bot.client,
                chat_id=ctx.msg.chat.id,
                file_path=file_path,
                media_type=m_type,
                message_thread_id=ctx.msg.message_thread_id,
                progress=prog_cb,
            )

        if os.path.isfile(target_path):
            await ctx.respond("Preparing to upload file...")
            if force_doc:
                media_type = "document"
            elif force_sticker:
                media_type = "sticker"
            else:
                media_type = util.tg.get_media_type(target_path)

            task = self.bot.loop.create_task(_send_file(target_path, media_type))
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
                    doc_chunks = list(util.misc.chunk_list(all_files, 10))
                    total_chunks = len(doc_chunks)
                    for idx, chunk in enumerate(doc_chunks, 1):
                        if len(chunk) >= 2:
                            await ctx.respond(
                                f"Uploading document album ({idx}/{total_chunks})..."
                            )
                            media_group = util.tg.build_media_group(
                                chunk, group_type="document"
                            )
                            try:
                                await self.bot.client.send_media_group(
                                    ctx.msg.chat.id,
                                    media=media_group,
                                    message_thread_id=ctx.msg.message_thread_id,
                                )
                            except Exception:
                                for f in chunk:
                                    await _send_file(f, "document")
                        else:
                            await _send_file(chunk[0], "document")
                else:
                    visual_files = [
                        f
                        for f in all_files
                        if util.tg.get_media_type(f) in ("photo", "video")
                    ]
                    audio_files = [
                        f
                        for f in all_files
                        if util.tg.get_media_type(f) == "audio"
                    ]
                    sticker_files = [
                        f
                        for f in all_files
                        if util.tg.get_media_type(f) == "sticker"
                    ]
                    doc_files = [
                        f
                        for f in all_files
                        if util.tg.get_media_type(f) == "document"
                    ]

                    # 1. Upload Visuals (Photos & Videos) as Media Albums
                    if visual_files:
                        visual_chunks = list(util.misc.chunk_list(visual_files, 10))
                        total_v = len(visual_chunks)
                        for idx, chunk in enumerate(visual_chunks, 1):
                            if len(chunk) >= 2:
                                await ctx.respond(
                                    f"Uploading media album ({idx}/{total_v})..."
                                )
                                media_group = util.tg.build_media_group(chunk)
                                try:
                                    await self.bot.client.send_media_group(
                                        ctx.msg.chat.id,
                                        media=media_group,
                                        message_thread_id=ctx.msg.message_thread_id,
                                    )
                                except Exception:
                                    for f in chunk:
                                        await _send_file(f, util.tg.get_media_type(f))
                            else:
                                await _send_file(
                                    chunk[0], util.tg.get_media_type(chunk[0])
                                )

                    # 2. Upload Audio Files as Music Albums
                    if audio_files:
                        audio_chunks = list(util.misc.chunk_list(audio_files, 10))
                        total_a = len(audio_chunks)
                        for idx, chunk in enumerate(audio_chunks, 1):
                            if len(chunk) >= 2:
                                await ctx.respond(
                                    f"Uploading audio album ({idx}/{total_a})..."
                                )
                                media_group = util.tg.build_media_group(
                                    chunk, group_type="audio"
                                )
                                try:
                                    await self.bot.client.send_media_group(
                                        ctx.msg.chat.id,
                                        media=media_group,
                                        message_thread_id=ctx.msg.message_thread_id,
                                    )
                                except Exception:
                                    for f in chunk:
                                        await _send_file(f, "audio")
                            else:
                                await _send_file(chunk[0], "audio")

                    # 3. Upload Stickers
                    if sticker_files:
                        total_s = len(sticker_files)
                        for idx, f in enumerate(sticker_files, 1):
                            await ctx.respond(
                                f"Uploading sticker ({idx}/{total_s})..."
                            )
                            await _send_file(f, "sticker")

                    # 4. Upload Documents as Document Albums
                    if doc_files:
                        doc_chunks = list(util.misc.chunk_list(doc_files, 10))
                        total_d = len(doc_chunks)
                        for idx, chunk in enumerate(doc_chunks, 1):
                            if len(chunk) >= 2:
                                await ctx.respond(
                                    f"Uploading document album ({idx}/{total_d})..."
                                )
                                media_group = util.tg.build_media_group(
                                    chunk, group_type="document"
                                )
                                try:
                                    await self.bot.client.send_media_group(
                                        ctx.msg.chat.id,
                                        media=media_group,
                                        message_thread_id=ctx.msg.message_thread_id,
                                    )
                                except Exception:
                                    for f in chunk:
                                        await _send_file(f, "document")
                            else:
                                await _send_file(chunk[0], "document")

            task = self.bot.loop.create_task(_upload_directory())
            self.tasks.add((ctx.msg.id, task))
            try:
                await task
            except asyncio.CancelledError:
                return "__Transmission aborted.__"
            finally:
                self.tasks.discard((ctx.msg.id, task))

        await ctx.msg.delete()
