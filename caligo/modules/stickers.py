import asyncio
import io
import json
from datetime import datetime
from typing import BinaryIO, ClassVar, Tuple, Union

import pyrogram
from aiopath import AsyncPath
from PIL import Image
from pyrogram.errors import StickersetInvalid
from pyrogram.raw.functions.messages.get_sticker_set import GetStickerSet
from pyrogram.raw.types.input_sticker_set_short_name import InputStickerSetShortName
from pyrogram.raw.types.sticker_set import StickerSet

from caligo import command, module, util
from caligo.core import database

MAX_VIDEO_SIZE = 10485760
MAX_SIZE = 512
CACHE_PATH = "caligo/.cache/"

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

        resized_video = f"{CACHE_PATH}{media.stem}.webm"
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
            "scale={width}:{height},fps=30",
            resized_video,
            "-y",
        )
        await media.unlink()
        return AsyncPath(resized_video)

    image = Image.open(str(media))
    scale = MAX_SIZE / max(image.width, image.height)
    image = image.resize(
        (int(image.width * scale), int(image.height * scale)), Image.LANCZOS
    )

    resized_photo = f"{CACHE_PATH}sticker.png"
    image.save(resized_photo, "PNG")

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

    async def add_sticker(
        self,
        sticker_data: Union[pyrogram.types.Sticker, BinaryIO],
        set_name: str,
        emoji: str = "❓",
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

        async with self.bot.conversation(target) as conv:

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
        sticker_data: Union[pyrogram.types.Sticker, BinaryIO],
        set_name: str,
        set_title: str,
        emoji: str = "❓",
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
        emoji = ""
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

        media = await reply_msg.download()
        if not media:
            return "__Failed to download media.__"

        media = AsyncPath(media)
        if user.username:
            set_name = f"{self.bot.user.username}_kangPack_VOL{pack_VOL}"
            set_title = f"@{self.bot.user.username}'s Kang Set VOL.{pack_VOL}"
        else:
            set_name = f"{str(self.bot.user.id)}_kangPack_VOL{pack_VOL}"
            set_title = f"{str(self.bot.user.id)}'s Kang Set VOL.{pack_VOL}"

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
                    if self.bot.user.username:
                        set_name = f"{self.bot.user.username}_kangPack_VOL{pack_VOL}"
                        set_title = (
                            f"@{self.bot.user.username}'s Kang Set VOL.{pack_VOL}"
                        )
                    else:
                        set_name = f"{str(self.bot.user.id)}_kangPack_VOL{pack_VOL}"
                        set_title = f"{str(self.bot.user.id)}'s Kang Set VOL.{pack_VOL}"

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

        sticker_bytes = await media.read_bytes()
        sticker_buf = io.BytesIO(sticker_bytes)
        sticker_buf.seek(0)
        sticker_buf.name = media.name
        if not sticker:
            await ctx.respond("Creating sticker pack...")
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
            await ctx.respond("Copying sticker...")
            status, result = await self.add_sticker(sticker_buf, set_name, emoji=emoji)

        if status:
            await self.bot.log_stat("stickers_created")
            return f"[Sticker copied]({result})."

        return result
