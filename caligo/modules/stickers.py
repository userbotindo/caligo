import asyncio
import io
import json
from datetime import datetime
from typing import BinaryIO, ClassVar, Tuple, Union

from anyio import Path as AsyncPath
from PIL import Image
from pyrogram import raw
from pyrogram.errors import StickersetInvalid
from pyrogram.file_id import FileId
from pyrogram.raw.functions.messages.get_sticker_set import GetStickerSet
from pyrogram.raw.types.input_sticker_set_short_name import InputStickerSetShortName
from pyrogram.raw.types.sticker_set import StickerSet

from caligo import command, module, util
from caligo.core import database

MAX_VIDEO_SIZE = 10485760
MAX_SIZE = 512
CACHE_PATH = "caligo/.cache/stickers"

# Sticker bot info and return error strings
STICKER_BOT_USERNAME = "Stickers"


async def resize_media(media: AsyncPath, video: bool) -> AsyncPath:
    if video:
        stdout, _, __ = await util.system.run_command(
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(media),
        )
        metadata = json.loads(stdout)
        width = round(metadata["streams"][0].get("width", 512))
        height = round(metadata["streams"][0].get("height", 512))

        if height == width:
            height, width = 512, 512
        elif height > width:
            height, width = 512, -1
        elif width > height:
            height, width = -1, 512

        resized_video = f"{CACHE_PATH}/{media.stem}.webm"
        await util.system.run_command(
            "ffmpeg",
            "-i",
            str(media),
            "-ss",
            "00:00:00",
            "-to",
            "00:00:03",
            "-map",
            "0:v",
            "-b",
            "256k",
            "-fs",
            "262144",
            "-c:v",
            "libvpx-vp9",
            "-vf",
            f"scale={width}:{height},fps=30",
            resized_video,
            "-y",
        )
        await media.unlink()
        return AsyncPath(resized_video)

    image: Image.Image = await util.run_sync(Image.open, str(media))
    scale = MAX_SIZE / max(image.width, image.height)
    image = await util.run_sync(
        image.resize,
        (int(image.width * scale), int(image.height * scale)),
        Image.LANCZOS,
    )

    resized_photo = f"{CACHE_PATH}/sticker.png"
    await util.run_sync(image.save, resized_photo, "PNG")

    await media.unlink()
    return AsyncPath(resized_photo)


class LengthMismatchError(Exception):
    pass


