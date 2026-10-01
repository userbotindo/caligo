import asyncio
import mimetypes
import os
from datetime import datetime, timedelta
from typing import Any, Callable, Optional, Sequence, Union

from pyrogram import types
from pyrogram.types import (
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
)

from . import misc, time

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


async def report_progress(
    current: int,
    total: int,
    start_time: int,
    mode: str,
    ctx: Any,
    file_name: str,
    style: str = DEFAULT_PROGRESS_STYLE,
) -> None:
    """Dispatches live upload/download progress updates."""
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

    last_update = getattr(ctx, "last_update_time", None)
    if (
        last_update is None
        or not isinstance(last_update, datetime)
        or (now - last_update).total_seconds() >= 5
    ):
        await ctx.respond(progress)
        ctx.last_update_time = now


prog_func = report_progress


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
        await report_progress(
            current=current,
            total=total,
            start_time=start_time,
            mode=mode,
            ctx=ctx,
            file_name=file_name,
            style=active_style,
        )

    return _callback
