import asyncio
import bisect
from datetime import datetime, timezone
import html
import re
import uuid
from typing import ClassVar, List, Optional, Tuple, Union

import pyrogram
from pyrogram import enums, errors, raw, types
from pyrogram.enums import ChatMembersFilter, ChatMemberStatus, ChatType, ParseMode

from caligo import command, listener, module, util

ID_REGISTRATION_CHECKPOINTS = [
    (0, datetime(2013, 8, 14)),
    (2768409, datetime(2013, 11, 1)),
    (7679610, datetime(2013, 12, 31)),
    (11538514, datetime(2014, 2, 1)),
    (15835244, datetime(2014, 2, 20)),
    (23646077, datetime(2014, 2, 26)),
    (38015510, datetime(2014, 3, 1)),
    (44634663, datetime(2014, 5, 6)),
    (46145305, datetime(2014, 5, 15)),
    (54845238, datetime(2014, 9, 20)),
    (63263518, datetime(2014, 10, 27)),
    (101260938, datetime(2015, 3, 6)),
    (112594714, datetime(2015, 8, 15)),
    (152079341, datetime(2016, 1, 22)),
    (225034354, datetime(2016, 6, 18)),
    (297621225, datetime(2016, 12, 16)),
    (390000000, datetime(2017, 6, 15)),
    (500000000, datetime(2017, 12, 30)),
    (600000000, datetime(2018, 5, 30)),
    (700000000, datetime(2018, 10, 31)),
    (800000000, datetime(2019, 3, 15)),
    (900000000, datetime(2019, 7, 20)),
    (1000000000, datetime(2019, 12, 15)),
    (1200000000, datetime(2020, 7, 15)),
    (1400000000, datetime(2021, 1, 10)),
    (1600000000, datetime(2021, 3, 20)),
    (1800000000, datetime(2021, 6, 15)),
    (2000000000, datetime(2021, 10, 30)),
    (5000000000, datetime(2022, 1, 15)),
    (5300000000, datetime(2022, 5, 1)),
    (5600000000, datetime(2022, 9, 1)),
    (5900000000, datetime(2023, 1, 1)),
    (6300000000, datetime(2023, 6, 1)),
    (6700000000, datetime(2023, 11, 1)),
    (7000000000, datetime(2024, 3, 1)),
    (7300000000, datetime(2024, 7, 1)),
    (7600000000, datetime(2024, 11, 1)),
    (7900000000, datetime(2025, 3, 1)),
    (8200000000, datetime(2025, 7, 1)),
    (8500000000, datetime(2025, 11, 1)),
    (8800000000, datetime(2026, 3, 1)),
    (9200000000, datetime(2026, 9, 1)),
]


def estimate_creation_date(user_or_chat_id: int) -> Optional[str]:
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


