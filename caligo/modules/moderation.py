import asyncio
from datetime import datetime
from typing import ClassVar, Optional

from pyrogram.enums import ChatMembersFilter, ChatType
from pyrogram.types import ChatMember

from caligo import command, module


class Moderation(module.Module):
    name: ClassVar[str] = "Moderation"

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
        async for member in self.bot.client.get_chat_members(
            chat, filter=user_filter
        ):  # type: ignore
            mention_text += f"[\u200b](tg://user?id={member.user.id})"

            mention_slots -= 1
            if mention_slots == 0:
                break

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
                purged += await ctx.bot.client.delete_messages(
                    chat_id=ctx.msg.chat.id,
                    message_ids=messages_id,
                )
                messages_id = []

        if messages_id:
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
