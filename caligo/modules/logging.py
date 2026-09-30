import asyncio
from datetime import datetime, timezone
import html
from typing import ClassVar, List, Optional, Union

from pymongo.asynchronous.collection import AsyncCollection
from pyrogram import enums, errors, types
from pyrogram.enums import ChatMemberStatus, ChatType, ParseMode

from caligo import command, module, util


class Logging(module.Module):
    name: ClassVar[str] = "Logging"

    db: AsyncCollection
    enabled: bool
    chat_id: Optional[int]

    async def on_load(self) -> None:
        self.db = self.bot.db.get_collection(self.name.upper())

        data = await self.db.find_one({"_id": 0}) or {}
        self.enabled = bool(data.get("enabled", False))
        self.chat_id = data.get("chat_id")

    async def _save_config(self) -> None:
        await self.db.update_one(
            {"_id": 0},
            {
                "$set": {
                    "enabled": self.enabled,
                    "chat_id": self.chat_id,
                }
            },
            upsert=True,
        )

    async def provision_helper(self, chat_id: int) -> bool:
        """Invites and promotes helper bot with required permissions in the group or channel."""
        return await util.tg.provision_helper(self.bot, chat_id)

    async def send_log(
        self,
        text: str,
        *,
        buttons: Optional[List[List[types.InlineKeyboardButton]]] = None,
        force: bool = False,
    ) -> bool:
        """Sends log message using Helper Bot when available, or fallbacks."""
        if not self.enabled and not force:
            return False

        text = self.bot.redact_message(text)
        target_chat = self.chat_id
        reply_markup = types.InlineKeyboardMarkup(buttons) if buttons else None

        if target_chat is not None:
            if self.bot.helper_initialized and self.bot.client_helper.is_connected:
                try:
                    await self.bot.client_helper.send_message(
                        target_chat,
                        text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup,
                        link_preview_options=types.LinkPreviewOptions(is_disabled=True),
                    )
                    return True
                except errors.FloodWait as e:
                    await asyncio.sleep(e.value + 1)
                    try:
                        await self.bot.client_helper.send_message(
                            target_chat,
                            text,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup,
                            link_preview_options=types.LinkPreviewOptions(is_disabled=True),
                        )
                        return True
                    except Exception as e:
                        self.log.warning(
                            "Helper bot failed to send log to %s: %s", target_chat, e
                        )
                except (errors.UserNotParticipant, errors.ChatAdminRequired, errors.ChannelPrivate):
                    if await self.provision_helper(target_chat):
                        try:
                            await self.bot.client_helper.send_message(
                                target_chat,
                                text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup,
                                link_preview_options=types.LinkPreviewOptions(is_disabled=True),
                            )
                            return True
                        except Exception as e:
                            self.log.warning(
                                "Helper bot failed to send log to %s: %s", target_chat, e
                            )
                except Exception as e:
                    self.log.warning(
                        "Helper bot failed to send log to %s: %s", target_chat, e
                    )

            try:
                await self.bot.client.send_message(
                    target_chat,
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup if buttons else None,
                    link_preview_options=types.LinkPreviewOptions(is_disabled=True),
                )
                return True
            except Exception as e:
                # Retry without reply_markup if user account cannot send inline buttons
                try:
                    await self.bot.client.send_message(
                        target_chat,
                        text,
                        parse_mode=ParseMode.HTML,
                        link_preview_options=types.LinkPreviewOptions(is_disabled=True),
                    )
                    return True
                except Exception as err:
                    self.log.error(
                        "Userbot failed to send log to destination %s: %s",
                        target_chat,
                        err,
                    )

        fallback_sent = False
        owner_id = getattr(self.bot, "uid", None)

        if (
            self.bot.helper_initialized
            and self.bot.client_helper.is_connected
            and owner_id
        ):
            try:
                await self.bot.client_helper.send_message(
                    owner_id,
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                    link_preview_options=types.LinkPreviewOptions(is_disabled=True),
                )
                fallback_sent = True
            except Exception as e:
                self.log.debug("Helper bot fallback to owner PM failed: %s", e)

        if fallback_sent:
            return True

        try:
            await self.bot.client.send_message(
                "me",
                text,
                parse_mode=ParseMode.HTML,
                link_preview_options=types.LinkPreviewOptions(is_disabled=True),
            )
            return True
        except Exception as e:
            self.log.error("Failed to send fallback log to Saved Messages: %s", e)
            return False

    async def on_message(self, msg: types.Message) -> None:
        """Monitors mentions in groups when logging is enabled."""
        if not self.enabled:
            return

        if msg.outgoing:
            return

        if not msg.chat or msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
            return

        sender = getattr(msg, "from_user", None)
        if sender and (
            getattr(sender, "is_bot", False)
            or getattr(sender, "id", None) == getattr(self.bot, "bot_uid", None)
        ):
            return

        owner_id = getattr(self.bot, "uid", None)
        owner_username = (
            getattr(self.bot.user, "username", None)
            if getattr(self.bot, "user", None)
            else None
        )

        is_mentioned = False

        if (
            msg.reply_to_message
            and msg.reply_to_message.from_user
            and msg.reply_to_message.from_user.id == owner_id
        ):
            is_mentioned = True

        if not is_mentioned and msg.entities:
            for entity in msg.entities:
                if (
                    entity.type == enums.MessageEntityType.TEXT_MENTION
                    and entity.user
                    and entity.user.id == owner_id
                ):
                    is_mentioned = True
                    break
                if (
                    entity.type == enums.MessageEntityType.MENTION
                    and owner_username
                    and msg.text
                ):
                    mention_text = msg.text[
                        entity.offset : entity.offset + entity.length
                    ]
                    if mention_text.lstrip("@").lower() == owner_username.lower():
                        is_mentioned = True
                        break

        if not is_mentioned and msg.caption_entities:
            for entity in msg.caption_entities:
                if (
                    entity.type == enums.MessageEntityType.TEXT_MENTION
                    and entity.user
                    and entity.user.id == owner_id
                ):
                    is_mentioned = True
                    break
                if (
                    entity.type == enums.MessageEntityType.MENTION
                    and owner_username
                    and msg.caption
                ):
                    mention_text = msg.caption[
                        entity.offset : entity.offset + entity.length
                    ]
                    if mention_text.lstrip("@").lower() == owner_username.lower():
                        is_mentioned = True
                        break

        if not is_mentioned:
            return

        chat_title = html.escape(getattr(msg.chat, "title", None) or "Unknown Chat")
        sender = getattr(msg, "from_user", None)
        sender_mention = util.tg.mention_user_html(sender) if sender else "Unknown"
        raw_content = msg.text or msg.caption or "[Media / Non-text Message]"
        escaped_content = html.escape(util.tg.truncate(raw_content))
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        log_text = (
            "<b>Mention Alert</b>\n\n"
            f"• <b>Chat:</b> {chat_title}\n"
            f"• <b>From:</b> {sender_mention}\n"
            f"• <b>Time:</b> <code>{timestamp}</code>\n\n"
            f"<b>Message:</b>\n<blockquote expandable>{escaped_content}</blockquote>"
        )

        buttons = []
        btn_row = []
        msg_link = self._make_message_link(msg.chat, msg.id)
        if msg_link:
            btn_row.append(
                types.InlineKeyboardButton("Open Message", url=msg_link)
            )

        if sender:
            profile_link = self._make_profile_link(sender)
            if profile_link:
                btn_row.append(
                    types.InlineKeyboardButton("Open Profile", url=profile_link)
                )

        if btn_row:
            buttons.append(btn_row)

        await self.send_log(log_text, buttons=buttons)

    async def on_chat_action(self, msg: types.Message) -> None:
        """Monitors member joins/leaves in groups when logging is enabled."""
        if not self.enabled:
            return

        if not msg.chat or msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
            return

        sender = getattr(msg, "from_user", None)
        if sender and (
            getattr(sender, "is_bot", False)
            or getattr(sender, "id", None) == getattr(self.bot, "bot_uid", None)
        ):
            return

        chat_title = html.escape(getattr(msg.chat, "title", None) or "Unknown Chat")
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        if msg.new_chat_members:
            for user in msg.new_chat_members:
                if (
                    getattr(user, "is_bot", False)
                    or user.id == getattr(self.bot, "bot_uid", None)
                ):
                    continue

                u_mention = util.tg.mention_user_html(user)
                log_text = (
                    "<b>Member Joined</b>\n\n"
                    f"• <b>Chat:</b> {chat_title}\n"
                    f"• <b>User:</b> {u_mention}\n"
                    f"• <b>Time:</b> <code>{timestamp}</code>"
                )

                buttons = []
                btn_row = []
                p_link = self._make_profile_link(user)
                if p_link:
                    btn_row.append(
                        types.InlineKeyboardButton("Open Profile", url=p_link)
                    )
                if btn_row:
                    buttons.append(btn_row)

                await self.send_log(log_text, buttons=buttons)

        if msg.left_chat_member:
            user = msg.left_chat_member
            if (
                getattr(user, "is_bot", False)
                or user.id == getattr(self.bot, "bot_uid", None)
            ):
                return

            u_mention = util.tg.mention_user_html(user)
            log_text = (
                "<b>Member Left</b>\n\n"
                f"• <b>Chat:</b> {chat_title}\n"
                f"• <b>User:</b> {u_mention}\n"
                f"• <b>Time:</b> <code>{timestamp}</code>"
            )

            buttons = []
            btn_row = []
            p_link = self._make_profile_link(user)
            if p_link:
                btn_row.append(
                    types.InlineKeyboardButton("Open Profile", url=p_link)
                )
            if btn_row:
                buttons.append(btn_row)

            await self.send_log(log_text, buttons=buttons)

    def _make_message_link(
        self, chat: types.Chat, message_id: int
    ) -> Optional[str]:
        return util.tg.get_message_link(chat, message_id)

    def _make_profile_link(self, user: types.User) -> Optional[str]:
        return util.tg.get_profile_link(user)

    @command.desc("Enable or disable sensitive activity logging")
    @command.usage("[on | off?]", optional=True)
    async def cmd_logging(self, ctx: command.Context) -> str:
        arg = ctx.input.strip().lower() if ctx.input else ""

        if arg == "on":
            self.enabled = True
            await self._save_config()
            return "Logging enabled."

        if arg == "off":
            self.enabled = False
            await self._save_config()
            return "Logging disabled."

        status = "<b>enabled</b>" if self.enabled else "<b>disabled</b>"
        dest = (
            f"<code>{self.chat_id}</code>"
            if self.chat_id is not None
            else "<i>Not configured</i>"
        )
        return (
            f"Activity logging is currently {status}.\n"
            f"• <b>Destination:</b> {dest}\n\n"
            f"Use <code>{self.bot.prefix}logging on</code> or <code>{self.bot.prefix}logging off</code>."
        )

    @command.desc("Set private chat or private channel destination for activity logs")
    @command.usage("[chat_id | username | 'here'?]", optional=True)
    async def cmd_setlog(self, ctx: command.Context) -> str:
        target_raw = ctx.input.strip() if ctx.input else ""

        if not target_raw or target_raw.lower() == "here":
            chat = ctx.msg.chat
        else:
            chat_target: Union[int, str]
            if (
                target_raw.isdigit()
                or (target_raw.startswith("-") and target_raw[1:].isdigit())
            ):
                chat_target = int(target_raw)
            else:
                chat_target = target_raw

            try:
                chat = await self.bot.client.get_chat(chat_target)
            except errors.FloodWait as e:
                await asyncio.sleep(e.value + 1)
                chat = await self.bot.client.get_chat(chat_target)
            except Exception as e:
                return f"<b>Error:</b> Failed to resolve chat: <code>{html.escape(str(e))}</code>"

        if chat.type == ChatType.BOT:
            return "<b>Error:</b> Cannot set a bot chat as the log destination."

        is_direct_private = chat.type == ChatType.PRIVATE
        is_private_channel_or_group = (
            chat.type in (ChatType.CHANNEL, ChatType.SUPERGROUP, ChatType.GROUP)
            and getattr(chat, "username", None) is None
        )

        if not (is_direct_private or is_private_channel_or_group):
            uname_text = f" (<code>@{chat.username}</code>)" if getattr(chat, "username", None) else ""
            return (
                f"<b>Error:</b> Cannot set a public chat or channel{uname_text} as the log destination.\n"
                "Logs contain sensitive private data and must only be sent to a <b>private chat</b> or <b>private channel</b>."
            )

        self.chat_id = chat.id
        await self._save_config()

        if chat.type in (ChatType.CHANNEL, ChatType.SUPERGROUP, ChatType.GROUP):
            await self.provision_helper(chat.id)

        chat_name = html.escape(
            (
                chat.first_name
                + (" " + chat.last_name if chat.last_name else "")
            )
            if chat.first_name
            else (chat.title or str(chat.id))
        )
        return f"Logging destination set to <b>{chat_name}</b> [<code>{self.chat_id}</code>]."

    @command.desc("Clear configured logging destination")
    async def cmd_clearlog(self, ctx: command.Context) -> str:
        self.chat_id = None
        await self._save_config()
        return "Logging destination cleared."