class Sticker(module.Module):
    name: ClassVar[str] = "Sticker"

    db: database.AsyncCollection

    async def on_load(self):
        # to use later maybe
        self.db = self.bot.db.get_collection(self.name.upper())

        if not await AsyncPath(CACHE_PATH).exists():
            await AsyncPath(CACHE_PATH).mkdir(parents=True)

    async def upload_sticker_media(
        self,
        media: AsyncPath,
        *,
        animation: bool = False,
        video: bool = False,
        emoji: str = "❓",
    ) -> raw.types.InputDocument:
        attributes = [
            raw.types.DocumentAttributeFilename(file_name=media.name),
            raw.types.DocumentAttributeSticker(
                alt=emoji,
                stickerset=raw.types.InputStickerSetEmpty(),
            ),
        ]

        if animation:
            mime_type = "application/x-tgsticker"
        elif video:
            mime_type = "video/webm"
            attributes.append(
                raw.types.DocumentAttributeVideo(
                    duration=3.0,
                    w=512,
                    h=512,
                    nosound=True,
                )
            )
        else:
            mime_type = "image/png"
            attributes.append(
                raw.types.DocumentAttributeImageSize(
                    w=512,
                    h=512,
                )
            )

        file = await self.bot.client.save_file(str(media))
        uploaded = await self.bot.client.invoke(
            raw.functions.messages.UploadMedia(
                peer=raw.types.InputPeerSelf(),
                media=raw.types.InputMediaUploadedDocument(
                    file=file,
                    mime_type=mime_type,
                    attributes=attributes,
                ),
            )
        )
        if not hasattr(uploaded, "document") or not isinstance(
            uploaded.document, raw.types.Document
        ):
            raise TypeError("Expected raw.types.Document from UploadMedia")

        doc = uploaded.document
        return raw.types.InputDocument(
            id=doc.id,
            access_hash=doc.access_hash,
            file_reference=doc.file_reference,
        )

    async def create_pack_mtproto(
        self,
        input_doc: raw.types.InputDocument,
        set_name: str,
        set_title: str,
        emoji: str,
    ) -> Tuple[bool, str]:
        try:
            await self.bot.client.invoke(
                raw.functions.stickers.CreateStickerSet(
                    user_id=raw.types.InputUserSelf(),
                    title=set_title,
                    short_name=set_name,
                    stickers=[
                        raw.types.InputStickerSetItem(
                            document=input_doc,
                            emoji=emoji,
                        )
                    ],
                )
            )
            return True, f"https://t.me/addstickers/{set_name}"
        except Exception as e:
            self.log.warning(f"Direct MTProto CreateStickerSet failed: {e}")
            return False, str(e)

    async def add_sticker_mtproto(
        self,
        input_doc: raw.types.InputDocument,
        set_name: str,
        emoji: str,
    ) -> Tuple[bool, str]:
        try:
            await self.bot.client.invoke(
                raw.functions.stickers.AddStickerToSet(
                    stickerset=raw.types.InputStickerSetShortName(short_name=set_name),
                    sticker=raw.types.InputStickerSetItem(
                        document=input_doc,
                        emoji=emoji,
                    ),
                )
            )
            return True, f"https://t.me/addstickers/{set_name}"
        except Exception as e:
            self.log.warning(f"Direct MTProto AddStickerToSet failed: {e}")
            return False, str(e)

    async def add_sticker(
        self,
        sticker_data: Union[str, BinaryIO],
        set_name: str,
        emoji: str,
        *,
        target: str = STICKER_BOT_USERNAME,
    ) -> Tuple[bool, str]:
        commands = [
            ("text", "/cancel", None),
            ("text", "/addsticker", "Choose a sticker set"),
            ("text", set_name, "Now send me the"),
            ("file", sticker_data, "send me an emoji"),
            ("text", emoji, "added your sticker"),
            ("text", "/done", "done"),
        ]

        success = False
        before = datetime.now()

        async with self.bot.conversation(target, timeout=25) as conv:

            async def reply_and_ack():
                # Wait for a response
                resp = await conv.get_response()
                # Ack the response to suppress its notification
                await conv.mark_read()

                return resp

            try:
                for cmd_type, data, expected_resp in commands:
                    if cmd_type == "text":
                        await conv.send_message(data)
                    elif cmd_type == "file":
                        await conv.send_file(data, force_document=True)
                    else:
                        raise TypeError(f"Unknown command type '{cmd_type}'")

                    # Wait for both the rate-limit and the bot's response
                    try:
                        resp_task = self.bot.loop.create_task(reply_and_ack())
                        done, _ = await asyncio.wait((resp_task,))
                        # Raise exceptions encountered in coroutines
                        for fut in done:
                            fut.result()

                        response = resp_task.result()
                        if expected_resp and expected_resp not in response.text:
                            return False, f'Sticker creation failed: "{response.text}"'
                    except asyncio.TimeoutError:
                        after = datetime.now()
                        delta_seconds = int((after - before).total_seconds())

                        return (
                            False,
                            f"Sticker creation timed out after {delta_seconds} seconds.",
                        )

                success = True
            finally:
                # Cancel the operation if we return early
                if not success:
                    await conv.send_message("/cancel")

        return True, f"https://t.me/addstickers/{set_name}"

    async def create_pack(
        self,
        sticker_data: Union[str, BinaryIO],
        set_name: str,
        set_title: str,
        emoji: str,
        *,
        sticker_type: str = "static",
        target: str = STICKER_BOT_USERNAME,
    ) -> Tuple[bool, str]:
        sticker_types = {
            "animated": ["/newanimated", " animated "],
            "static": ["/newpack", " "],
            "video": ["/newvideo", " video "],
        }
        commands = [
            ("text", "/cancel", None),
            ("text", sticker_types[sticker_type][0], "Yay!"),
            ("text", set_title, f"send me the{sticker_types[sticker_type][1]}sticker"),
            ("file", sticker_data, "send me an emoji"),
            ("text", emoji, "/publish"),
            ("text", "/publish", "/skip"),
            ("text", "/skip", "Animals"),
            ("text", set_name, "Kaboom!"),
        ]

        success = False
        before = datetime.now()

        async with self.bot.conversation(target, max_messages=9) as conv:

            async def reply_and_ack():
                # Wait for a response
                resp = await conv.get_response()
                # Ack the response to suppress its notification
                await conv.mark_read()

                return resp

            try:
                for cmd_type, data, expected_resp in commands:
                    if cmd_type == "text":
                        await conv.send_message(data)
                    elif cmd_type == "file":
                        await conv.send_file(data, force_document=True)
                    else:
                        raise TypeError(f"Unknown command type '{cmd_type}'")

                    # Wait for both the rate-limit and the bot's response
                    try:
                        resp_task = self.bot.loop.create_task(reply_and_ack())
                        done, _ = await asyncio.wait((resp_task,))
                        # Raise exceptions encountered in coroutines
                        for fut in done:
                            fut.result()

                        response = resp_task.result()
                        if expected_resp and expected_resp not in response.text:
                            return False, f'Sticker creation failed: "{response.text}"'
                    except asyncio.TimeoutError:
                        after = datetime.now()
                        delta_seconds = int((after - before).total_seconds())

                        return (
                            False,
                            f"Sticker creation timed out after {delta_seconds} seconds.",
                        )

                success = True
            finally:
                # Cancel the operation if we return early
                if not success:
                    await conv.send_message("/cancel")

        return True, f"https://t.me/addstickers/{set_name}"

    @command.desc("Copy a sticker into another pack")
    @command.alias("stickercopy", "kang")
    @command.usage("[sticker pack VOL number? if not set] [emoji?]", optional=True)
    async def cmd_copysticker(self, ctx: command.Context) -> str:
        reply_msg = ctx.msg.reply_to_message
        user = ctx.msg.from_user

        if not reply_msg:
            return "__Reply to a sticker to copy it.__"

        if not reply_msg.media:
            return "__Ewww can't kang that.__"

        await ctx.respond("__Preparing...__")

        pack_VOL = 1
        animation = False
        video = False
        emoji = None
        resize = False

        if reply_msg.sticker:
            if not reply_msg.sticker.file_name:
                return "__Invalid sticker.__"

            if reply_msg.sticker.emoji:
                emoji = reply_msg.sticker.emoji

            animation = reply_msg.sticker.is_animated
            video = reply_msg.sticker.is_video
            if not (
                reply_msg.sticker.file_name.endswith(".tgs")
                or reply_msg.sticker.file_name.endswith(".webm")
            ):
                resize = True
        elif (
            reply_msg.photo
            or reply_msg.document
            and "image" in reply_msg.document.mime_type
        ):
            resize = True
        elif reply_msg.document and "tgsticker" in reply_msg.document.mime_type:
            animation = True
        elif reply_msg.animation or (
            reply_msg.document
            and "video" in reply_msg.document.mime_type
            and reply_msg.document.file_size <= MAX_VIDEO_SIZE
        ):
            resize = True
            video = True

        for arg in ctx.args:
            if util.text.has_emoji(arg):
                # Allow for emoji split across several arguments, since some clients
                # automatically insert spaces
                emoji = arg
            else:
                pack_VOL = int(arg)

        if not emoji:
            emoji = "❓"

        prefix = self.bot.user.username or f"u{self.bot.user.id}"
        if not prefix[0].isalpha():
            prefix = f"k_{prefix}"

        if self.bot.user.username:
            set_title_base = f"@{self.bot.user.username}'s Kang Set"
        else:
            set_title_base = f"{self.bot.user.id}'s Kang Set"

        set_name = f"{prefix}_kangPack_VOL{pack_VOL}"
        set_title = f"{set_title_base} VOL.{pack_VOL}"

        if animation:
            set_name += "_animation"
            set_title += " (Animation)"
        if video:
            set_name += "_video"
            set_title += " (Video)"

        while True:
            sticker: StickerSet
            try:
                sticker = await self.bot.client.invoke(
                    GetStickerSet(
                        stickerset=InputStickerSetShortName(short_name=set_name), hash=0  # type: ignore
                    )
                )
            except StickersetInvalid:
                sticker = None  # type: ignore
                break
            else:
                lim = 120 if not (animation or video) else 50
                if sticker.set.count >= lim:  # type: ignore
                    pack_VOL += 1
                    set_name = f"{prefix}_kangPack_VOL{pack_VOL}"
                    set_title = f"{set_title_base} VOL.{pack_VOL}"

                    if animation:
                        set_name += "_animation"
                        set_title += " (Animated)"
                    if video:
                        set_name += "_video"
                        set_title += " (Video)"

                    await ctx.respond(
                        f"Pack VOL {pack_VOL} is full, switching to next VOL..."
                    )
                    continue

                break

        input_doc = None
        media = None

        if reply_msg.sticker and not resize and reply_msg.sticker.file_id:
            try:
                decoded = FileId.decode(reply_msg.sticker.file_id)
                input_doc = raw.types.InputDocument(
                    id=decoded.media_id,
                    access_hash=decoded.access_hash,
                    file_reference=decoded.file_reference,
                )
            except Exception as e:
                self.log.warning(f"Failed to decode sticker file_id: {e}")
                input_doc = None

        if not input_doc:
            media_path = await reply_msg.download()
            if not media_path:
                return "__Failed to download media.__"

            media = AsyncPath(media_path)
            if resize:
                try:
                    media = await resize_media(media, video)
                except FileNotFoundError:
                    return (
                        "❌ [FFmpeg](https://github.com/FFmpeg/FFmpeg) "
                        "must be installed on the host system.\n\n"
                        "If you're running this bot on Heroku, "
                        "you can install FFmpeg by adding this buildpack:\n"
                        "[FFmpeg](https://github.com/jonathanong/heroku-buildpack-ffmpeg-latest)"
                    )
                else:
                    if not await media.exists():
                        return "__Failed to resize media.__"

            try:
                input_doc = await self.upload_sticker_media(
                    media,
                    animation=animation,
                    video=video,
                    emoji=emoji,
                )
            except Exception as e:
                self.log.warning(f"Direct MTProto upload failed: {e}")
                input_doc = None

        status = False
        result = ""

        if input_doc:
            if not sticker:
                await ctx.respond("Creating sticker pack...")
                status, result = await self.create_pack_mtproto(
                    input_doc, set_name, set_title, emoji=emoji
                )
            else:
                await ctx.respond("Copying sticker...")
                status, result = await self.add_sticker_mtproto(
                    input_doc, set_name, emoji=emoji
                )

        if not status:
            if not media:
                media_path = await reply_msg.download()
                if not media_path:
                    return "__Failed to download media.__"
                media = AsyncPath(media_path)
                if resize:
                    media = await resize_media(media, video)

            sticker_bytes = await media.read_bytes()
            sticker_buf = io.BytesIO(sticker_bytes)
            sticker_buf.name = media.name

            if not sticker:
                await ctx.respond("Creating sticker pack via @Stickers...")
                status, result = await self.create_pack(
                    sticker_buf,
                    set_name,
                    set_title,
                    emoji=emoji,
                    sticker_type="animated"
                    if animation
                    else "video"
                    if video
                    else "static",
                )
            else:
                await ctx.respond("Copying sticker via @Stickers...")
                status, result = await self.add_sticker(
                    sticker_buf, set_name, emoji=emoji
                )

        if media and await media.exists():
            await media.unlink()

        if status:
            await self.bot.log_stat("stickers_created")
            return f"[Sticker copied]({result})."

        return result
