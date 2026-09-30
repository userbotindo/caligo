import asyncio
import mimetypes
import os
import re
from typing import Any, ClassVar, List, Optional, Set, Tuple, Union
from urllib.parse import urlparse

from anyio import Path as AsyncPath
from pyrogram.types import Message

from caligo import command, module, util


class Transfer(module.Module):
    name: ClassVar[str] = "Transfer"

    tasks: Set[Tuple[int, asyncio.Task[Any]]]

    @property
    def progress_style(self) -> str:
        return getattr(self.bot, "progress_style", util.media.DEFAULT_PROGRESS_STYLE)

    async def get_download_dir(self) -> AsyncPath:
        """Returns the canonical downloads directory AsyncPath."""
        client_workdir = getattr(getattr(self.bot, "client", None), "workdir", None)
        if client_workdir:
            path = (await AsyncPath(client_workdir).resolve()) / "downloads"
        else:
            path = await AsyncPath("downloads").resolve()
        await path.mkdir(parents=True, exist_ok=True)
        return path

    async def get_download_dirs(self) -> List[AsyncPath]:
        """Returns all known download directories (both workdir/downloads and ./downloads)."""
        primary = await self.get_download_dir()
        caligo_dl = await (AsyncPath("caligo") / "downloads").resolve()
        root_dl = await AsyncPath("downloads").resolve()

        candidate_dirs = [primary, caligo_dl, root_dl]
        unique_dirs: List[AsyncPath] = []
        for d in candidate_dirs:
            if d not in unique_dirs and await d.exists():
                unique_dirs.append(d)
        return unique_dirs

    _async_rmtree = staticmethod(util.system.async_rmtree)

    async def on_load(self) -> None:
        self.tasks = set()

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

    @command.desc("Download file from Telegram (link/reply/id) or direct URL")
    @command.alias("dl")
    @command.usage("[link | id | reply to media]", optional=True, reply=True)
    async def cmd_download(self, ctx: command.Context) -> str:
        start_time = util.time.sec()
        target_msg = None
        target_chat: Optional[Union[int, str]] = None
        target_msg_id: Optional[int] = None
        http_url: Optional[str] = None

        if ctx.input:
            first_arg = ctx.input.strip().split()[0]
            tg_link_info = util.tg.parse_telegram_message_link(first_arg)
            if tg_link_info:
                target_chat, target_msg_id = tg_link_info
            elif first_arg.isdigit():
                target_chat = ctx.chat.id
                target_msg_id = int(first_arg)
            else:
                parsed = urlparse(first_arg)
                if parsed.scheme in ("http", "https"):
                    http_url = first_arg

        if not target_chat and not http_url and not target_msg_id:
            reply_msg = ctx.msg.reply_to_message
            if reply_msg and reply_msg.media:
                target_msg = reply_msg
            elif reply_msg and reply_msg.text:
                reply_first = reply_msg.text.strip().split()[0]
                tg_link_info = util.tg.parse_telegram_message_link(reply_first)
                if tg_link_info:
                    target_chat, target_msg_id = tg_link_info
                elif reply_first.isdigit():
                    target_chat = ctx.chat.id
                    target_msg_id = int(reply_first)
                else:
                    parsed = urlparse(reply_first)
                    if parsed.scheme in ("http", "https"):
                        http_url = reply_first

        if not target_chat and not http_url and not target_msg:
            return (
                "__Pass a Telegram message link/ID, a direct URL, "
                "or reply to a message with media to download.__"
            )

        # Handle direct HTTP/HTTPS URL download
        if http_url:
            await ctx.respond("Connecting to URL...")

            async def _download_http(url: str) -> str:
                dest_dir = await self.get_download_dir()

                async with self.bot.http.stream("GET", url, follow_redirects=True) as resp:
                    if resp.status_code >= 400:
                        raise RuntimeError(f"HTTP error {resp.status_code}: {resp.reason_phrase}")

                    raw_filename = ""
                    content_disposition = resp.headers.get("content-disposition", "")
                    if "filename=" in content_disposition:
                        match = re.search(
                            r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)["\']?',
                            content_disposition,
                        )
                        if match:
                            raw_filename = match.group(1).strip()

                    if not raw_filename:
                        parsed_path = urlparse(url).path
                        raw_filename = AsyncPath(parsed_path).name.split("?")[0]

                    if not raw_filename:
                        content_type = resp.headers.get("content-type", "").split(";")[0].strip()
                        ext = mimetypes.guess_extension(content_type) or ".bin"
                        raw_filename = f"download_{util.time.sec()}{ext}"

                    dest_path = dest_dir / raw_filename
                    base = dest_path.stem
                    ext = dest_path.suffix
                    counter = 1
                    while await dest_path.exists():
                        dest_path = dest_dir / f"{base}_{counter}{ext}"
                        counter += 1

                    total_size = int(resp.headers.get("content-length", 0))
                    prog_cb = util.media.create_progress_callback(
                        ctx=ctx,
                        start_time=start_time,
                        mode="download",
                        file_name=dest_path.name,
                        style=self.progress_style,
                    )

                    current_size = 0
                    try:
                        async with await dest_path.open("wb") as f:
                            async for chunk in resp.aiter_bytes(chunk_size=65536):
                                await f.write(chunk)
                                current_size += len(chunk)
                                if total_size > 0:
                                    await prog_cb(current_size, total_size)
                    except Exception:
                        if await dest_path.exists():
                            await dest_path.unlink()
                        raise

                    return str(dest_path)

            task = self.bot.loop.create_task(_download_http(http_url))
            self.tasks.add((ctx.msg.id, task))
            try:
                dest_path = await task
            except asyncio.CancelledError:
                return "__Transmission aborted.__"
            except Exception as e:
                return f"__Download failed: {e}__"
            finally:
                self.tasks.discard((ctx.msg.id, task))

            size_str = ""
            final_p = AsyncPath(dest_path)
            if await final_p.is_file():
                stat = await final_p.stat()
                size_str = f" ({util.misc.human_readable_bytes(stat.st_size)})"
            return f"**Downloaded to:**\n\n× `{dest_path}`{size_str}"

        # Fetch message if target_msg_id was provided
        if target_msg_id is not None:
            await ctx.respond("Fetching message from link...")
            try:
                target_msg = await self.bot.client.get_messages(
                    target_chat, target_msg_id
                )
            except Exception as e:
                return f"__Failed to fetch message: {e}__"

            if not target_msg or getattr(target_msg, "empty", False):
                return "__The specified message was not found or has been deleted.__"

        if target_msg is None or not target_msg.media:
            return "__The specified message doesn't contain any media.__"

        await ctx.respond("Preparing to download...")

        # Check if media is group or not
        try:
            if getattr(target_msg, "media_group_id", None):
                media_group = await self.bot.client.get_media_group(
                    target_chat or ctx.chat.id, target_msg.id
                )
            else:
                media_group = [target_msg]
        except Exception:
            media_group = [target_msg]

        results = []
        dest_dir = await self.get_download_dir()
        for msg in media_group:
            if not msg.media:
                continue

            media = getattr(msg, msg.media.value, None)
            file_name = getattr(media, "file_name", None)

            # Generate unique filename for stickers to avoid generic sticker.webp collisions
            if msg.media.value == "sticker" and hasattr(msg, "sticker") and msg.sticker:
                st = msg.sticker
                ext = ".webp"
                if getattr(st, "is_animated", False):
                    ext = ".tgs"
                elif getattr(st, "is_video", False):
                    ext = ".webm"

                file_id_part = getattr(st, "file_unique_id", util.time.sec())
                set_part = getattr(st, "set_name", None) or "pack"
                file_name = f"sticker_{set_part}_{file_id_part}{ext}"

            if not file_name:
                ext = mimetypes.guess_extension(getattr(media, "mime_type", "")) or ".bin"
                file_name = f"download_{util.time.sec()}{ext}"

            dest_path = dest_dir / file_name
            base = dest_path.stem
            ext = dest_path.suffix
            counter = 1
            while await dest_path.exists():
                file_name = f"{base}_{counter}{ext}"
                dest_path = dest_dir / file_name
                counter += 1

            prog_cb = util.media.create_progress_callback(
                ctx=ctx,
                start_time=start_time,
                mode="download",
                file_name=file_name,
                style=self.progress_style,
            )

            task = self.bot.loop.create_task(
                self.bot.client.download_media(
                    msg,
                    file_name=str(dest_path),
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
            res_async = AsyncPath(str(result))
            if await res_async.is_file():
                stat = await res_async.stat()
                size_str = f" ({util.misc.human_readable_bytes(stat.st_size)})"

            path += f"\n× `{result}`{size_str}"

        if not path:
            return "__Failed to download media.__"

        return f"**Downloaded to:**\n{path}"

    @command.desc("Delete all downloaded files or a specific file from downloads folder")
    @command.alias("cleardl", "dldel", "cldl", "rmdl")
    @command.usage("[filename | all]", optional=True, reply=True)
    async def cmd_cleardownloads(self, ctx: command.Context) -> str:
        download_dirs = await self.get_download_dirs()
        if not download_dirs:
            return "__Downloads folder does not exist or is empty.__"

        raw_input = ctx.input.strip() if ctx.input else ""

        # If no explicit input but replied to a message with text, check if text has a download path
        if not raw_input and ctx.msg.reply_to_message and ctx.msg.reply_to_message.text:
            reply_text = ctx.msg.reply_to_message.text
            match = re.search(r"[`']([^`'\n]+)[`']", reply_text)
            if match:
                potential_name = AsyncPath(match.group(1).strip()).name
                for d in download_dirs:
                    if await (d / potential_name).exists():
                        raw_input = potential_name
                        break

        # Delete all files in downloads
        if not raw_input or raw_input.lower() in ("all", "*", "-a", "--all"):
            total_size = 0
            deleted_count = 0

            for d in download_dirs:
                try:
                    async for entry in d.iterdir():
                        try:
                            if await entry.is_file() or await entry.is_symlink():
                                stat = await entry.stat()
                                total_size += stat.st_size
                                await entry.unlink()
                                deleted_count += 1
                            elif await entry.is_dir():
                                total_size += await self._async_rmtree(entry)
                                deleted_count += 1
                        except Exception as e:
                            self.log.error(f"Error removing {entry}: {e}")
                except Exception as e:
                    self.log.error(f"Error reading directory {d}: {e}")

            if deleted_count == 0:
                return "__Downloads folder is already empty.__"

            size_str = util.misc.human_readable_bytes(total_size)
            item_label = "file" if deleted_count == 1 else "files"
            return f"__Cleared {deleted_count} {item_label} ({size_str} freed).__"

        # Delete specific file or folder
        clean_name = raw_input.strip("\"'")
        if clean_name.startswith("caligo/downloads/"):
            clean_name = clean_name[len("caligo/downloads/"):]
        elif clean_name.startswith("downloads/"):
            clean_name = clean_name[len("downloads/"):]

        found_target: Optional[AsyncPath] = None
        for d in download_dirs:
            resolved_d = await d.resolve()
            target = await (d / clean_name).resolve()
            # Security check: must not escape directory resolved_d
            str_d = str(resolved_d)
            str_t = str(target)
            if not str_t.startswith(str_d + os.sep) and str_t != str_d:
                continue
            if await target.exists():
                found_target = target
                break

        if not found_target:
            return f"__Item__ `{clean_name}` __not found in downloads.__"

        try:
            if await found_target.is_file() or await found_target.is_symlink():
                stat = await found_target.stat()
                await found_target.unlink()
                size_str = util.misc.human_readable_bytes(stat.st_size)
                return f"__Deleted__ `{found_target.name}` __({size_str} freed).__"
            elif await found_target.is_dir():
                freed = await self._async_rmtree(found_target)
                size_str = util.misc.human_readable_bytes(freed)
                return f"__Deleted folder__ `{found_target.name}` __({size_str} freed).__"
        except Exception as e:
            return f"__Failed to delete__ `{clean_name}`: {e}__"

    @command.desc("Upload file or folder into telegram server")
    @command.alias("ul")
    @command.usage("[file/folder path] [-d/--doc] [-s/--sticker]")
    async def cmd_upload(self, ctx: command.Context) -> Optional[str]:
        raw_input = ctx.input.strip() if ctx.input else ""
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

        target_async = await AsyncPath(os.path.expanduser(target_path)).resolve()

        if not await target_async.exists():
            return f"__Path `{target_path}` does not exist.__"

        start_time = util.time.sec()

        async def _send_file(file_path: str, media_type: Optional[str] = None) -> Any:
            prog_cb = util.media.create_progress_callback(
                ctx=ctx,
                start_time=start_time,
                mode="upload",
                file_name=AsyncPath(file_path).name,
                style=self.progress_style,
            )
            return await util.media.send_media(
                self.bot.client,
                ctx.msg.chat.id,
                file_path,
                media_type=media_type,
                message_thread_id=ctx.msg.message_thread_id,
                progress=prog_cb,
            )

        if await target_async.is_file():
            await ctx.respond("Preparing to upload file...")
            if force_doc:
                media_type = "document"
            elif force_sticker:
                media_type = "sticker"
            else:
                media_type = util.media.get_media_type(str(target_async))

            task = self.bot.loop.create_task(_send_file(str(target_async), media_type))
            self.tasks.add((ctx.msg.id, task))
            try:
                await task
            except asyncio.CancelledError:
                return "__Transmission aborted.__"
            finally:
                self.tasks.discard((ctx.msg.id, task))

        elif await target_async.is_dir():
            all_files = [
                str(f)
                async for f in target_async.iterdir()
                if await f.is_file() and not f.name.startswith(".")
            ]
            all_files.sort()

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
                            media_group = util.media.build_media_group(
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
                        if util.media.get_media_type(f) in ("photo", "video")
                    ]
                    audio_files = [
                        f
                        for f in all_files
                        if util.media.get_media_type(f) == "audio"
                    ]
                    sticker_files = [
                        f
                        for f in all_files
                        if util.media.get_media_type(f) == "sticker"
                    ]
                    doc_files = [
                        f
                        for f in all_files
                        if util.media.get_media_type(f) == "document"
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
                                media_group = util.media.build_media_group(chunk)
                                try:
                                    await self.bot.client.send_media_group(
                                        ctx.msg.chat.id,
                                        media=media_group,
                                        message_thread_id=ctx.msg.message_thread_id,
                                    )
                                except Exception:
                                    for f in chunk:
                                        await _send_file(f)
                            else:
                                await _send_file(chunk[0])

                    # 2. Upload Audio Files as Audio Albums
                    if audio_files:
                        audio_chunks = list(util.misc.chunk_list(audio_files, 10))
                        total_a = len(audio_chunks)
                        for idx, chunk in enumerate(audio_chunks, 1):
                            if len(chunk) >= 2:
                                await ctx.respond(
                                    f"Uploading audio album ({idx}/{total_a})..."
                                )
                                media_group = util.media.build_media_group(
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

                    # 3. Upload Stickers Individually
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
                                media_group = util.media.build_media_group(
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
