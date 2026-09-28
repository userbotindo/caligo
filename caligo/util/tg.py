import io
import mimetypes
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Optional, Sequence, Union

import bprint
import pyrogram

from . import misc, time
from pyrogram.types import (
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
)

MESSAGE_CHAR_LIMIT = 4096
TRUNCATION_SUFFIX = "... (truncated)"

SKIP_ATTR_NAMES = (
    "CONSTRUCTOR_ID",
    "SUBCLASS_OF_ID",
    "access_hash",
    "message",
    "raw_text",
    "phone",
)
SKIP_ATTR_VALUES = (False,)
SKIP_ATTR_TYPES = ()


def mention_user(user: pyrogram.types.User) -> str:
    """Returns a string that mentions the given user, regardless of whether they have a username."""

    if user.username:
        # Use username mention if possible
        name = f"@{user.username}"
    else:
        # Use the first and last name otherwise
        if user.first_name and user.last_name:
            name = user.first_name + " " + user.last_name
        elif user.first_name and not user.last_name:
            name = user.first_name
        else:
            # Deleted accounts have no name; behave like the official clients
            name = "Deleted Account"

    return f"[{name}](tg://user?id={user.id})"


def filter_code_block(inp: str) -> str:
    """Returns the content inside the given Markdown code block or inline code."""

    if inp.startswith("```") and inp.endswith("```"):
        inp = inp[3:][:-3]
    elif inp.startswith("`") and inp.endswith("`"):
        inp = inp[1:][:-1]

    return inp


def _bprint_skip_predicate(name: str, value: Any) -> bool:
    return (
        name.startswith("_")
        or value is None
        or callable(value)
        or name in SKIP_ATTR_NAMES
        or value in SKIP_ATTR_VALUES
        or type(value) in SKIP_ATTR_TYPES
    )


def pretty_print_entity(entity: Any) -> str:
    """Pretty-prints the given Telegram entity with recursive details."""

    return bprint.bprint(entity, stream=str, skip_predicate=_bprint_skip_predicate)


def truncate(text: str) -> str:
    """Truncates the given text to fit in one Telegram message."""
    suffix = TRUNCATION_SUFFIX
    if text.endswith("```"):
        suffix += "```"

    if len(text) > MESSAGE_CHAR_LIMIT:
        return text[: MESSAGE_CHAR_LIMIT - len(suffix)] + suffix

    return text


async def send_as_document(
    content: str, msg: pyrogram.types.Message, caption: str
) -> pyrogram.types.Message:
    with io.BytesIO(str.encode(content)) as o:
        o.name = str(uuid.uuid4()).split("-")[0].upper() + ".TXT"
        return await msg.reply_document(
            document=o,
            caption="❯ ```" + caption + "```",
        )


async def unpack_inline_id(bot_uid: int, inline_id: str) -> tuple[int, int]:
    """Unpacks a Telegram inline message ID into (chat_id, message_id)."""
    unpacked = pyrogram.utils.unpack_inline_message_id(inline_id)

    match unpacked:
        case pyrogram.raw.types.InputBotInlineMessageID64(
            owner_id=owner_id, id=message_id
        ):
            pass
        case pyrogram.raw.types.InputBotInlineMessageID(id=combined_id):
            owner_id = (combined_id >> 32) & 0xFFFFFFFF
            message_id = combined_id & 0xFFFFFFFF

            if owner_id > 0x7FFFFFFF:
                owner_id -= 0x100000000
            if message_id > 0x7FFFFFFF:
                message_id -= 0x100000000
        case _:
            raise TypeError(f"Unexpected unpacked type: {type(unpacked)}")

    if owner_id == bot_uid:
        chat_id = owner_id
    else:
        chat_id = pyrogram.utils.get_channel_id(abs(owner_id))

    return chat_id, message_id


PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".wmv", ".3gp", ".m4v"}
AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wma"}
STICKER_EXTS = {".tgs"}


