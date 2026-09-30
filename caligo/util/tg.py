import asyncio
import bisect
import html
import io
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Sequence, Tuple, Union
from urllib.parse import urlparse

import bprint
import pyrogram
from pyrogram import enums, errors, types
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import ChatPrivileges

from . import media, misc, time

MESSAGE_CHAR_LIMIT = 4096
TRUNCATION_SUFFIX = "... (truncated)"

SKIP_ATTR_NAMES = frozenset(
    (
        "CONSTRUCTOR_ID",
        "SUBCLASS_OF_ID",
        "access_hash",
        "message",
        "raw_text",
        "phone",
    )
)


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


def mention_user_html(
    user: Union[pyrogram.types.User, pyrogram.types.Chat]
) -> str:
    """Returns an HTML string that mentions the given user or chat."""
    name = (
        getattr(user, "first_name", "")
        or getattr(user, "title", "")
        or str(user.id)
    )
    if getattr(user, "last_name", None):
        name += f" {user.last_name}"
    return f'<a href="tg://user?id={user.id}">{html.escape(name)}</a>'


def get_target_id(target: Union[pyrogram.types.User, int, str]) -> Union[int, str]:
    """Returns the integer or string user ID from a User object, int, or string."""
    if isinstance(target, pyrogram.types.User):
        return target.id
    return target


def clean_target(target: Union[int, str]) -> Union[int, str]:
    """Cleans up target identifiers (stripping t.me/ prefixes, @ mentions, and parsing digits to int)."""
    if isinstance(target, str):
        target = target.strip()
        if target.startswith("https://t.me/"):
            target = target[13:]
        elif target.startswith("http://t.me/"):
            target = target[12:]
        elif target.startswith("t.me/"):
            target = target[5:]
        if target.startswith("@"):
            target = target[1:]
        try:
            return int(target)
        except ValueError:
            return target
    return target


parse_target_entity = clean_target


def format_target(target: Union[pyrogram.types.User, int, str]) -> str:
    """Formats and mentions a target User, numeric ID, or username string."""
    if isinstance(target, pyrogram.types.User):
        return mention_user(target)
    if isinstance(target, int):
        return f"[{target}](tg://user?id={target})"
    return str(target)


def format_target_html(
    target: Union[pyrogram.types.User, pyrogram.types.Chat, int, str]
) -> str:
    """Formats target user or chat as an HTML mention, ID link, or bold text."""
    if isinstance(target, (pyrogram.types.User, pyrogram.types.Chat)):
        return mention_user_html(target)
    if isinstance(target, int):
        return f'<a href="tg://user?id={target}">{target}</a>'
    return f"<b>{html.escape(str(target))}</b>"


async def resolve_user(
    client: Any, target: Union[int, str, pyrogram.types.User]
) -> Union[pyrogram.types.User, int, str]:
    """Attempts to resolve a User object using the client, falling back to original target."""
    if isinstance(target, pyrogram.types.User) or client is None:
        return target

    try:
        return await client.get_users(target)
    except Exception:
        return target


async def extract_target_and_rest(
    source: Any,
    *,
    client: Optional[Any] = None,
    input_text: Optional[str] = None,
    args: Optional[Sequence[str]] = None,
) -> Tuple[Optional[Union[pyrogram.types.User, int, str]], Optional[str]]:
    """Extracts target user/entity (from reply, entity, or first argument) and the remaining text.

    `source` can be a `command.Context` or a `pyrogram.types.Message`.
    """
    if hasattr(source, "msg"):  # Context object
        msg = source.msg
        client = client or getattr(getattr(source, "bot", None), "client", None)
        if input_text is None:
            input_text = getattr(source, "input", None)
        if args is None:
            args = getattr(source, "args", None)
    else:
        msg = source

    # 1. From replied message
    if msg.reply_to_message:
        reply = msg.reply_to_message
        if reply.from_user:
            return reply.from_user, input_text.strip() if input_text else None
        if reply.sender_chat:
            return reply.sender_chat.id, input_text.strip() if input_text else None

    # 2. From message entities (text_mention)
    if msg.entities:
        for entity in msg.entities:
            if entity.user:
                return entity.user, input_text.strip() if input_text else None

    # 3. From arguments
    if args:
        user_arg = args[0]
        rest = " ".join(args[1:]).strip() if len(args) > 1 else None
        if user_arg.isdigit() or (user_arg.startswith("-") and user_arg[1:].isdigit()):
            target_raw: Union[int, str] = int(user_arg)
        else:
            target_raw = user_arg

        if client:
            resolved = await resolve_user(client, target_raw)
            return resolved, rest
        return target_raw, rest

    return None, None



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
        or value is False
        or callable(value)
        or name in SKIP_ATTR_NAMES
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