class Info(module.Module):
    name: ClassVar[str] = "Info"

    async def _get_deep_user_info(
        self, user_id_or_username: Union[int, str], chat_id: Optional[int] = None
    ) -> Optional[Tuple[str, Optional[str], List[List[types.InlineKeyboardButton]]]]:
        client = self.bot.client
        full_user = None
        raw_user = None

        try:
            peer = await client.resolve_peer(user_id_or_username)
            if not isinstance(
                peer,
                (
                    raw.types.InputPeerUser,
                    raw.types.InputPeerUserFromMessage,
                    raw.types.InputPeerSelf,
                ),
            ):
                return None
            full_res = await client.invoke(raw.functions.users.GetFullUser(id=peer))
            full_user = full_res.full_user
            raw_user = next(
                (
                    u
                    for u in full_res.users
                    if isinstance(u, raw.types.User)
                    and u.id == getattr(peer, "user_id", full_user.id)
                ),
                None,
            )
            if not raw_user and full_res.users:
                raw_user = full_res.users[0]
        except Exception as e:
            self.log.debug("GetFullUser raw invoke error: %s", e)

        # High-level pyrogram User
        try:
            user = await client.get_users(user_id_or_username)
        except Exception:
            user = None

        if not user and not raw_user:
            return None

        uid = user.id if user else raw_user.id
        first_name = (
            (user.first_name if user else getattr(raw_user, "first_name", None))
            or ""
        )
        last_name = (
            (user.last_name if user else getattr(raw_user, "last_name", None))
            or ""
        )
        full_name = f"{first_name} {last_name}".strip() or "Unnamed"
        esc_name = html.escape(full_name)

        username = user.username if user else getattr(raw_user, "username", None)
        dc_id = user.dc_id if user else getattr(raw_user, "dc_id", None)
        phone = (
            raw_user.phone
            if raw_user and getattr(raw_user, "phone", None)
            else getattr(user, "phone_number", None)
        )

        data = {
            "ID": f"<code>{uid}</code>",
            "First name": html.escape(first_name) if first_name else "<i>None</i>",
        }
        if last_name:
            data["Last name"] = html.escape(last_name)
        if username:
            data["Username"] = f"@{username}"
        if dc_id:
            data["DC ID"] = f"<code>{dc_id}</code>"
        if phone:
            data["Phone"] = f"<code>+{phone}</code>"

        # Raw user full metadata
        if full_user:
            if getattr(full_user, "about", None):
                data["Bio"] = f"<i>{html.escape(full_user.about.strip())}</i>"

            if getattr(full_user, "birthday", None):
                b = full_user.birthday
                y = b.year or "????"
                data["Birthday"] = f"<code>{y}-{b.month:02d}-{b.day:02d}</code>"

            if getattr(full_user, "common_chats_count", 0):
                data["Common chats"] = f"<code>{full_user.common_chats_count}</code>"

            if getattr(full_user, "stargifts_count", 0):
                data["Star gifts"] = f"<code>{full_user.stargifts_count:,}</code>"

            if getattr(full_user, "personal_channel_id", None):
                data["Personal channel"] = f"<code>-100{full_user.personal_channel_id}</code>"

        # Flags
        flags = []
        is_bot = user.is_bot if user else getattr(raw_user, "bot", False)
        is_premium = user.is_premium if user else getattr(raw_user, "premium", False)
        is_verified = user.is_verified if user else getattr(raw_user, "verified", False)
        is_scam = user.is_scam if user else getattr(raw_user, "scam", False)
        is_fake = user.is_fake if user else getattr(raw_user, "fake", False)
        is_restricted = user.is_restricted if user else getattr(raw_user, "restricted", False)
        is_support = getattr(raw_user, "support", False) or getattr(user, "is_support", False)
        is_blocked = getattr(full_user, "blocked", False) if full_user else False

        if is_bot:
            flags.append("Bot")
        if is_premium:
            flags.append("Premium")
        if is_verified:
            flags.append("Verified")
        if is_scam:
            flags.append("Scam")
        if is_fake:
            flags.append("Fake")
        if is_restricted:
            flags.append("Restricted")
        if is_support:
            flags.append("Support")
        if is_blocked:
            flags.append("Blocked")

        if getattr(full_user, "phone_calls_private", False):
            flags.append("Calls Private")
        if getattr(full_user, "voice_messages_forbidden", False):
            flags.append("Voice Msg Locked")

        if flags:
            data["Flags"] = ", ".join(flags)

        # Status / Last seen
        status_text = None
        if user and user.status:
            status_text = str(user.status).replace("UserStatus.", "").capitalize()
        elif raw_user and getattr(raw_user, "status", None):
            st = raw_user.status
            if isinstance(st, raw.types.UserStatusOnline):
                status_text = "Online"
            elif isinstance(st, raw.types.UserStatusOffline):
                dt = datetime.fromtimestamp(st.was_online, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                )
                status_text = f"Offline ({dt})"
            elif isinstance(st, raw.types.UserStatusRecently):
                status_text = "Recently"
            elif isinstance(st, raw.types.UserStatusLastWeek):
                status_text = "Within a week"
            elif isinstance(st, raw.types.UserStatusLastMonth):
                status_text = "Within a month"

        if status_text:
            data["Status"] = f"<code>{status_text}</code>"

        # Check membership in current chat
        if chat_id:
            try:
                cm = await client.get_chat_member(chat_id, uid)
                if cm:
                    cm_status = str(cm.status).replace("ChatMemberStatus.", "").capitalize()
                    if cm.custom_title:
                        cm_status += f" (<code>{html.escape(cm.custom_title)}</code>)"
                    data["Group status"] = cm_status
                    if cm.joined_date:
                        data["Joined"] = cm.joined_date.strftime("%Y-%m-%d %H:%M:%S UTC")
            except Exception:
                pass

        reg_date = estimate_creation_date(uid)
        if reg_date:
            data["Registered"] = f"<code>{reg_date}</code>"

        heading = f'<a href="tg://user?id={uid}">{esc_name}</a> info'
        urow: List[types.InlineKeyboardButton] = []
        if username:
            urow.append(
                types.InlineKeyboardButton("Open Profile", url=f"https://t.me/{username}")
            )
        else:
            urow.append(
                types.InlineKeyboardButton("Profile", url=f"tg://user?id={uid}")
            )
        buttons = [urow] if urow else []
        photo_file_id = (
            user.photo.big_file_id or user.photo.small_file_id
            if user and user.photo
            else None
        )
        return util.text.join_map(data, heading=heading, parse_mode="html"), photo_file_id, buttons

    async def _get_deep_chat_info(
        self, chat_id_or_username: Union[int, str]
    ) -> Optional[Tuple[str, Optional[str], List[List[types.InlineKeyboardButton]]]]:
        client = self.bot.client
        full_chat = None
        raw_chat = None
        is_channel = False

        try:
            peer = await client.resolve_peer(chat_id_or_username)
            if isinstance(
                peer,
                (
                    raw.types.InputPeerChannel,
                    raw.types.InputPeerChannelFromMessage,
                ),
            ):
                is_channel = True
                full_res = await client.invoke(
                    raw.functions.channels.GetFullChannel(channel=peer)
                )
                full_chat = full_res.full_chat
                raw_chat = next(
                    (
                        c
                        for c in full_res.chats
                        if isinstance(c, (raw.types.Channel, raw.types.ChannelForbidden))
                        and c.id == getattr(peer, "channel_id", full_chat.id)
                    ),
                    None,
                )
                if not raw_chat and full_res.chats:
                    raw_chat = full_res.chats[0]
            elif isinstance(peer, raw.types.InputPeerChat):
                full_res = await client.invoke(
                    raw.functions.messages.GetFullChat(chat_id=peer.chat_id)
                )
                full_chat = full_res.full_chat
                raw_chat = next(
                    (
                        c
                        for c in full_res.chats
                        if isinstance(c, (raw.types.Chat, raw.types.ChatForbidden))
                        and c.id == peer.chat_id
                    ),
                    None,
                )
                if not raw_chat and full_res.chats:
                    raw_chat = full_res.chats[0]
        except Exception as e:
            self.log.debug("GetFullChat raw invoke error: %s", e)

        # High-level pyrogram chat
        try:
            chat = await client.get_chat(chat_id_or_username)
        except Exception:
            chat = None

        if not chat and not full_chat and not raw_chat:
            return None

        cid = (
            chat.id
            if chat
            else (
                getattr(raw_chat, "id", None)
                or getattr(full_chat, "id", chat_id_or_username)
            )
        )
        title = (
            (chat.title if chat else getattr(raw_chat, "title", None))
            or "Unnamed Chat"
        )
        esc_title = html.escape(title)
        username = chat.username if chat else getattr(raw_chat, "username", None)
        dc_id = chat.dc_id if chat else getattr(raw_chat, "dc_id", None)

        # Chat Type
        if chat:
            chat_type = str(chat.type).replace("ChatType.", "").capitalize()
            if getattr(chat, "is_forum", False):
                chat_type = "Forum"
        else:
            if is_channel:
                chat_type = (
                    "Channel"
                    if getattr(raw_chat, "broadcast", False)
                    else ("Forum" if getattr(raw_chat, "forum", False) else "Supergroup")
                )
            else:
                chat_type = "Group"

        data = {
            "ID": f"<code>{cid}</code>",
            "Type": f"<code>{chat_type}</code>",
        }
        if username:
            data["Username"] = f"@{username}"
        if dc_id:
            data["DC ID"] = f"<code>{dc_id}</code>"

        # Creation date
        created_str = None
        try:
            first_msg = await client.get_messages(chat.id if chat else cid, 1)
            if first_msg and getattr(first_msg, "date", None):
                created_str = first_msg.date.strftime("%Y-%m-%d")
        except Exception:
            pass
        if not created_str:
            created_str = estimate_creation_date(cid)
        if created_str:
            data["Created"] = f"<code>{created_str}</code>"

        members_count = getattr(full_chat, "participants_count", None) or (
            chat.members_count if chat else None
        )
        admins_count = getattr(full_chat, "admins_count", None)
        owner_text = None
        bot_count = None

        # Owner & Admins
        if isinstance(full_chat, raw.types.ChatFull) and getattr(full_chat, "participants", None):
            p = full_chat.participants
            if hasattr(p, "participants"):
                calc_admins = 0
                for part in p.participants:
                    if isinstance(part, raw.types.ChatParticipantCreator):
                        calc_admins += 1
                        try:
                            ou = await client.get_users(part.user_id)
                            oname = html.escape(f"{ou.first_name} {ou.last_name or ''}".strip())
                            owner_text = f'<a href="tg://user?id={ou.id}">{oname}</a>'
                        except Exception:
                            owner_text = f"<code>{part.user_id}</code>"
                    elif isinstance(part, raw.types.ChatParticipantAdmin):
                        calc_admins += 1
                if admins_count is None:
                    admins_count = calc_admins

        if not owner_text:
            try:
                async for admin in client.get_chat_members(cid, filter=ChatMembersFilter.ADMINISTRATORS):
                    if admin.status == ChatMemberStatus.OWNER:
                        ou = admin.user
                        oname = html.escape(f"{ou.first_name} {ou.last_name or ''}".strip())
                        owner_text = f'<a href="tg://user?id={ou.id}">{oname}</a>'
                        break
            except Exception:
                pass

        if getattr(full_chat, "bot_info", None) is not None:
            bot_count = len(full_chat.bot_info)
        else:
            try:
                b_cnt = 0
                async for m in client.get_chat_members(cid, filter=ChatMembersFilter.BOTS):
                    b_cnt += 1
                    if b_cnt >= 50:
                        break
                bot_count = b_cnt
            except Exception:
                pass

        if members_count is not None:
            if bot_count is not None and members_count >= bot_count:
                user_count = members_count - bot_count
                data["Members"] = (
                    f"<code>{members_count:,}</code> "
                    f"(<code>{user_count:,}</code> users, <code>{bot_count:,}</code> bots)"
                )
            else:
                data["Members"] = f"<code>{members_count:,}</code>"

        if owner_text:
            data["Owner"] = owner_text

        if admins_count is not None:
            data["Admins"] = f"<code>{admins_count:,}</code>"

        online_count = getattr(full_chat, "online_count", None)
        if online_count is not None:
            data["Online"] = f"<code>{online_count:,}</code>"

        banned_count = getattr(full_chat, "banned_count", None) or getattr(
            full_chat, "kicked_count", None
        )
        if banned_count is not None:
            data["Banned"] = f"<code>{banned_count:,}</code>"

        # Boosts
        boosts = getattr(full_chat, "boosts_applied", None)
        if boosts:
            data["Boosts"] = f"<code>{boosts} applied</code>"

        # Slowmode & Auto-delete (TTL)
        slowmode = getattr(full_chat, "slowmode_seconds", None) or (
            chat.slow_mode_delay if chat else None
        )
        if slowmode:
            data["Slowmode"] = f"<code>{slowmode}s</code>"

        ttl = getattr(full_chat, "ttl_period", None)
        if ttl:
            data["Auto-delete"] = f"<code>{ttl}s</code>"

        # Anti-spam & Hidden members
        if getattr(full_chat, "antispam", None) is not None:
            data["Anti-Spam"] = (
                "<code>Enabled</code>" if full_chat.antispam else "<code>Disabled</code>"
            )

        if getattr(full_chat, "participants_hidden", False):
            data["Hidden members"] = "<code>Yes</code>"

        if getattr(full_chat, "hidden_prehistory", False):
            data["History"] = "<code>Hidden for new members</code>"

        if getattr(full_chat, "call", None):
            data["Voice chat"] = "<code>Active</code>"

        if getattr(full_chat, "requests_pending", 0):
            data["Join requests"] = f"<code>{full_chat.requests_pending:,}</code>"

        # Linked chat
        linked_id = getattr(full_chat, "linked_chat_id", None) or (
            chat.linked_chat.id if chat and chat.linked_chat else None
        )
        if linked_id:
            data["Linked chat"] = f"<code>-100{linked_id}</code>"

        # Invite link
        invite_link = None
        if getattr(full_chat, "exported_invite", None) and hasattr(
            full_chat.exported_invite, "link"
        ):
            invite_link = full_chat.exported_invite.link
        elif chat and chat.invite_link:
            invite_link = chat.invite_link

        # Flags
        flags = []
        is_verified = chat.is_verified if chat else getattr(raw_chat, "verified", False)
        is_scam = chat.is_scam if chat else getattr(raw_chat, "scam", False)
        is_fake = chat.is_fake if chat else getattr(raw_chat, "fake", False)
        is_restricted = (
            chat.is_restricted if chat else getattr(raw_chat, "restricted", False)
        )
        is_protected = (
            getattr(chat, "has_protected_content", False)
            if chat
            else getattr(raw_chat, "noforwards", False)
        )

        if is_verified:
            flags.append("Verified")
        if is_scam:
            flags.append("Scam")
        if is_fake:
            flags.append("Fake")
        if is_restricted:
            flags.append("Restricted")
        if is_protected:
            flags.append("Protected")

        if flags:
            data["Flags"] = ", ".join(flags)

        # Description / Bio
        about = getattr(full_chat, "about", None) or (
            chat.description if chat else None
        )
        if about:
            about_clean = about.strip()
            if len(about_clean) > 200:
                about_clean = about_clean[:197] + "..."
            data["Description"] = f"<i>{html.escape(about_clean)}</i>"

        heading = f"<b>{esc_title}</b> info"
        photo_file_id = (
            chat.photo.big_file_id or chat.photo.small_file_id
            if chat and chat.photo
            else None
        )

        row: List[types.InlineKeyboardButton] = []
        if invite_link:
            row.append(
                types.InlineKeyboardButton(
                    "Copy Link", copy_text=types.CopyTextButton(text=invite_link)
                )
            )
        if username:
            row.append(
                types.InlineKeyboardButton("Open Chat", url=f"https://t.me/{username}")
            )
        buttons = [row] if row else []

        return util.text.join_map(data, heading=heading, parse_mode="html"), photo_file_id, buttons

    async def _send_info_result(
        self,
        ctx: command.Context,
        text: str,
        photo_file_id: Optional[str] = None,
        buttons: Optional[List[List[types.InlineKeyboardButton]]] = None,
        reply_to_id: Optional[int] = None,
        target_query: Optional[str] = None,
    ) -> None:
        client = self.bot.client

        # 1. If helper bot is initialized: send inline result with buttons and photo!
        if self.bot.helper_initialized and buttons:
            try:
                bot_user = (
                    getattr(self.bot, "bot_user", None)
                    or self.bot.client_helper.me
                    or await self.bot.client_helper.get_me()
                )
                if bot_user and bot_user.username:
                    bot_photo_file_id = None
                    photo_url = None

                    # If avatar/photo exists, prepare it for inline photo display
                    if photo_file_id:
                        try:
                            photo_bytes = await client.download_media(
                                photo_file_id, in_memory=True
                            )
                            if photo_bytes:
                                setattr(photo_bytes, "name", "profile.jpg")
                                if hasattr(photo_bytes, "seek"):
                                    photo_bytes.seek(0)

                                # Fast upload via helper bot (creates bot-owned cached photo)
                                try:
                                    owner_uid = (
                                        getattr(self.bot, "uid", None)
                                        or (await client.get_me()).id
                                    )
                                    temp_msg = await self.bot.client_helper.send_photo(
                                        chat_id=owner_uid, photo=photo_bytes
                                    )
                                    if temp_msg and temp_msg.photo:
                                        bot_photo_file_id = temp_msg.photo.file_id

                                        async def _cleanup_temp_msg(m: types.Message):
                                            try:
                                                await asyncio.sleep(4.0)
                                                await m.delete()
                                            except Exception:
                                                pass

                                        self.bot.loop.create_task(_cleanup_temp_msg(temp_msg))
                                except Exception as up_err:
                                    self.log.debug("Helper send_photo error: %s", up_err)

                                # Optional fallback: Catbox upload for direct photo URL
                                if not bot_photo_file_id:
                                    try:
                                        if hasattr(photo_bytes, "getvalue"):
                                            data_bytes = photo_bytes.getvalue()
                                        else:
                                            photo_bytes.seek(0)
                                            data_bytes = photo_bytes.read()
                                        files = {"fileToUpload": ("profile.jpg", data_bytes, "image/jpeg")}
                                        data = {"reqtype": "fileupload"}
                                        resp = await self.bot.http.post(
                                            "https://catbox.moe/user/api.php",
                                            data=data,
                                            files=files,
                                            timeout=10.0,
                                        )
                                        if resp.status_code == 200 and resp.text.startswith("https://"):
                                            photo_url = resp.text.strip()
                                    except Exception as cat_err:
                                        self.log.debug("Catbox upload error: %s", cat_err)
                        except Exception as dl_err:
                            self.log.debug("Photo download error: %s", dl_err)

                    if not hasattr(self.bot, "_inline_cache"):
                        self.bot._inline_cache = {}
                    cache_key = uuid.uuid4().hex[:10]
                    self.bot._inline_cache[cache_key] = {
                        "text": text,
                        "buttons": buttons,
                        "photo_file_id": bot_photo_file_id,
                        "photo_url": photo_url,
                    }
                    inline_q = f"info_cache {cache_key}"
                    res = await client.get_inline_bot_results(
                        bot=bot_user.username,
                        query=inline_q,
                    )
                    if res and res.results:
                        if ctx.msg:
                            try:
                                await ctx.msg.delete()
                            except Exception:
                                pass
                        result_id = res.results[0].id
                        thread_id = getattr(ctx.msg, "message_thread_id", None)
                        if getattr(ctx.chat, "is_forum", False) and thread_id is not None:
                            await client.send_inline_bot_result(
                                ctx.msg.chat.id,
                                res.query_id,
                                result_id,
                                message_thread_id=thread_id,
                            )
                        else:
                            await client.send_inline_bot_result(
                                ctx.msg.chat.id,
                                res.query_id,
                                result_id,
                            )
                        return
            except Exception as e:
                self.log.debug("Helper inline dispatch failed: %s", e)

        # 2. If photo is available: download and send photo with caption
        if photo_file_id:
            try:
                photo_bytes = await client.download_media(
                    photo_file_id, in_memory=True
                )
                if photo_bytes:
                    setattr(photo_bytes, "name", "profile.jpg")
                    await client.send_photo(
                        chat_id=ctx.msg.chat.id,
                        photo=photo_bytes,
                        caption=text,
                        parse_mode=ParseMode.HTML,
                        reply_to_message_id=reply_to_id,
                    )
                    if ctx.response:
                        await ctx.response.delete()
                    elif ctx.msg:
                        await ctx.msg.delete()
                    return
            except Exception as e:
                self.log.debug("Failed to send profile photo with caption: %s", e)

        # 3. Fallback to text message
        await ctx.respond(
            text,
            parse_mode=ParseMode.HTML,
            link_preview_options=types.LinkPreviewOptions(is_disabled=True),
        )

    @command.desc("Get deep information about a user, group, channel, or current chat")
    @command.alias(
        "whois",
        "userinfo",
        "chatinfo",
        "cinfo",
        "uinfo",
        "ginfo",
        "groupinfo",
        "who",
        "w",
    )
    @command.usage("[user/chat id/username | reply to message]", optional=True)
    async def cmd_info(self, ctx: command.Context) -> Optional[str]:
        target = ctx.input.strip() if ctx.input else None
        reply_to_id = ctx.reply_msg.id if ctx.reply_msg else None

        # Case 1: User explicitly provided an argument
        if target:
            clean: Union[int, str] = target
            if isinstance(clean, str):
                if clean.startswith("https://t.me/"):
                    clean = clean[13:]
                elif clean.startswith("t.me/"):
                    clean = clean[5:]
                if clean.startswith("@"):
                    clean = clean[1:]
                try:
                    clean = int(clean)
                except ValueError:
                    pass

            # Try resolving user first
            res = await self._get_deep_user_info(clean, chat_id=ctx.chat.id)
            if res is not None:
                text, photo_id, buttons = res
                await self._send_info_result(ctx, text, photo_id, buttons, reply_to_id, target_query=str(clean))
                return None

            # Try resolving chat next
            res = await self._get_deep_chat_info(clean)
            if res is not None:
                text, photo_id, buttons = res
                await self._send_info_result(ctx, text, photo_id, buttons, reply_to_id, target_query=str(clean))
                return None

            return f"<i>Could not resolve user or chat</i> <code>{html.escape(str(target))}</code>."

        # Case 2: Replied to a message
        if ctx.reply_msg:
            if ctx.reply_msg.from_user:
                tq = str(ctx.reply_msg.from_user.id)
                res = await self._get_deep_user_info(
                    ctx.reply_msg.from_user.id, chat_id=ctx.chat.id
                )
                if res is not None:
                    text, photo_id, buttons = res
                    await self._send_info_result(ctx, text, photo_id, buttons, reply_to_id, target_query=tq)
                    return None
            elif ctx.reply_msg.sender_chat:
                tq = str(ctx.reply_msg.sender_chat.id)
                res = await self._get_deep_chat_info(ctx.reply_msg.sender_chat.id)
                if res is not None:
                    text, photo_id, buttons = res
                    await self._send_info_result(ctx, text, photo_id, buttons, reply_to_id, target_query=tq)
                    return None
            elif ctx.reply_msg.forward_from:
                tq = str(ctx.reply_msg.forward_from.id)
                res = await self._get_deep_user_info(
                    ctx.reply_msg.forward_from.id, chat_id=ctx.chat.id
                )
                if res is not None:
                    text, photo_id, buttons = res
                    await self._send_info_result(ctx, text, photo_id, buttons, reply_to_id, target_query=tq)
                    return None
            elif ctx.reply_msg.forward_from_chat:
                tq = str(ctx.reply_msg.forward_from_chat.id)
                res = await self._get_deep_chat_info(ctx.reply_msg.forward_from_chat.id)
                if res is not None:
                    text, photo_id, buttons = res
                    await self._send_info_result(ctx, text, photo_id, buttons, reply_to_id, target_query=tq)
                    return None

        # Case 3: No input and no reply -> Info of current chat
        if ctx.chat.type == ChatType.PRIVATE:
            res = await self._get_deep_user_info(ctx.chat.id, chat_id=ctx.chat.id)
            if res is not None:
                text, photo_id, buttons = res
                await self._send_info_result(ctx, text, photo_id, buttons, reply_to_id, target_query=str(ctx.chat.id))
                return None

        res = await self._get_deep_chat_info(ctx.chat.id)
        if res is not None:
            text, photo_id, buttons = res
            await self._send_info_result(ctx, text, photo_id, buttons, reply_to_id, target_query=str(ctx.chat.id))
            return None

        return "<i>Failed to fetch chat information.</i>"