def get_media_type(path: str) -> str:
    """Determines media type ('photo', 'video', 'audio', 'sticker', 'document') from file path."""
    ext = os.path.splitext(path)[1].lower()
    if ext in STICKER_EXTS:
        return "sticker"
    if ext in PHOTO_EXTS:
        return "photo"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"

    mime, _ = mimetypes.guess_type(path)
    if mime:
        if mime in ("application/x-tgsticker", "image/tgs"):
            return "sticker"
        if mime.startswith("image/") and ext != ".gif":
            return "photo"
        if mime.startswith("video/") or ext == ".gif":
            return "video"
        if mime.startswith("audio/"):
            return "audio"

    return "document"


async def send_media(
    client: Any,
    chat_id: Union[int, str],
    file_path: str,
    media_type: Optional[str] = None,
    *,
    caption: Optional[str] = None,
    message_thread_id: Optional[int] = None,
    progress: Optional[Callable] = None,
    progress_args: tuple = (),
) -> Any:
    """Sends a single media file using the appropriate Pyrogram method with fallback."""
    if media_type is None:
        media_type = get_media_type(file_path)

    file_name = os.path.basename(file_path)
    if caption is None:
        caption = file_name

    prog_kwargs: dict[str, Any] = {}
    if progress:
        prog_kwargs["progress"] = progress
        prog_kwargs["progress_args"] = progress_args

    thread_kwargs: dict[str, Any] = {}
    if message_thread_id is not None:
        thread_kwargs["message_thread_id"] = message_thread_id

    if media_type == "photo":
        try:
            return await client.send_photo(
                chat_id,
                photo=file_path,
                caption=caption,
                **thread_kwargs,
                **prog_kwargs,
            )
        except Exception:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".webp":
                try:
                    return await client.send_sticker(
                        chat_id,
                        sticker=file_path,
                        **thread_kwargs,
                        **prog_kwargs,
                    )
                except Exception:
                    pass

            return await client.send_document(
                chat_id,
                document=file_path,
                caption=caption,
                force_document=True,
                **thread_kwargs,
                **prog_kwargs,
            )
    elif media_type == "sticker":
        try:
            return await client.send_sticker(
                chat_id,
                sticker=file_path,
                **thread_kwargs,
                **prog_kwargs,
            )
        except Exception:
            return await client.send_document(
                chat_id,
                document=file_path,
                caption=caption,
                force_document=True,
                **thread_kwargs,
                **prog_kwargs,
            )
    elif media_type == "video":
        try:
            return await client.send_video(
                chat_id,
                video=file_path,
                caption=caption,
                supports_streaming=True,
                **thread_kwargs,
                **prog_kwargs,
            )
        except Exception:
            return await client.send_document(
                chat_id,
                document=file_path,
                caption=caption,
                force_document=True,
                **thread_kwargs,
                **prog_kwargs,
            )
    elif media_type == "audio":
        try:
            title = os.path.splitext(file_name)[0]
            return await client.send_audio(
                chat_id,
                audio=file_path,
                caption=caption,
                title=title,
                **thread_kwargs,
                **prog_kwargs,
            )
        except Exception:
            return await client.send_document(
                chat_id,
                document=file_path,
                caption=caption,
                force_document=True,
                **thread_kwargs,
                **prog_kwargs,
            )
    else:
        return await client.send_document(
            chat_id,
            document=file_path,
            caption=caption,
            force_document=True,
            **thread_kwargs,
            **prog_kwargs,
        )


def build_media_group(
    files: Sequence[str],
    group_type: Optional[str] = None,
) -> list[Union[InputMediaPhoto, InputMediaVideo, InputMediaAudio, InputMediaDocument]]:
    """Builds a list of Pyrogram InputMedia items for album sending."""
    media_group: list[
        Union[InputMediaPhoto, InputMediaVideo, InputMediaAudio, InputMediaDocument]
    ] = []

    for file_path in files:
        fname = os.path.basename(file_path)
        m_type = group_type or get_media_type(file_path)

        if m_type == "photo":
            media_group.append(InputMediaPhoto(file_path, caption=fname))
        elif m_type == "video":
            media_group.append(
                InputMediaVideo(file_path, caption=fname, supports_streaming=True)
            )
        elif m_type == "audio":
            title = os.path.splitext(fname)[0]
            media_group.append(
                InputMediaAudio(file_path, caption=fname, title=title)
            )
        else:
            media_group.append(InputMediaDocument(file_path, caption=fname))

    return media_group