TG_MESSAGE_LINK_REGEX = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t(?:elegram)?\.(?:me|dog))/(?:c/(\d+)|b/([a-zA-Z0-9_]+)|([a-zA-Z0-9_]+))/(?:(\d+)/)?(\d+)(?:\?.*)?$"
)


def parse_telegram_message_link(url: str) -> Optional[Tuple[Union[int, str], int]]:
    """Parses a Telegram message link or deep link into (chat_id, message_id)."""
    clean_url = url.strip().strip("<>\"'")

    if clean_url.startswith("tg://"):
        parsed = urlparse(clean_url)
        if parsed.netloc == "resolve":
            params = dict(p.split("=", 1) for p in parsed.query.split("&") if "=" in p)
            if "domain" in params and "post" in params:
                return params["domain"], int(params["post"])
        elif parsed.netloc == "openmessage":
            params = dict(p.split("=", 1) for p in parsed.query.split("&") if "=" in p)
            if "chat_id" in params and "message_id" in params:
                cid = int(params["chat_id"])
                if cid > 0:
                    cid = int(f"-100{cid}")
                return cid, int(params["message_id"])

    match = TG_MESSAGE_LINK_REGEX.match(clean_url)
    if match:
        c_id, b_name, username, _, msg_id = match.groups()
        if c_id:
            chat_id: Union[int, str] = int(f"-100{c_id}")
        elif b_name:
            chat_id = b_name
        else:
            chat_id = username
        return chat_id, int(msg_id)

    return None


def get_message_link(
    chat: Union[pyrogram.types.Chat, int, str], message_id: int
) -> Optional[str]:
    """Generates a direct Telegram link to a message if chat metadata allows it."""
    username = getattr(chat, "username", None)
    chat_id = getattr(chat, "id", None) if hasattr(chat, "id") else None

    if username:
        return f"https://t.me/{username}/{message_id}"

    if chat_id is None:
        if isinstance(chat, str) and not chat.startswith("-") and not chat.isdigit():
            return f"https://t.me/{chat}/{message_id}"
        try:
            chat_id = int(chat)  # type: ignore
        except (ValueError, TypeError):
            return None

    chat_id_str = str(chat_id)
    if chat_id_str.startswith("-100"):
        internal_id = chat_id_str[4:]
        return f"https://t.me/c/{internal_id}/{message_id}"

    return None


def get_profile_link(
    user: Union[pyrogram.types.User, int, str]
) -> Optional[str]:
    """Generates a profile link (t.me/username or tg://user?id=...)."""
    username = getattr(user, "username", None)
    user_id = getattr(user, "id", None) if hasattr(user, "id") else None

    if username:
        return f"https://t.me/{username}"
    if user_id:
        return f"tg://user?id={user_id}"

    if isinstance(user, int):
        return f"tg://user?id={user}"
    if isinstance(user, str):
        if user.isdigit() or (user.startswith("-") and user[1:].isdigit()):
            return f"tg://user?id={user}"
        return f"https://t.me/{user.lstrip('@')}"

    return None


def get_chat_link(
    chat: Union[pyrogram.types.Chat, int, str]
) -> Optional[str]:
    """Generates a direct link to a chat or channel if possible."""
    username = getattr(chat, "username", None)
    invite_link = getattr(chat, "invite_link", None)
    chat_id = getattr(chat, "id", None) if hasattr(chat, "id") else None

    if username:
        return f"https://t.me/{username}"
    if invite_link:
        return invite_link

    if chat_id is None:
        if isinstance(chat, str) and not chat.startswith("-") and not chat.isdigit():
            return f"https://t.me/{chat.lstrip('@')}"
        try:
            chat_id = int(chat)  # type: ignore
        except (ValueError, TypeError):
            return None

    chat_id_str = str(chat_id)
    if chat_id_str.startswith("-100"):
        internal_id = chat_id_str[4:]
        return f"https://t.me/c/{internal_id}"

    return None


