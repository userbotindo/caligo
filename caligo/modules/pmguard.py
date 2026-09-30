import asyncio
from datetime import datetime, timezone
import html
from typing import ClassVar, List, Optional, Set, Union

import pymongo
from pymongo.asynchronous.collection import AsyncCollection
from pyrogram import errors, types
from pyrogram.enums import ChatType, ParseMode

from caligo import command, module, util


DEFAULT_WARN_TEMPLATE = (
    "<b>Caligo PM Security</b>\n\n"
    "Direct messages to this account are protected by an automated system.\n"
    "Please state your identity and purpose in a single message and wait for approval.\n\n"
    "<b>Warning:</b> <code>{current}/{limit}</code>"
)

_format_target_html = util.tg.format_target_html


class PMGuard(module.Module):
    name: ClassVar[str] = "PMGuard"

    db: AsyncCollection
    enabled: bool
    mode: str
    limit: int
    custom_message: Optional[str]
    approved_users: Set[int]

    async def on_load(self) -> None:
        self.db = self.bot.db.get_collection(self.name.upper())

        data = await self.db.find_one({"_id": 0}) or {}
        self.enabled = bool(data.get("enabled", False))
        self.mode = str(data.get("mode", "warn")).lower()
        if self.mode not in ("delete", "block", "warn"):
            self.mode = "warn"
        self.limit = max(1, int(data.get("limit", 3)))
        self.custom_message = data.get("custom_message")
        self.approved_users = set(data.get("approved_users", []))

    async def _save_settings(self) -> None:
        await self.db.update_one(
            {"_id": 0},
            {
                "$set": {
                    "enabled": self.enabled,
                    "mode": self.mode,
                    "limit": self.limit,
                    "custom_message": self.custom_message,
                    "approved_users": list(self.approved_users),
                }
            },
            upsert=True,
        )

    async def _log_pm_activity(
        self,
        text: str,
        buttons: Optional[List[List[types.InlineKeyboardButton]]] = None,
    ) -> None:
        """Dispatches PM Guard log via Logging module or falls back to PM/Saved Messages."""
        log_mod = self.bot.modules.get("Logging")
        if log_mod is not None and hasattr(log_mod, "send_log"):
            await log_mod.send_log(text, buttons=buttons, force=True)
            return

        text = self.bot.redact_message(text)
        reply_markup = types.InlineKeyboardMarkup(buttons) if buttons else None
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
                return
            except Exception as e:
                self.log.debug("Helper fallback failed: %s", e)

        try:
            await self.bot.client.send_message(
                "me",
                text,
                parse_mode=ParseMode.HTML,
                link_preview_options=types.LinkPreviewOptions(is_disabled=True),
            )
        except Exception as e:
            self.log.error("Failed to send PM guard log to Saved Messages: %s", e)

    async def on_message(self, msg: types.Message) -> None:
        """Inspects incoming private messages and executes PM Guard policies."""
        if not self.enabled:
            return

        if not msg.chat or msg.chat.type not in (ChatType.PRIVATE, ChatType.BOT):
            return

        if msg.outgoing:
            return

        sender = msg.from_user
        if not sender:
            return

        owner_id = getattr(self.bot, "uid", None)
        if sender.is_self or (owner_id and sender.id == owner_id):
            return

        if (
            sender.id in (777000, 42777)
            or sender.is_support
            or sender.is_verified
            or sender.is_bot
        ):
            return

        if sender.id in self.approved_users or sender.is_contact:
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        sender_mention = _format_target_html(sender)
        user_id = sender.id
        raw_content = msg.text or msg.caption or "[Media / Non-text Message]"
        escaped_content = html.escape(util.tg.truncate(raw_content))

        profile_link = util.tg.get_profile_link(sender)
        buttons = []
        if profile_link:
            buttons.append(
                [types.InlineKeyboardButton("Open Profile", url=profile_link)]
            )

        if self.mode == "delete":
            try:
                await msg.delete()
            except Exception:
                pass

            try:
                await self.bot.client.delete_chat_history(
                    msg.chat.id, revoke=True
                )
            except Exception:
                try:
                    await self.bot.client.delete_messages(
                        msg.chat.id, [msg.id], revoke=True
                    )
                except Exception:
                    pass

            log_text = (
                "<b>Deleted Private Message</b>\n\n"
                f"• <b>From:</b> {sender_mention}\n\n"
                f"<blockquote expandable>{escaped_content}</blockquote>"
            )
            await self._log_pm_activity(log_text, buttons=buttons)

        elif self.mode == "block":
            try:
                await self.bot.client.block_user(user_id)
            except Exception as e:
                self.log.debug("Failed to block PM sender %s: %s", user_id, e)

            try:
                await msg.delete()
            except Exception:
                pass

            try:
                await self.bot.client.delete_messages(
                    msg.chat.id, [msg.id], revoke=True
                )
            except Exception:
                pass

            log_text = (
                "<b>Blocked Private Message</b>\n\n"
                f"• <b>From:</b> {sender_mention}\n\n"
                f"<blockquote expandable>{escaped_content}</blockquote>"
            )
            await self._log_pm_activity(log_text, buttons=buttons)

        elif self.mode == "warn":
            doc = await self.db.find_one_and_update(
                {"_id": user_id},
                {
                    "$inc": {"count": 1},
                    "$set": {"last_warned": datetime.now(timezone.utc)},
                },
                upsert=True,
                return_document=pymongo.ReturnDocument.AFTER,
            )
            count = doc.get("count", 1) if doc else 1

            if count < self.limit:
                template = self.custom_message or DEFAULT_WARN_TEMPLATE
                warn_msg = template.format(current=count, limit=self.limit)

                try:
                    await msg.reply(warn_msg, parse_mode=ParseMode.HTML)
                except errors.FloodWait as e:
                    await asyncio.sleep(e.value + 1)
                    try:
                        await msg.reply(warn_msg, parse_mode=ParseMode.HTML)
                    except Exception:
                        pass
                except Exception as e:
                    self.log.debug("Failed to reply PM warning: %s", e)

            else:
                try:
                    await self.bot.client.block_user(user_id)
                except Exception as e:
                    self.log.debug(
                        "Failed to block user %s on limit reached: %s", user_id, e
                    )

                try:
                    await self.bot.client.delete_messages(
                        msg.chat.id, [msg.id], revoke=True
                    )
                except Exception:
                    try:
                        await msg.delete()
                    except Exception:
                        pass

                log_text = (
                    "<b>Blocked User (PM Guard)</b>\n\n"
                    f"• <b>From:</b> {sender_mention}\n\n"
                    f"<blockquote expandable>{escaped_content}</blockquote>"
                )
                await self._log_pm_activity(log_text, buttons=buttons)

    @command.desc("Enable or disable PM Guard protection")
    @command.usage("[on | off?]", optional=True)
    @command.alias("pmguard")
    async def cmd_antipm(self, ctx: command.Context) -> str:
        arg = ctx.input.strip().lower() if ctx.input else ""

        if arg == "on":
            self.enabled = True
            await self._save_settings()
            return "PM Guard enabled."

        if arg == "off":
            self.enabled = False
            await self._save_settings()
            return "PM Guard disabled."

        status = "<b>enabled</b>" if self.enabled else "<b>disabled</b>"
        return (
            f"PM Guard is currently {status}.\n"
            f"• <b>Mode:</b> <code>{self.mode}</code>\n"
            f"• <b>Warning limit:</b> <code>{self.limit}</code>\n"
            f"• <b>Approved users:</b> <code>{len(self.approved_users)}</code>\n\n"
            f"Use <code>{self.bot.prefix}antipm on</code> or <code>{self.bot.prefix}antipm off</code>."
        )

    @command.desc("Set PM Guard action mode (delete, block, warn)")
    @command.usage("<delete | block | warn>")
    @command.alias("setpmmode")
    async def cmd_pmmode(self, ctx: command.Context) -> str:
        if not ctx.input:
            return (
                f"PM Guard mode is currently <code>{self.mode}</code>.\n"
                "Available modes: <code>delete</code>, <code>block</code>, <code>warn</code>"
            )

        mode = ctx.input.strip().lower()
        if mode not in ("delete", "block", "warn"):
            return (
                f"<b>Error:</b> Invalid PM mode <code>{html.escape(mode)}</code>.\n"
                "Available modes: <code>delete</code>, <code>block</code>, <code>warn</code>"
            )

        self.mode = mode
        await self._save_settings()
        return f"PM Guard mode set to <code>{self.mode}</code>."

    @command.desc("Set PM Guard warning limit for warn mode")
    @command.usage("<number>")
    @command.alias("setpmlimit")
    async def cmd_pmlimit(self, ctx: command.Context) -> str:
        if not ctx.input:
            return f"PM warning limit is currently <code>{self.limit}</code>."

        try:
            val = int(ctx.input.strip())
            if val < 1:
                return "<b>Error:</b> Warning limit must be at least 1."
        except ValueError:
            return "<b>Error:</b> Please provide a valid integer limit."

        self.limit = val
        await self._save_settings()
        return f"PM warning limit set to <code>{self.limit}</code>."

    @command.desc("Approve a user to send private messages")
    @command.usage("[user?]", optional=True, reply=True)
    @command.alias("allow", "approve", "pmapprove")
    async def cmd_pmallow(self, ctx: command.Context) -> str:
        target, _ = await util.tg.extract_target_and_rest(ctx)

        if target is None:
            if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
                target = ctx.msg.chat
            else:
                return "<i>Reply to a user or specify a user to approve.</i>"

        target_id = util.tg.get_target_id(target)
        if isinstance(target_id, str):
            try:
                target_id = int(target_id)
            except ValueError:
                resolved = await util.tg.resolve_user(self.bot.client, target_id)
                target_id = util.tg.get_target_id(resolved)

        if isinstance(target_id, int):
            self.approved_users.add(target_id)
            await self._save_settings()
            await self.db.delete_one({"_id": target_id})
            formatted = _format_target_html(target)
            return f"Approved {formatted} for private messages."

        return "<i>Could not resolve target user.</i>"

    @command.desc("Disapprove a user from sending private messages")
    @command.usage("[user?]", optional=True, reply=True)
    @command.alias("disallow", "disapprove", "pmdisapprove")
    async def cmd_pmdisallow(self, ctx: command.Context) -> str:
        target, _ = await util.tg.extract_target_and_rest(ctx)

        if target is None:
            if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
                target = ctx.msg.chat
            else:
                return "<i>Reply to a user or specify a user to disapprove.</i>"

        target_id = util.tg.get_target_id(target)
        if isinstance(target_id, str):
            try:
                target_id = int(target_id)
            except ValueError:
                resolved = await util.tg.resolve_user(self.bot.client, target_id)
                target_id = util.tg.get_target_id(resolved)

        if isinstance(target_id, int):
            self.approved_users.discard(target_id)
            await self._save_settings()
            formatted = _format_target_html(target)
            return f"Disapproved {formatted} from private messages."

        return "<i>Could not resolve target user.</i>"

    @command.desc("Set custom anti-PM warning message or view/reset to default")
    @command.usage("[custom message | 'reset'?]", optional=True)
    @command.alias("setpmmsg", "pmwarn", "pmtext")
    async def cmd_pmmsg(self, ctx: command.Context) -> str:
        if not ctx.input:
            current = self.custom_message or DEFAULT_WARN_TEMPLATE
            is_custom = "Custom" if self.custom_message else "Default"
            return (
                f"<b>Current PM Warning Message ({is_custom}):</b>\n"
                f"<blockquote expandable>{current}</blockquote>\n\n"
                f"• <b>To customize:</b> <code>{self.bot.prefix}pmmsg &lt;your message&gt;</code>\n"
                f"• <b>Supported placeholders:</b> <code>{{current}}</code> (warning count), <code>{{limit}}</code> (limit)\n"
                f"• <b>To reset:</b> <code>{self.bot.prefix}pmmsg reset</code>"
            )

        val = ctx.input.strip()
        if val.lower() in ("reset", "default"):
            self.custom_message = None
            await self._save_settings()
            return (
                "<b>PM warning message reset to default:</b>\n"
                f"<blockquote expandable>{DEFAULT_WARN_TEMPLATE}</blockquote>"
            )

        self.custom_message = val
        await self._save_settings()
        return (
            "<b>Custom PM warning message updated:</b>\n"
            f"<blockquote expandable>{self.custom_message}</blockquote>"
        )

    @command.desc("Reset PM warning counter for a user")
    @command.usage("[user?]", optional=True, reply=True)
    async def cmd_pmreset(self, ctx: command.Context) -> str:
        target, _ = await util.tg.extract_target_and_rest(ctx)

        if target is None:
            if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
                target = ctx.msg.chat
            else:
                return "<i>Reply to a user or specify a user to reset.</i>"

        target_id = util.tg.get_target_id(target)
        if isinstance(target_id, str):
            try:
                target_id = int(target_id)
            except ValueError:
                resolved = await util.tg.resolve_user(self.bot.client, target_id)
                target_id = util.tg.get_target_id(resolved)

        if isinstance(target_id, int):
            await self.db.delete_one({"_id": target_id})
            formatted = _format_target_html(target)
            return f"Warning counter reset for {formatted}."

        return "<i>Could not resolve target user.</i>"
