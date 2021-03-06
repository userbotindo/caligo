import io
import os
import uuid
from typing import Any, Optional, Tuple, Type, Union

import aiofile
import bprint
import pyrogram

from .. import command

MESSAGE_CHAR_LIMIT = 4096
TRUNCATION_SUFFIX = "... (truncated)"


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
    )


def pretty_print_entity(entity) -> str:
    """Pretty-prints the given Telegram entity with recursive details."""

    return bprint.bprint(entity, stream=str, skip_predicate=_bprint_skip_predicate)


async def download_file(
    dest: Union[pyrogram.types.Document, os.PathLike, Type[bytes]] = bytes
) -> Any:
    """Downloads the file embedded in the given message."""
    path = await dest.download()
    async with aiofile.async_open(path, "r") as file:
        text = await file.read()

    os.remove(path)
    return text


def truncate(text: str) -> str:
    """Truncates the given text to fit in one Telegram message."""
    suffix = TRUNCATION_SUFFIX
    if text.endswith("```"):
        suffix += "```"

    if len(text) > MESSAGE_CHAR_LIMIT:
        return text[: MESSAGE_CHAR_LIMIT - len(suffix)] + suffix

    return text


async def send_as_document(
    content: Union[bytes, str],
    msg: pyrogram.types.Message,
    caption: str
) -> pyrogram.types.Message:
    with io.BytesIO(str.encode(content)) as o:
        o.name = str(uuid.uuid4()).split("-")[0].upper() + ".TXT"
        return await msg.reply_document(
            document=o,
            caption="❯ ```" + caption + "```",
        )


async def get_text_input(
    ctx: command.Context, input_arg: Optional[str]
) -> Tuple[bool, Optional[Union[str, bytes]]]:
    """Returns input text from various sources in the given command context."""

    if ctx.msg.document:
        text = await download_file(ctx.msg)
    elif input_arg:
        text = filter_code_block(input_arg)
    elif ctx.msg.reply_to_message:
        reply_msg = ctx.msg.reply_to_message

        if reply_msg.document:
            text = await download_file(reply_msg)
        elif reply_msg.text:
            text = filter_code_block(reply_msg.text)
        else:
            return (
                False,
                "__Reply to a message with text or a text file, or provide text in command.__",
            )
    else:
        return False, "__Reply to a message or provide text in command.__"

    return True, text