async def provision_helper(bot: Any, chat_id: int) -> bool:
    """Provisions helper bot presence and promotes administrator permissions in a group/channel."""
    if not getattr(bot, "helper_initialized", False):
        return False

    bot_uid = getattr(bot, "bot_uid", None)
    if not bot_uid:
        if getattr(bot, "bot_user", None):
            bot_uid = bot.bot_user.id
        elif getattr(getattr(bot, "client_helper", None), "me", None):
            bot_uid = bot.client_helper.me.id
        elif getattr(bot, "client_helper", None):
            try:
                bot_me = await bot.client_helper.get_me()
                bot_uid = bot_me.id
                bot.bot_uid = bot_uid
                bot.bot_user = bot_me
            except Exception:
                return False

    if not bot_uid or not getattr(bot, "client", None):
        return False

    try:
        chat = await bot.client.get_chat(chat_id)
    except Exception:
        return False

    if chat.type in (ChatType.PRIVATE, ChatType.BOT):
        return True

    # Check member status
    is_admin = False
    is_member = False
    try:
        member = await bot.client.get_chat_member(chat_id, bot_uid)
        if member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ):
            is_admin = True
            is_member = True
        elif member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.RESTRICTED,
        ):
            is_member = True
    except errors.UserNotParticipant:
        is_member = False
    except Exception:
        pass

    if chat.type == ChatType.CHANNEL:
        privileges = ChatPrivileges(
            can_manage_chat=True,
            can_post_messages=True,
            can_edit_messages=True,
            can_delete_messages=True,
            can_invite_users=True,
        )
        try:
            await bot.client.promote_chat_member(
                chat_id=chat_id,
                user_id=bot_uid,
                privileges=privileges,
            )
            return True
        except errors.FloodWait as e:
            await asyncio.sleep(e.value + 1)
            try:
                await bot.client.promote_chat_member(
                    chat_id=chat_id,
                    user_id=bot_uid,
                    privileges=privileges,
                )
                return True
            except Exception:
                return False
        except Exception:
            return False

    # For Groups / Supergroups: add as member first if not joined, then promote
    if not is_member:
        try:
            await bot.client.add_chat_members(chat_id, bot_uid)
            is_member = True
        except errors.UserAlreadyParticipant:
            is_member = True
        except errors.FloodWait as e:
            await asyncio.sleep(e.value + 1)
            try:
                await bot.client.add_chat_members(chat_id, bot_uid)
                is_member = True
            except Exception:
                pass
        except Exception:
            pass

    if not is_admin:
        privileges = ChatPrivileges(
            can_manage_chat=True,
            can_delete_messages=True,
            can_invite_users=True,
            can_pin_messages=True,
        )
        try:
            await bot.client.promote_chat_member(
                chat_id=chat_id,
                user_id=bot_uid,
                privileges=privileges,
            )
            return True
        except errors.FloodWait as e:
            await asyncio.sleep(e.value + 1)
            try:
                await bot.client.promote_chat_member(
                    chat_id=chat_id,
                    user_id=bot_uid,
                    privileges=privileges,
                )
                return True
            except Exception:
                return is_member
        except Exception:
            return is_member

    return True


# Media and progress utilities (re-exported from caligo.util.media)
PHOTO_EXTS = media.PHOTO_EXTS
VIDEO_EXTS = media.VIDEO_EXTS
AUDIO_EXTS = media.AUDIO_EXTS
STICKER_EXTS = media.STICKER_EXTS
get_media_type = media.get_media_type
send_media = media.send_media
build_media_group = media.build_media_group
PROGRESS_STYLES = media.PROGRESS_STYLES
DEFAULT_PROGRESS_STYLE = media.DEFAULT_PROGRESS_STYLE
render_progress_bar = media.render_progress_bar
format_progress = media.format_progress
report_progress = media.report_progress
prog_func = media.prog_func
create_progress_callback = media.create_progress_callback


TELEGRAM_DCS: dict[int, tuple[str, int, str]] = {
    1: ("149.154.175.53", 443, "Miami"),
    2: ("149.154.167.51", 443, "Amsterdam"),
    3: ("149.154.175.100", 443, "Miami"),
    4: ("149.154.167.91", 443, "Amsterdam"),
    5: ("91.108.56.130", 443, "Singapore"),
}

