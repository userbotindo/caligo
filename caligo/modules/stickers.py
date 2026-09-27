import asyncio
import io
import json
import re
from datetime import datetime
from typing import BinaryIO, ClassVar, Optional, Tuple, Union

import aiohttp
from anyio import Path as AsyncPath
from PIL import Image

from caligo import command, module, util
from caligo.core import database

MAX_VIDEO_SIZE = 10485760
MAX_SIZE = 512
CACHE_PATH = "caligo/.cache/stickers"


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

    @property
    def helper_token(self) -> Optional[str]:
        if not getattr(self.bot, "helper_initialized", False):
            return None
        return self.bot.config.get("telegram", {}).get("helper", {}).get("token")

    async def upload_sticker_file_botapi(
        self,
        media: AsyncPath,
        sticker_format: str = "static",
    ) -> str:
        token = self.helper_token
        if not token:
            raise ValueError("Helper bot is not initialized")

        url = f"https://api.telegram.org/bot{token}/uploadStickerFile"
        data = aiohttp.FormData()
        data.add_field("user_id", str(self.bot.uid))
        data.add_field("sticker_format", sticker_format)

        content_type = (
            "video/webm"
            if sticker_format == "video"
            else "application/x-tgsticker"
            if sticker_format == "animated"
            else "image/png"
        )
        file_bytes = await media.read_bytes()
        data.add_field(
            "sticker",
            file_bytes,
            filename=media.name,
            content_type=content_type,
        )

        async with self.bot.http.post(url, data=data) as resp:
            res = await resp.json()
            if not res.get("ok"):
                raise ValueError(res.get("description", "Failed to upload sticker file"))
            return res["result"]["file_id"]

    async def get_sticker_set_botapi(self, name: str) -> Optional[dict]:
        token = self.helper_token
        if not token:
            return None
        url = f"https://api.telegram.org/bot{token}/getStickerSet"
        async with self.bot.http.get(url, params={"name": name}) as resp:
            data = await resp.json()
            if data.get("ok"):
                return data.get("result")
            return None

    async def create_pack_botapi(
        self,
        set_name: str,
        set_title: str,
        file_id: str,
        emoji: str,
        sticker_format: str = "static",
    ) -> Tuple[bool, str]:
        token = self.helper_token
        if not token:
            return False, "Helper bot is not initialized"

        url = f"https://api.telegram.org/bot{token}/createNewStickerSet"
        payload = {
            "user_id": str(self.bot.uid),
            "name": set_name,
            "title": set_title,
            "stickers": json.dumps(
                [
                    {
                        "sticker": file_id,
                        "format": sticker_format,
                        "emoji_list": [emoji],
                    }
                ]
            ),
        }
        async with self.bot.http.post(url, data=payload) as resp:
            res = await resp.json()
            if res.get("ok"):
                return True, f"https://t.me/addstickers/{set_name}"
            return False, res.get("description", "Failed to create sticker pack")

    async def add_sticker_botapi(
        self,
        set_name: str,
        file_id: str,
        emoji: str,
        sticker_format: str = "static",
    ) -> Tuple[bool, str]:
        token = self.helper_token
        if not token:
            return False, "Helper bot is not initialized"

        url = f"https://api.telegram.org/bot{token}/addStickerToSet"
        payload = {
            "user_id": str(self.bot.uid),
            "name": set_name,
            "sticker": json.dumps(
                {
                    "sticker": file_id,
                    "format": sticker_format,
                    "emoji_list": [emoji],
                }
            ),
        }
        async with self.bot.http.post(url, data=payload) as resp:
            res = await resp.json()
            if res.get("ok"):
                return True, f"https://t.me/addstickers/{set_name}"
            return False, res.get("description", "Failed to add sticker to pack")

    @command.desc("Copy a sticker into another pack")
    @command.alias("stickercopy", "kang")
    @command.usage("[sticker pack VOL number? if not set] [emoji?]", optional=True)
    async def cmd_copysticker(self, ctx: command.Context) -> str:
        if not self.helper_token or not getattr(self.bot, "bot_user", None):
            return "__Helper bot is not initialized. Kang requires a helper bot token.__"

        reply_msg = ctx.msg.reply_to_message
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
                emoji = arg
            else:
                pack_VOL = int(arg)

        if not emoji:
            emoji = "❓"

        sticker_format = "animated" if animation else "video" if video else "static"
        bot_username = self.bot.bot_user.username

        owner_prefix = self.bot.user.username or f"u{self.bot.uid}"
        if not owner_prefix[0].isalpha():
            owner_prefix = f"k_{owner_prefix}"
        owner_prefix = re.sub(r"_+", "_", owner_prefix)

        if self.bot.user.username:
            set_title_base = f"@{self.bot.user.username}'s Kang Set"
        else:
            set_title_base = f"{self.bot.uid}'s Kang Set"

        def build_set_info(vol: int) -> Tuple[str, str]:
            title = f"{set_title_base} VOL.{vol}"
            if animation:
                title += " (Animation)"
            elif video:
                title += " (Video)"

            suffix = f"_by_{bot_username}"
            base = f"{owner_prefix}_kang_v{vol}"
            if animation:
                base += "_anim"
            elif video:
                base += "_vid"
            base = re.sub(r"_+", "_", base)[: 64 - len(suffix)]
            name = f"{base}{suffix}"
            return name, title

        set_name, set_title = build_set_info(pack_VOL)
        pack_exists = False

        lim = 120 if not (animation or video) else 50
        while True:
            sticker_set = await self.get_sticker_set_botapi(set_name)
            if sticker_set:
                pack_exists = True
                count = len(sticker_set.get("stickers", []))
                if count >= lim:
                    pack_VOL += 1
                    set_name, set_title = build_set_info(pack_VOL)
                    await ctx.respond(
                        f"Pack VOL {pack_VOL} is full, switching to next VOL..."
                    )
                    continue
            else:
                pack_exists = False
            break

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
            file_id = await self.upload_sticker_file_botapi(
                media, sticker_format=sticker_format
            )
            if not pack_exists:
                await ctx.respond("Creating sticker pack...")
                status, result = await self.create_pack_botapi(
                    set_name,
                    set_title,
                    file_id,
                    emoji=emoji,
                    sticker_format=sticker_format,
                )
            else:
                await ctx.respond("Copying sticker...")
                status, result = await self.add_sticker_botapi(
                    set_name,
                    file_id,
                    emoji=emoji,
                    sticker_format=sticker_format,
                )
        except Exception as e:
            status = False
            result = f"Sticker upload failed: {e}"
        finally:
            if await media.exists():
                await media.unlink()

        if status:
            await self.bot.log_stat("stickers_created")
            return f"[Sticker copied]({result})."

        return f"Failed: {result}"
