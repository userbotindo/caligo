""" Purge module is a function to delete messages easily. """
import asyncio

from typing import ClassVar
from datetime import datetime
from pyrogram.errors import MessageDeleteForbidden
from .. import command, module


class PurgeModule(module.Module):
    name: ClassVar[str] = "Purge"

    @command.desc(
        "reply to a message, mark as start until your purge command. "
    )
    @command.usage("purge", reply=True)
    async def cmd_purge(self, ctx: command.Context):
        """ This function need permission to delete messages. """
        if ctx.msg.chat.type in ["group", "supergroup"]:
            perm = (await ctx.bot.client.get_chat_member(ctx.msg.chat.id, "me")).can_delete_messages
            if perm is not True:
                return "**You can't delete message in this chat..**"
        await ctx.respond("Purging...")
        msg_ids = []
        purging = 0
        t_s = datetime.now()
        for msg_id in range(ctx.msg.reply_to_message.message_id, ctx.msg.message_id):
            msg_ids.append(msg_id)
            if len(msg_ids) == 100:
                await ctx.bot.client.delete_messages(
                    chat_id=ctx.msg.chat.id,
                    message_ids=msg_ids,
                    revoke=True,
                )
                purging += len(msg_ids)
                msg_ids = []

        if msg_ids:
            await ctx.bot.client.delete_messages(
                chat_id=ctx.msg.chat.id,
                message_ids=msg_ids,
                revoke=True,
            )
            purging += len(msg_ids)
        t_e = datetime.now()
        run_time = (t_e - t_s).seconds
        await ctx.respond("`Purged {} messages in {} second...`".format(purging, run_time))
        await asyncio.sleep(5)
        await ctx.msg.delete()

    @command.desc("This module, can delete your message, just reply message you wanna deleted.")
    @command.usage("del", reply=True)
    async def cmd_del(self, ctx: command.Context):
        """ reply to message as target, this function will delete that. """
        if ctx.msg.reply_to_message:
            try:
                await ctx.msg.reply_to_message.delete(revoke=True)
            except MessageDeleteForbidden:
                pass
            await ctx.msg.delete()