ID_REGISTRATION_CHECKPOINTS: list[tuple[int, datetime]] = [
    (0, datetime(2013, 8, 14)), (2768409, datetime(2013, 11, 1)), (7679610, datetime(2013, 12, 31)),
    (11538514, datetime(2014, 2, 1)), (15835244, datetime(2014, 2, 20)), (23646077, datetime(2014, 2, 26)),
    (38015510, datetime(2014, 3, 1)), (44634663, datetime(2014, 5, 6)), (46145305, datetime(2014, 5, 15)),
    (54845238, datetime(2014, 9, 20)), (63263518, datetime(2014, 10, 27)), (101260938, datetime(2015, 3, 6)),
    (112594714, datetime(2015, 8, 15)), (152079341, datetime(2016, 1, 22)), (225034354, datetime(2016, 6, 18)),
    (297621225, datetime(2016, 12, 16)), (390000000, datetime(2017, 6, 15)), (500000000, datetime(2017, 12, 30)),
    (600000000, datetime(2018, 5, 30)), (700000000, datetime(2018, 10, 31)), (800000000, datetime(2019, 3, 15)),
    (900000000, datetime(2019, 7, 20)), (1000000000, datetime(2019, 12, 15)), (1200000000, datetime(2020, 7, 15)),
    (1400000000, datetime(2021, 1, 10)), (1600000000, datetime(2021, 3, 20)), (1800000000, datetime(2021, 6, 15)),
    (2000000000, datetime(2021, 10, 30)), (5000000000, datetime(2022, 1, 15)), (5300000000, datetime(2022, 5, 1)),
    (5600000000, datetime(2022, 9, 1)), (5900000000, datetime(2023, 1, 1)), (6300000000, datetime(2023, 6, 1)),
    (6700000000, datetime(2023, 11, 1)), (7000000000, datetime(2024, 3, 1)), (7300000000, datetime(2024, 7, 1)),
    (7600000000, datetime(2024, 11, 1)), (7900000000, datetime(2025, 3, 1)), (8200000000, datetime(2025, 7, 1)),
    (8500000000, datetime(2025, 11, 1)), (8800000000, datetime(2026, 3, 1)), (9200000000, datetime(2026, 9, 1)),
]


def estimate_creation_date(user_or_chat_id: int) -> Optional[str]:
    """Estimates the creation/registration date of a Telegram entity ID based on historical checkpoints."""
    raw_id = abs(int(user_or_chat_id))
    if str(raw_id).startswith("100") and len(str(raw_id)) > 3:
        try:
            raw_id = int(str(raw_id)[3:])
        except ValueError:
            pass

    if raw_id <= 0:
        return None

    ids = [cp[0] for cp in ID_REGISTRATION_CHECKPOINTS]
    idx = bisect.bisect_left(ids, raw_id)
    if idx == 0:
        return ID_REGISTRATION_CHECKPOINTS[0][1].strftime("~%B %Y")
    if idx >= len(ID_REGISTRATION_CHECKPOINTS):
        id1, d1 = ID_REGISTRATION_CHECKPOINTS[-2]
        id2, d2 = ID_REGISTRATION_CHECKPOINTS[-1]
    else:
        id1, d1 = ID_REGISTRATION_CHECKPOINTS[idx - 1]
        id2, d2 = ID_REGISTRATION_CHECKPOINTS[idx]

    denom = id2 - id1
    ratio = (raw_id - id1) / denom if denom != 0 else 0
    ts1 = d1.timestamp()
    ts2 = d2.timestamp()
    est_ts = ts1 + ratio * (ts2 - ts1)
    est_dt = datetime.fromtimestamp(est_ts, tz=timezone.utc)
    return est_dt.strftime("~%B %Y")


def clean_button_url(url: Optional[str]) -> Optional[str]:
    """Validates and normalizes URL for Telegram inline buttons."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if url.startswith("git+https://"):
        url = url[4:]
    elif url.startswith("git+http://"):
        url = url[4:]
    elif url.startswith("git://"):
        url = "https://" + url[6:]
    elif url.startswith("git@github.com:"):
        url = "https://github.com/" + url[15:]
    elif url.startswith("github.com/"):
        url = "https://" + url

    if not url.startswith(("http://", "https://", "tg://")):
        return None
    return url


clean_url = clean_button_url
