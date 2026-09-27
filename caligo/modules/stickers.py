import asyncio
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, ClassVar, Optional, Tuple, Union

import pyrogram
from anyio import Path as AsyncPath
from PIL import Image
from pyrogram import raw, utils
from pyrogram.errors import StickersetInvalid
from pyrogram.file_id import FileType
from pyrogram.raw.functions.messages.get_sticker_set import GetStickerSet
from pyrogram.raw.types.input_sticker_set_short_name import InputStickerSetShortName
from pyrogram.raw.types.sticker_set import StickerSet

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


class InputSticker:
    """A sticker to be added to a sticker set."""

    def __init__(
        self,
        sticker: Union[str, AsyncPath, BinaryIO],
        format: str = "static",
        emoji_list: Optional[list[str]] = None,
    ) -> None:
        self.sticker = sticker
        self.format = format
        self.emoji_list = emoji_list or ["❓"]

    async def write(
        self,
        client: pyrogram.Client,
        chat_id: Union[int, str, None] = None,
    ) -> raw.types.InputStickerSetItem:
        if chat_id is None:
            peer = raw.types.InputPeerSelf()
        else:
            peer = await client.resolve_peer(chat_id)

        file_name = "sticker.png"
        mime_type = "image/png"

        if self.format == "animated":
            file_name = "sticker.tgs"
            mime_type = "application/x-tgsticker"
        elif self.format == "video":
            file_name = "sticker.webm"
            mime_type = "video/webm"

        alt = "".join(self.emoji_list)

        # Check if local file or in-memory BytesIO
        if isinstance(self.sticker, (io.BytesIO, bytes)) or (
            isinstance(self.sticker, (str, Path, AsyncPath))
            and await AsyncPath(str(self.sticker)).is_file()
        ):
            uploaded_media = await client.invoke(
                raw.functions.messages.UploadMedia(
                    peer=peer,
                    media=raw.types.InputMediaUploadedDocument(
                        mime_type=mime_type,
                        file=await client.save_file(str(self.sticker)),
                        attributes=[
                            raw.types.DocumentAttributeFilename(
                                file_name=file_name,
                            ),
                            raw.types.DocumentAttributeSticker(
                                alt=alt,
                                stickerset=raw.types.InputStickerSetEmpty(),
                            ),
                        ],
                    ),
                ),
            )

            return raw.types.InputStickerSetItem(
                document=raw.types.InputDocument(
                    id=uploaded_media.document.id,
                    access_hash=uploaded_media.document.access_hash,
                    file_reference=uploaded_media.document.file_reference,
                ),
                emoji=alt,
            )

        # If it's a file_id string of an existing sticker
        return raw.types.InputStickerSetItem(
            document=utils.get_input_media_from_file_id(
                str(self.sticker), FileType.STICKER
            ).id,
            emoji=alt,
        )


class Sticker(module.Module):
    name: ClassVar[str] = "Sticker"

    db: database.AsyncCollection

    async def on_load(self):
        # to use later maybe
        self.db = self.bot.db.get_collection(self.name.upper())

        if not await AsyncPath(CACHE_PATH).exists():
            await AsyncPath(CACHE_PATH).mkdir(parents=True)

    async def create_new_sticker_set(
        self,
        name: str,
        title: str,
        stickers: list[InputSticker],
        user_id: Union[int, str] = "me",
    ) -> Tuple[bool, str]:
        try:
            items = [
                await s.write(client=self.bot.client, chat_id=user_id)
                for s in stickers
            ]
            await self.bot.client.invoke(
                raw.functions.stickers.CreateStickerSet(
                    user_id=await self.bot.client.resolve_peer(user_id),
                    title=title,
                    short_name=name,
                    stickers=items,
                )
            )
            return True, f"https://t.me/addstickers/{name}"
        except Exception as e:
            self.log.warning(f"Direct MTProto CreateStickerSet failed: {e}")
            return False, str(e)

    async def add_sticker_to_set(
        self,
        name: str,
        sticker: InputSticker,
        sticker_set: Optional[StickerSet] = None,
        user_id: Union[int, str] = "me",
    ) -> Tuple[bool, str]:
        try:
            item = await sticker.write(client=self.bot.client, chat_id=user_id)
            if sticker_set and hasattr(sticker_set, "set"):
                stickerset = raw.types.InputStickerSetID(
                    id=sticker_set.set.id,
                    access_hash=sticker_set.set.access_hash,
                )
            else:
                stickerset = raw.types.InputStickerSetShortName(short_name=name)

            await self.bot.client.invoke(
                raw.functions.stickers.AddStickerToSet(
                    stickerset=stickerset,
                    sticker=item,
                )
            )
            return True, f"https://t.me/addstickers/{name}"
        except Exception as e:
            self.log.warning(f"Direct MTProto AddStickerToSet failed: {e}")
            return False, str(e)

    @command.desc("Copy a sticker into another pack")
    @command.alias("stickercopy", "kang")
    @command.usage("[sticker pack VOL number? if not set] [emoji?]", optional=True)
    async def cmd_copysticker(self, ctx: command.Context) -> str:
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

            base = f"k_{owner_prefix}_pack{vol}"
            if animation:
                base += "_anim"
            elif video:
                base += "_vid"
            name = re.sub(r"_+", "_", base)[:64]
            return name, title

        set_name, set_title = build_set_info(pack_VOL)
        sticker_set = None

        lim = 120 if not (animation or video) else 50
        while True:
            try:
                sticker_set = await self.bot.client.invoke(
                    GetStickerSet(
                        stickerset=InputStickerSetShortName(short_name=set_name),
                        hash=0,
                    )
                )
            except StickersetInvalid:
                sticker_set = None
                break
            else:
                if sticker_set.set.count >= lim:
                    pack_VOL += 1
                    set_name, set_title = build_set_info(pack_VOL)
                    await ctx.respond(
                        f"Pack VOL {pack_VOL} is full, switching to next VOL..."
                    )
                    continue
                break

        media_to_delete = None
        if reply_msg.sticker and not resize and reply_msg.sticker.file_id:
            input_sticker = InputSticker(
                sticker=reply_msg.sticker.file_id,
                format=sticker_format,
                emoji_list=[emoji],
            )
        else:
            media_path = await reply_msg.download()
            if not media_path:
                return "__Failed to download media.__"

            media = AsyncPath(media_path)
            media_to_delete = media
            if resize:
                try:
                    media = await resize_media(media, video)
                    media_to_delete = media
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

            input_sticker = InputSticker(
                sticker=str(media),
                format=sticker_format,
                emoji_list=[emoji],
            )

        try:
            if not sticker_set:
                await ctx.respond("Creating sticker pack...")
                status, result = await self.create_new_sticker_set(
                    name=set_name,
                    title=set_title,
                    stickers=[input_sticker],
                    user_id="me",
                )
            else:
                await ctx.respond("Copying sticker...")
                status, result = await self.add_sticker_to_set(
                    name=set_name,
                    sticker=input_sticker,
                    sticker_set=sticker_set,
                    user_id="me",
                )
        except Exception as e:
            status = False
            result = f"Sticker operation failed: {e}"
        finally:
            if media_to_delete and await media_to_delete.exists():
                await media_to_delete.unlink()

        if status:
            await self.bot.log_stat("stickers_created")
            return f"[Sticker copied]({result})."

        return f"Failed: {result}"