PROGRESS_STYLES: dict[str, tuple[str, str]] = {
    "bullet": ("●", "○"),  # Default Caligo bullet style
    "block": ("█", "░"),  # Solid blocks
    "square": ("■", "□"),  # Solid / hollow squares
    "circle": ("⬤", "◯"),  # Large filled / hollow circles
    "stripes": ("▰", "▱"),  # Modern angled stripes
    "arrow": ("►", "▻"),  # Pointer arrows
    "dots": ("⬢", "⬡"),  # Hexagons
}
DEFAULT_PROGRESS_STYLE = "bullet"


def render_progress_bar(
    percent: float,
    length: int = 10,
    style: str = DEFAULT_PROGRESS_STYLE,
) -> str:
    """Renders a progress bar string with the specified style."""
    chars = PROGRESS_STYLES.get(style)
    if chars is None:
        chars = PROGRESS_STYLES.get(
            style.lower(), PROGRESS_STYLES[DEFAULT_PROGRESS_STYLE]
        )
    filled_count = min(length, max(0, int(round(percent * length))))
    return chars[0] * filled_count + chars[1] * (length - filled_count)


def format_progress(
    file_name: str,
    status: str,
    percent: float,
    current: int,
    total: int,
    speed: float,
    eta: timedelta,
    style: str = DEFAULT_PROGRESS_STYLE,
) -> str:
    """Formats the progress message text for Telegram."""
    bar = render_progress_bar(percent, length=10, style=style)
    pct_text = f"{round(percent * 100)}%"
    return (
        f"`{file_name}`\n"
        f"Status: **{status}**\n"
        f"Progress: [{bar}] {pct_text}\n"
        f"__{misc.human_readable_bytes(current)} of {misc.human_readable_bytes(total)} @ "
        f"{misc.human_readable_bytes(speed, postfix='/s')}\n"
        f"ETA: {time.format_duration_td(eta)}__\n\n"
    )


async def prog_func(
    current: int,
    total: int,
    start_time: int,
    mode: str,
    ctx: Any,
    file_name: str,
    style: str = DEFAULT_PROGRESS_STYLE,
) -> None:
    """Live progress callback function for Telegram upload/download."""
    if total <= 0:
        return

    percent = current / total
    end_time = time.sec() - start_time
    now = datetime.now()

    try:
        speed = round(current / end_time, 2)
        eta = timedelta(seconds=int(round((total - current) / speed)))
    except ZeroDivisionError:
        speed = 0.0
        eta = timedelta(seconds=0)

    status = "Uploading" if mode == "upload" else "Downloading"
    progress = format_progress(
        file_name=file_name,
        status=status,
        percent=percent,
        current=current,
        total=total,
        speed=speed,
        eta=eta,
        style=style,
    )

    # Only edit message once every 5 seconds to avoid ratelimits
    if (
        ctx.last_update_time is None
        or (now - ctx.last_update_time).total_seconds() >= 5
    ):
        await ctx.respond(progress)
        ctx.last_update_time = now


def create_progress_callback(
    ctx: Any,
    start_time: int,
    mode: str,
    file_name: str,
    style: Optional[str] = None,
) -> Callable[[int, int], Any]:
    """Returns a progress callback closure with bound arguments."""
    active_style = (
        style
        or getattr(getattr(ctx, "bot", None), "progress_style", None)
        or DEFAULT_PROGRESS_STYLE
    )

    async def _callback(current: int, total: int, *args: Any) -> None:
        await prog_func(
            current=current,
            total=total,
            start_time=start_time,
            mode=mode,
            ctx=ctx,
            file_name=file_name,
            style=active_style,
        )

    return _callback
