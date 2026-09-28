import asyncio
from datetime import datetime, timedelta
import re
from typing import ClassVar, Optional, Tuple, Union

from pyrogram.enums import ChatMembersFilter, ChatType
from pyrogram.errors import (
    ChatAdminRequired,
    FloodWait,
    RightForbidden,
    RPCError,
    UserAdminInvalid,
)
from pyrogram.types import (
    ChatMember,
    ChatPermissions,
    ChatPrivileges,
    User,
)

from caligo import command, module, util


# Reusable utilities from caligo.util
_parse_duration = util.time.parse_duration
_extract_duration_and_reason = util.time.extract_duration_and_reason
_get_target_id = util.tg.get_target_id
_format_target = util.tg.format_target


class Moderation(module.Module):
    name: ClassVar[str] = "Moderation"

    def _is_self(self, target_id: Union[int, str]) -> bool:
        my_id = getattr(self.bot, "uid", None) or getattr(
            getattr(self.bot, "user", None), "id", None
        )
        return my_id is not None and target_id == my_id

    async def _resolve_user(
        self,
        target: Union[int, str, User],
    ) -> Union[User, int, str]:
        return await util.tg.resolve_user(self.bot.client, target)

    async def _extract_target_and_rest(
        self, ctx: command.Context
    ) -> Tuple[Optional[Union[User, int, str]], Optional[str]]:
        return await util.tg.extract_target_and_rest(ctx)


    @command.desc("Mention everyone in this group (**DO NOT ABUSE**)")
    @command.usage("[comment?]", optional=True)
    async def cmd_everyone(
        self,
        ctx: command.Context,
        *,
        tag: str = "\U000e0020everyone",
        user_filter: ChatMembersFilter = ChatMembersFilter.SEARCH,
    ) -> Optional[str]:
        comment = ctx.input

        if ctx.msg.chat.type == ChatType.PRIVATE:
            return "__This command can only be used in groups.__"

        mention_text = f"@{tag}"
        if comment:
            mention_text += " " + comment

        mention_slots = 4096 - len(mention_text)

        chat = ctx.msg.chat.id
        member: ChatMember
        try:
            async for member in self.bot.client.get_chat_members(
                chat, filter=user_filter
            ):  # type: ignore
                mention_text += f"[\u200b](tg://user?id={member.user.id})"

                mention_slots -= 1
                if mention_slots == 0:
                    break
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)

        await ctx.respond(mention_text, mode="repost")

    @command.desc("Mention all admins in a group (**DO NOT ABUSE**)")
    @command.usage("[comment?]", optional=True)
    async def cmd_admin(self, ctx: command.Context) -> Optional[str]:
        return await self.cmd_everyone(
            ctx, tag="admin", user_filter=ChatMembersFilter.ADMINISTRATORS
        )

    @command.desc("reply to a message, mark as start until your purge command.")
    @command.usage("purge", reply=True)
    async def cmd_purge(self, ctx: command.Context) -> Optional[str]:
        if not ctx.msg.reply_to_message:
            return "__Reply to a message.__"

        await ctx.respond("Purging...")

        time_start = datetime.now()
        start, end = ctx.msg.reply_to_message.id, ctx.msg.id
        messages_id = []

        purged = 0
        for message_id in range(start, end):
            messages_id.append(message_id)
            if len(messages_id) == 100:
                try:
                    purged += await ctx.bot.client.delete_messages(
                        chat_id=ctx.msg.chat.id,
                        message_ids=messages_id,
                    )
                except FloodWait as e:
                    await asyncio.sleep(e.value + 1)
                    purged += await ctx.bot.client.delete_messages(
                        chat_id=ctx.msg.chat.id,
                        message_ids=messages_id,
                    )
                messages_id = []

        if messages_id:
            try:
                purged += await ctx.bot.client.delete_messages(
                    chat_id=ctx.msg.chat.id,
                    message_ids=messages_id,
                    revoke=True,
                )
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                purged += await ctx.bot.client.delete_messages(
                    chat_id=ctx.msg.chat.id,
                    message_ids=messages_id,
                    revoke=True,
                )

        time_end = datetime.now()
        run_time = (time_end - time_start).seconds
        time = "second" if run_time <= 1 else "seconds"
        msg = "message" if purged <= 1 else "messages"

        await ctx.respond(
            f"__Purged {purged} {msg} in {run_time} {time}...__",
            mode="repost",
            delete_after=3.5,
        )

    @command.desc("Delete the replied message.")
    @command.usage("del", reply=True)
    async def cmd_del(self, ctx: command.Context) -> Optional[str]:
        if not ctx.msg.reply_to_message:
            return "__Reply to a message.__"

        await asyncio.gather(
            ctx.msg.reply_to_message.delete(), ctx.msg.delete(), return_exceptions=True
        )

    @command.desc("Kick a user from the group")
    @command.usage("[user?] [reason?]", reply=True)
    @command.alias("punch")
    async def cmd_kick(self, ctx: command.Context) -> Optional[str]:
        if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
            return "__This command can only be used in groups.__"

        target, reason = await self._extract_target_and_rest(ctx)
        if target is None:
            return "__Reply to a user or specify a user to kick.__"

        target_id = _get_target_id(target)
        if self._is_self(target_id):
            return "__Cannot kick myself.__"

        chat_id = ctx.msg.chat.id
        try:
            await ctx.bot.client.ban_chat_member(chat_id=chat_id, user_id=target_id)
            await ctx.bot.client.unban_chat_member(chat_id=chat_id, user_id=target_id)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            await ctx.bot.client.ban_chat_member(chat_id=chat_id, user_id=target_id)
            await ctx.bot.client.unban_chat_member(chat_id=chat_id, user_id=target_id)
        except ChatAdminRequired:
            return "__I need to be an admin with ban permissions in this chat.__"
        except UserAdminInvalid:
            return "__Cannot kick an administrator or chat owner.__"
        except RightForbidden:
            return "__I don't have permission to kick users in this chat.__"
        except RPCError as e:
            return f"__Error: {e.MESSAGE or type(e).__name__}__"

        res = f"__Kicked {_format_target(target)}.__"
        if reason:
            res += f"\n**Reason:** {reason}"
        return res

    @command.desc("Ban a user from the group (permanently or temporarily)")
    @command.usage("[user?] [duration?] [reason?]", reply=True)
    @command.alias("b")
    async def cmd_ban(self, ctx: command.Context) -> Optional[str]:
        if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
            return "__This command can only be used in groups.__"

        target, rest = await self._extract_target_and_rest(ctx)
        if target is None:
            return "__Reply to a user or specify a user to ban.__"

        target_id = _get_target_id(target)
        if self._is_self(target_id):
            return "__Cannot ban myself.__"

        dur, reason = _extract_duration_and_reason(rest)
        until_date: Optional[datetime] = None
        if dur is not None:
            sec = dur.total_seconds()
            if sec < 30:
                return "__Duration must be at least 30 seconds.__"
            if sec > 366 * 86400:
                return "__Duration cannot exceed 366 days.__"
            until_date = datetime.now() + dur

        chat_id = ctx.msg.chat.id
        try:
            await ctx.bot.client.ban_chat_member(
                chat_id=chat_id, user_id=target_id, until_date=until_date
            )
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            await ctx.bot.client.ban_chat_member(
                chat_id=chat_id, user_id=target_id, until_date=until_date
            )
        except ChatAdminRequired:
            return "__I need to be an admin with ban permissions in this chat.__"
        except UserAdminInvalid:
            return "__Cannot ban an administrator or chat owner.__"
        except RightForbidden:
            return "__I don't have permission to ban users in this chat.__"
        except RPCError as e:
            return f"__Error: {e.MESSAGE or type(e).__name__}__"

        if dur is not None:
            res = f"__Banned {_format_target(target)} for {util.time.format_duration_td(dur)}.__"
        else:
            res = f"__Banned {_format_target(target)}.__"

        if reason:
            res += f"\n**Reason:** {reason}"
        return res

    @command.desc("Temporarily ban a user from the group")
    @command.usage("[user?] <duration> [reason?]", reply=True)
    @command.alias("tempban")
    async def cmd_tban(self, ctx: command.Context) -> Optional[str]:
        if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
            return "__This command can only be used in groups.__"

        target, rest = await self._extract_target_and_rest(ctx)
        if target is None:
            return "__Reply to a user or specify a user to temporarily ban.__"

        target_id = _get_target_id(target)
        if self._is_self(target_id):
            return "__Cannot ban myself.__"

        dur, reason = _extract_duration_and_reason(rest)
        if dur is None:
            return "__Please specify a valid duration (e.g. `1d`, `12h`, `30m`).__"

        sec = dur.total_seconds()
        if sec < 30:
            return "__Duration must be at least 30 seconds.__"
        if sec > 366 * 86400:
            return "__Duration cannot exceed 366 days.__"

        until_date = datetime.now() + dur
        chat_id = ctx.msg.chat.id
        try:
            await ctx.bot.client.ban_chat_member(
                chat_id=chat_id, user_id=target_id, until_date=until_date
            )
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            await ctx.bot.client.ban_chat_member(
                chat_id=chat_id, user_id=target_id, until_date=until_date
            )
        except ChatAdminRequired:
            return "__I need to be an admin with ban permissions in this chat.__"
        except UserAdminInvalid:
            return "__Cannot ban an administrator or chat owner.__"
        except RightForbidden:
            return "__I don't have permission to ban users in this chat.__"
        except RPCError as e:
            return f"__Error: {e.MESSAGE or type(e).__name__}__"

        res = f"__Banned {_format_target(target)} for {util.time.format_duration_td(dur)}.__"
        if reason:
            res += f"\n**Reason:** {reason}"
        return res

    @command.desc("Unban a user in the group")
    @command.usage("[user?]", reply=True)
    @command.alias("ub")
    async def cmd_unban(self, ctx: command.Context) -> Optional[str]:
        if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
            return "__This command can only be used in groups.__"

        target, _ = await self._extract_target_and_rest(ctx)
        if target is None:
            return "__Reply to a user or specify a user to unban.__"

        target_id = _get_target_id(target)
        chat_id = ctx.msg.chat.id
        try:
            await ctx.bot.client.unban_chat_member(chat_id=chat_id, user_id=target_id)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            await ctx.bot.client.unban_chat_member(chat_id=chat_id, user_id=target_id)
        except ChatAdminRequired:
            return "__I need to be an admin with ban permissions in this chat.__"
        except RightForbidden:
            return "__I don't have permission to unban users in this chat.__"
        except RPCError as e:
            return f"__Error: {e.MESSAGE or type(e).__name__}__"

        return f"__Unbanned {_format_target(target)}.__"

    @command.desc("Mute a user in the group (permanently or temporarily)")
    @command.usage("[user?] [duration?] [reason?]", reply=True)
    @command.alias("m")
    async def cmd_mute(self, ctx: command.Context) -> Optional[str]:
        if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
            return "__This command can only be used in groups.__"

        target, rest = await self._extract_target_and_rest(ctx)
        if target is None:
            return "__Reply to a user or specify a user to mute.__"

        target_id = _get_target_id(target)
        if self._is_self(target_id):
            return "__Cannot mute myself.__"

        dur, reason = _extract_duration_and_reason(rest)
        until_date: Optional[datetime] = None
        if dur is not None:
            sec = dur.total_seconds()
            if sec < 30:
                return "__Duration must be at least 30 seconds.__"
            if sec > 366 * 86400:
                return "__Duration cannot exceed 366 days.__"
            until_date = datetime.now() + dur

        chat_id = ctx.msg.chat.id
        try:
            await ctx.bot.client.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_id,
                permissions=ChatPermissions(),
                until_date=until_date,
            )
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            await ctx.bot.client.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_id,
                permissions=ChatPermissions(),
                until_date=until_date,
            )
        except ChatAdminRequired:
            return "__I need to be an admin with restrict permissions in this chat.__"
        except UserAdminInvalid:
            return "__Cannot mute an administrator or chat owner.__"
        except RightForbidden:
            return "__I don't have permission to mute users in this chat.__"
        except RPCError as e:
            return f"__Error: {e.MESSAGE or type(e).__name__}__"

        if dur is not None:
            res = f"__Muted {_format_target(target)} for {util.time.format_duration_td(dur)}.__"
        else:
            res = f"__Muted {_format_target(target)}.__"

        if reason:
            res += f"\n**Reason:** {reason}"
        return res

    @command.desc("Temporarily mute a user in the group")
    @command.usage("[user?] <duration> [reason?]", reply=True)
    @command.alias("tempmute")
    async def cmd_tmute(self, ctx: command.Context) -> Optional[str]:
        if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
            return "__This command can only be used in groups.__"

        target, rest = await self._extract_target_and_rest(ctx)
        if target is None:
            return "__Reply to a user or specify a user to temporarily mute.__"

        target_id = _get_target_id(target)
        if self._is_self(target_id):
            return "__Cannot mute myself.__"

        dur, reason = _extract_duration_and_reason(rest)
        if dur is None:
            return "__Please specify a valid duration (e.g. `1d`, `12h`, `30m`).__"

        sec = dur.total_seconds()
        if sec < 30:
            return "__Duration must be at least 30 seconds.__"
        if sec > 366 * 86400:
            return "__Duration cannot exceed 366 days.__"

        until_date = datetime.now() + dur
        chat_id = ctx.msg.chat.id
        try:
            await ctx.bot.client.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_id,
                permissions=ChatPermissions(),
                until_date=until_date,
            )
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            await ctx.bot.client.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_id,
                permissions=ChatPermissions(),
                until_date=until_date,
            )
        except ChatAdminRequired:
            return "__I need to be an admin with restrict permissions in this chat.__"
        except UserAdminInvalid:
            return "__Cannot mute an administrator or chat owner.__"
        except RightForbidden:
            return "__I don't have permission to mute users in this chat.__"
        except RPCError as e:
            return f"__Error: {e.MESSAGE or type(e).__name__}__"

        res = f"__Muted {_format_target(target)} for {util.time.format_duration_td(dur)}.__"
        if reason:
            res += f"\n**Reason:** {reason}"
        return res

    @command.desc("Unmute a user in the group")
    @command.usage("[user?]", reply=True)
    @command.alias("um")
    async def cmd_unmute(self, ctx: command.Context) -> Optional[str]:
        if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
            return "__This command can only be used in groups.__"

        target, _ = await self._extract_target_and_rest(ctx)
        if target is None:
            return "__Reply to a user or specify a user to unmute.__"

        target_id = _get_target_id(target)
        chat = ctx.msg.chat
        permissions = chat.permissions or ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_send_polls=True,
            can_invite_users=True,
        )

        try:
            await ctx.bot.client.restrict_chat_member(
                chat_id=chat.id,
                user_id=target_id,
                permissions=permissions,
            )
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            await ctx.bot.client.restrict_chat_member(
                chat_id=chat.id,
                user_id=target_id,
                permissions=permissions,
            )
        except ChatAdminRequired:
            return "__I need to be an admin with restrict permissions in this chat.__"
        except RightForbidden:
            return "__I don't have permission to unmute users in this chat.__"
        except RPCError as e:
            return f"__Error: {e.MESSAGE or type(e).__name__}__"

        return f"__Unmuted {_format_target(target)}.__"

    @command.desc("Promote a user to group administrator")
    @command.usage("[user?] [custom_title?]", reply=True)
    async def cmd_promote(self, ctx: command.Context) -> Optional[str]:
        if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
            return "__This command can only be used in groups.__"

        target, title = await self._extract_target_and_rest(ctx)
        if target is None:
            return "__Reply to a user or specify a user to promote.__"

        target_id = _get_target_id(target)
        if self._is_self(target_id):
            return "__Cannot promote myself.__"

        privileges = ChatPrivileges(
            can_manage_chat=True,
            can_delete_messages=True,
            can_manage_video_chats=True,
            can_restrict_members=True,
            can_promote_members=False,
            can_change_info=True,
            can_invite_users=True,
            can_pin_messages=True,
        )

        chat_id = ctx.msg.chat.id
        try:
            await ctx.bot.client.promote_chat_member(
                chat_id=chat_id, user_id=target_id, privileges=privileges
            )
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            await ctx.bot.client.promote_chat_member(
                chat_id=chat_id, user_id=target_id, privileges=privileges
            )
        except ChatAdminRequired:
            return "__I need to be an admin with promote permissions in this chat.__"
        except RightForbidden:
            return "__I don't have permission to promote members in this chat.__"
        except RPCError as e:
            return f"__Error: {e.MESSAGE or type(e).__name__}__"

        if title:
            try:
                await ctx.bot.client.set_administrator_title(
                    chat_id=chat_id, user_id=target_id, title=title
                )
            except Exception as e:
                self.log.debug(f"Could not set custom title: {e}")

        res = f"__Promoted {_format_target(target)} to administrator.__"
        if title:
            res += f"\n**Title:** {title}"
        return res

    @command.desc("Demote an administrator back to regular member")
    @command.usage("[user?]", reply=True)
    async def cmd_demote(self, ctx: command.Context) -> Optional[str]:
        if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
            return "__This command can only be used in groups.__"

        target, _ = await self._extract_target_and_rest(ctx)
        if target is None:
            return "__Reply to a user or specify a user to demote.__"

        target_id = _get_target_id(target)
        if self._is_self(target_id):
            return "__Cannot demote myself.__"

        privileges = ChatPrivileges(
            can_manage_chat=False,
            can_delete_messages=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_post_messages=False,
            can_edit_messages=False,
        )

        chat_id = ctx.msg.chat.id
        try:
            await ctx.bot.client.promote_chat_member(
                chat_id=chat_id, user_id=target_id, privileges=privileges
            )
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            await ctx.bot.client.promote_chat_member(
                chat_id=chat_id, user_id=target_id, privileges=privileges
            )
        except ChatAdminRequired:
            return "__I need to be an admin with promote permissions in this chat.__"
        except UserAdminInvalid:
            return "__Cannot demote chat owner or users not promoted by me.__"
        except RightForbidden:
            return "__I don't have permission to demote members in this chat.__"
        except RPCError as e:
            return f"__Error: {e.MESSAGE or type(e).__name__}__"

        return f"__Demoted {_format_target(target)} to regular member.__"

    @command.desc("Pin a message in the chat")
    @command.usage("[loud | silent]", reply=True)
    @command.alias("cpin")
    async def cmd_pin(self, ctx: command.Context) -> Optional[str]:
        if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
            return "__This command can only be used in groups.__"

        if not ctx.msg.reply_to_message:
            return "__Reply to a message to pin it.__"

        silent = True
        if ctx.input and ctx.input.strip().lower() in ("loud", "notify", "alert"):
            silent = False

        chat_id = ctx.msg.chat.id
        message_id = ctx.msg.reply_to_message.id
        try:
            await ctx.bot.client.pin_chat_message(
                chat_id=chat_id,
                message_id=message_id,
                disable_notification=silent,
                both_sides=True,
            )
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            await ctx.bot.client.pin_chat_message(
                chat_id=chat_id,
                message_id=message_id,
                disable_notification=silent,
                both_sides=True,
            )
        except ChatAdminRequired:
            return "__I need to be an admin with pin permissions to do this.__"
        except RightForbidden:
            return "__I don't have permission to pin messages in this chat.__"
        except RPCError as e:
            return f"__Error: {e.MESSAGE or type(e).__name__}__"

        return f"__Pinned [message]({ctx.msg.reply_to_message.link}).__"

    @command.desc("Unpin a message or all messages in the chat")
    @command.usage("['all'?]", optional=True, reply=True)
    async def cmd_unpin(self, ctx: command.Context) -> Optional[str]:
        if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
            return "__This command can only be used in groups.__"

        chat_id = ctx.msg.chat.id
        if ctx.input and ctx.input.strip().lower() == "all":
            try:
                await ctx.bot.client.unpin_all_chat_messages(chat_id=chat_id)
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                await ctx.bot.client.unpin_all_chat_messages(chat_id=chat_id)
            except ChatAdminRequired:
                return "__I need to be an admin with pin permissions to do this.__"
            except RightForbidden:
                return "__I don't have permission to unpin messages in this chat.__"
            except RPCError as e:
                return f"__Error: {e.MESSAGE or type(e).__name__}__"
            return "__Unpinned all messages in this chat.__"

        if not ctx.msg.reply_to_message:
            return "__Reply to a message to unpin it, or use__ `unpin all` __to unpin all.__"

        message_id = ctx.msg.reply_to_message.id
        try:
            await ctx.bot.client.unpin_chat_message(
                chat_id=chat_id,
                message_id=message_id,
            )
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            await ctx.bot.client.unpin_chat_message(
                chat_id=chat_id,
                message_id=message_id,
            )
        except ChatAdminRequired:
            return "__I need to be an admin with pin permissions to do this.__"
        except RightForbidden:
            return "__I don't have permission to unpin messages in this chat.__"
        except RPCError as e:
            return f"__Error: {e.MESSAGE or type(e).__name__}__"

        return f"__Unpinned [message]({ctx.msg.reply_to_message.link}).__"

    @command.desc("Set or disable slow mode delay for the group")
    @command.alias("slow")
    @command.usage("[seconds | 'off']", optional=True)
    async def cmd_slowmode(self, ctx: command.Context) -> Optional[str]:
        if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
            return "__This command can only be used in groups.__"

        if not ctx.input:
            current = getattr(ctx.msg.chat, "slow_mode_delay", None)
            if current:
                return f"__Current slow mode delay is__ `{current}` __seconds.__"
            return "__Usage:__ `slowmode [seconds | 'off']`"

        raw = ctx.input.strip().lower()
        if raw in ("off", "disable", "disabled", "0"):
            seconds = 0
        else:
            td = _parse_duration(raw)
            if td is not None:
                seconds = int(td.total_seconds())
            elif raw.isdigit():
                seconds = int(raw)
            else:
                return "__Invalid duration. Valid intervals: 0 (off), 10s, 30s, 1m, 5m, 15m, 1h.__"

        allowed = [0, 10, 30, 60, 300, 900, 3600]
        if seconds not in allowed:
            return "__Telegram only supports slow mode intervals: 0 (off), 10s, 30s, 60s (1m), 300s (5m), 900s (15m), 3600s (1h).__"

        chat_id = ctx.msg.chat.id
        try:
            await ctx.bot.client.set_slow_mode(chat_id=chat_id, seconds=seconds)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            await ctx.bot.client.set_slow_mode(chat_id=chat_id, seconds=seconds)
        except ChatAdminRequired:
            return "__I need to be an admin with change info permissions to set slow mode.__"
        except RightForbidden:
            return "__I don't have permission to change slow mode in this chat.__"
        except RPCError as e:
            return f"__Error: {e.MESSAGE or type(e).__name__}__"

        if seconds == 0:
            return "__Slow mode has been disabled.__"
        return f"__Slow mode set to__ `{seconds}` __seconds.__"

    @command.desc("Find or clean deleted accounts in the group")
    @command.alias("kickdeleted")
    @command.usage("['clean'?]", optional=True)
    async def cmd_zombies(self, ctx: command.Context) -> Optional[str]:
        if ctx.msg.chat.type in (ChatType.PRIVATE, ChatType.BOT):
            return "__This command can only be used in groups.__"

        clean = bool(
            ctx.input and ctx.input.strip().lower() in ("clean", "kick", "remove", "yes")
        )
        await ctx.respond("__Scanning for deleted accounts...__")

        chat_id = ctx.msg.chat.id
        count = 0
        cleaned = 0
        try:
            async for member in ctx.bot.client.get_chat_members(chat_id):
                if member.user and member.user.is_deleted:
                    count += 1
                    if clean:
                        try:
                            await ctx.bot.client.ban_chat_member(
                                chat_id=chat_id, user_id=member.user.id
                            )
                            await ctx.bot.client.unban_chat_member(
                                chat_id=chat_id, user_id=member.user.id
                            )
                            cleaned += 1
                        except FloodWait as e:
                            await asyncio.sleep(e.value + 1)
                            await ctx.bot.client.ban_chat_member(
                                chat_id=chat_id, user_id=member.user.id
                            )
                            await ctx.bot.client.unban_chat_member(
                                chat_id=chat_id, user_id=member.user.id
                            )
                            cleaned += 1
                        except Exception:
                            pass
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
        except ChatAdminRequired:
            return "__I need to be an admin with member permissions in this chat.__"
        except RightForbidden:
            return "__I don't have permission to view or manage members in this chat.__"
        except RPCError as e:
            return f"__Error: {e.MESSAGE or type(e).__name__}__"

        if count == 0:
            return "__No deleted accounts found in this chat.__"

        if clean:
            return f"__Cleaned__ `{cleaned}` / `{count}` __deleted accounts.__"
        return f"__Found__ `{count}` __deleted accounts. Use__ `zombies clean` __to remove them.__"

    @command.desc("Purge your own messages in this chat")
    @command.alias("pme")
    @command.usage("[count?]", optional=True, reply=True)
    async def cmd_purgeme(self, ctx: command.Context) -> Optional[str]:
        my_id = getattr(self.bot, "uid", None) or getattr(
            getattr(self.bot, "user", None), "id", None
        )
        if my_id is None:
            try:
                me = await ctx.bot.client.get_me()
                my_id = me.id
            except Exception:
                my_id = None

        chat_id = ctx.msg.chat.id
        msg_ids: list[int] = []

        if ctx.msg.reply_to_message:
            start_id = ctx.msg.reply_to_message.id
            end_id = ctx.msg.id
            try:
                async for msg in ctx.bot.client.get_chat_history(
                    chat_id, limit=max(1, end_id - start_id + 1)
                ):
                    if msg.id < start_id:
                        break
                    if (
                        my_id is not None
                        and msg.from_user
                        and msg.from_user.id == my_id
                    ) or (my_id is None and msg.outgoing):
                        msg_ids.append(msg.id)
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
        else:
            count = 100
            if ctx.input and ctx.input.strip().isdigit():
                count = int(ctx.input.strip())

            try:
                async for msg in ctx.bot.client.get_chat_history(
                    chat_id, limit=count * 3
                ):
                    if (
                        my_id is not None
                        and msg.from_user
                        and msg.from_user.id == my_id
                    ) or (my_id is None and msg.outgoing):
                        msg_ids.append(msg.id)
                        if len(msg_ids) >= count:
                            break
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)

        if not msg_ids:
            return "__No messages found to purge.__"

        purged = 0
        for i in range(0, len(msg_ids), 100):
            batch = msg_ids[i : i + 100]
            try:
                purged += await ctx.bot.client.delete_messages(
                    chat_id=chat_id,
                    message_ids=batch,
                    revoke=True,
                )
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                purged += await ctx.bot.client.delete_messages(
                    chat_id=chat_id,
                    message_ids=batch,
                    revoke=True,
                )
            except Exception:
                pass

        msg_str = "message" if purged <= 1 else "messages"
        await ctx.respond(
            f"__Purged {purged} {msg_str} of your own.__",
            mode="repost",
            delete_after=3.5,
        )
