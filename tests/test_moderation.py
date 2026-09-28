import asyncio
from datetime import datetime, timedelta
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from pyrogram.enums import ChatType
from pyrogram.errors import ChatAdminRequired, UserAdminInvalid, RightForbidden
from pyrogram.types import Chat, ChatMember, Message, User

from caligo.modules.moderation import (
    Moderation,
    _parse_duration,
    _extract_duration_and_reason,
    _format_target,
    _get_target_id,
)


class TestModerationModule(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = MagicMock()
        self.bot.uid = 12345
        self.bot.user = MagicMock()
        self.bot.user.id = 12345
        self.bot.client = MagicMock()
        self.mod = Moderation(self.bot)

        # Base mock chat
        self.chat = MagicMock(spec=Chat)
        self.chat.id = -1001234567890
        self.chat.type = ChatType.SUPERGROUP
        self.chat.permissions = None
        self.chat.slow_mode_delay = 0

    def create_ctx(self):
        ctx = MagicMock()
        ctx.bot = self.bot
        ctx.msg = MagicMock(spec=Message)
        ctx.msg.chat = self.chat
        ctx.msg.reply_to_message = None
        ctx.msg.entities = []
        ctx.args = []
        ctx.input = ""
        ctx.respond = AsyncMock()
        return ctx

    def test_duration_parser(self):
        self.assertEqual(_parse_duration("10s"), timedelta(seconds=10))
        self.assertEqual(_parse_duration("30m"), timedelta(minutes=30))
        self.assertEqual(_parse_duration("2h"), timedelta(hours=2))
        self.assertEqual(_parse_duration("1d"), timedelta(days=1))
        self.assertEqual(_parse_duration("2w"), timedelta(weeks=2))
        self.assertEqual(_parse_duration("1d12h"), timedelta(days=1, hours=12))
        self.assertIsNone(_parse_duration("invalid"))
        self.assertIsNone(_parse_duration("1d spam"))

    def test_duration_and_reason_extractor(self):
        dur, reason = _extract_duration_and_reason("1d bad behaviour")
        self.assertEqual(dur, timedelta(days=1))
        self.assertEqual(reason, "bad behaviour")

        dur, reason = _extract_duration_and_reason("2h")
        self.assertEqual(dur, timedelta(hours=2))
        self.assertIsNone(reason)

        dur, reason = _extract_duration_and_reason("bad behaviour")
        self.assertIsNone(dur)
        self.assertEqual(reason, "bad behaviour")

        dur, reason = _extract_duration_and_reason(None)
        self.assertIsNone(dur)
        self.assertIsNone(reason)

    def test_format_target_and_id(self):
        user = MagicMock(spec=User)
        user.id = 9999
        user.username = "testuser"
        user.first_name = "Test"
        user.last_name = "User"

        self.assertEqual(_get_target_id(user), 9999)
        self.assertEqual(_get_target_id(5555), 5555)

        mention = _format_target(user)
        self.assertIn("@testuser", mention)

        raw_id_mention = _format_target(5555)
        self.assertEqual(raw_id_mention, "[5555](tg://user?id=5555)")

    async def test_cmd_private_chat_rejection(self):
        ctx = self.create_ctx()
        ctx.msg.chat.type = ChatType.PRIVATE
        res = await self.mod.cmd_kick(ctx)
        self.assertIn("can only be used in groups", res)

        res = await self.mod.cmd_ban(ctx)
        self.assertIn("can only be used in groups", res)

        res = await self.mod.cmd_mute(ctx)
        self.assertIn("can only be used in groups", res)

        res = await self.mod.cmd_pin(ctx)
        self.assertIn("can only be used in groups", res)

    async def test_cmd_kick_success(self):
        ctx = self.create_ctx()
        ctx.args = ["67890", "spamming"]
        ctx.input = "67890 spamming"

        target_user = MagicMock(spec=User)
        target_user.id = 67890
        target_user.username = "spammer"
        self.bot.client.get_users = AsyncMock(return_value=target_user)
        self.bot.client.ban_chat_member = AsyncMock()
        self.bot.client.unban_chat_member = AsyncMock()

        res = await self.mod.cmd_kick(ctx)
        self.assertIn("Kicked", res)
        self.assertIn("@spammer", res)
        self.assertIn("spamming", res)
        self.bot.client.ban_chat_member.assert_called_once_with(
            chat_id=self.chat.id, user_id=67890
        )
        self.bot.client.unban_chat_member.assert_called_once_with(
            chat_id=self.chat.id, user_id=67890
        )

    async def test_cmd_kick_self_protection(self):
        ctx = self.create_ctx()
        ctx.args = ["12345"]
        ctx.input = "12345"

        target_user = MagicMock(spec=User)
        target_user.id = 12345
        target_user.username = "myself"
        self.bot.client.get_users = AsyncMock(return_value=target_user)

        res = await self.mod.cmd_kick(ctx)
        self.assertIn("Cannot kick myself", res)

    async def test_cmd_ban_permanent_and_temporary(self):
        ctx = self.create_ctx()
        target_user = MagicMock(spec=User)
        target_user.id = 7777
        target_user.username = "badguy"
        ctx.msg.reply_to_message = MagicMock()
        ctx.msg.reply_to_message.from_user = target_user
        ctx.msg.reply_to_message.sender_chat = None

        self.bot.client.ban_chat_member = AsyncMock()

        # Permanent ban
        ctx.input = "trolling"
        ctx.args = ["trolling"]
        res = await self.mod.cmd_ban(ctx)
        self.assertIn("Banned", res)
        self.assertIn("trolling", res)
        self.bot.client.ban_chat_member.assert_called_with(
            chat_id=self.chat.id, user_id=7777, until_date=None
        )

        # Temporary ban
        ctx.input = "1d serious trolling"
        ctx.args = ["1d", "serious", "trolling"]
        res = await self.mod.cmd_ban(ctx)
        self.assertIn("Banned", res)
        self.assertIn("1d", res)
        self.assertIn("serious trolling", res)
        # Check until_date was passed
        call_kwargs = self.bot.client.ban_chat_member.call_args.kwargs
        self.assertIsNotNone(call_kwargs["until_date"])

    async def test_cmd_tban_validation(self):
        ctx = self.create_ctx()
        target_user = MagicMock(spec=User)
        target_user.id = 7777
        target_user.username = "badguy"
        ctx.msg.reply_to_message = MagicMock()
        ctx.msg.reply_to_message.from_user = target_user
        ctx.msg.reply_to_message.sender_chat = None

        # Missing duration
        ctx.input = "no duration here"
        ctx.args = ["no", "duration", "here"]
        res = await self.mod.cmd_tban(ctx)
        self.assertIn("specify a valid duration", res)

        # Duration too short (< 30s)
        ctx.input = "10s too short"
        ctx.args = ["10s", "too", "short"]
        res = await self.mod.cmd_tban(ctx)
        self.assertIn("must be at least 30 seconds", res)

    async def test_cmd_unban(self):
        ctx = self.create_ctx()
        ctx.args = ["7777"]
        ctx.input = "7777"

        target_user = MagicMock(spec=User)
        target_user.id = 7777
        target_user.username = "reformed"
        self.bot.client.get_users = AsyncMock(return_value=target_user)
        self.bot.client.unban_chat_member = AsyncMock()

        res = await self.mod.cmd_unban(ctx)
        self.assertIn("Unbanned", res)
        self.bot.client.unban_chat_member.assert_called_once_with(
            chat_id=self.chat.id, user_id=7777
        )

    async def test_cmd_mute_and_unmute(self):
        ctx = self.create_ctx()
        target_user = MagicMock(spec=User)
        target_user.id = 8888
        target_user.username = "loudperson"
        ctx.msg.reply_to_message = MagicMock()
        ctx.msg.reply_to_message.from_user = target_user
        ctx.msg.reply_to_message.sender_chat = None

        self.bot.client.restrict_chat_member = AsyncMock()

        # Mute
        ctx.input = "1h calm down"
        ctx.args = ["1h", "calm", "down"]
        res = await self.mod.cmd_mute(ctx)
        self.assertIn("Muted", res)
        self.assertIn("1h", res)
        self.assertIn("calm down", res)
        self.bot.client.restrict_chat_member.assert_called_once()

        # Unmute
        ctx.input = ""
        ctx.args = []
        res = await self.mod.cmd_unmute(ctx)
        self.assertIn("Unmuted", res)

    async def test_cmd_promote_and_demote(self):
        ctx = self.create_ctx()
        ctx.args = ["9999", "AdminLead"]
        ctx.input = "9999 AdminLead"

        target_user = MagicMock(spec=User)
        target_user.id = 9999
        target_user.username = "newadmin"
        self.bot.client.get_users = AsyncMock(return_value=target_user)
        self.bot.client.promote_chat_member = AsyncMock()
        self.bot.client.set_administrator_title = AsyncMock()

        # Promote
        res = await self.mod.cmd_promote(ctx)
        self.assertIn("Promoted", res)
        self.assertIn("AdminLead", res)
        self.bot.client.promote_chat_member.assert_called_once()
        self.bot.client.set_administrator_title.assert_called_once_with(
            chat_id=self.chat.id, user_id=9999, title="AdminLead"
        )

        # Demote
        ctx.args = ["9999"]
        ctx.input = "9999"
        res = await self.mod.cmd_demote(ctx)
        self.assertIn("Demoted", res)

    async def test_cmd_pin_and_unpin(self):
        ctx = self.create_ctx()
        reply_msg = MagicMock(spec=Message)
        reply_msg.id = 54321
        reply_msg.link = "https://t.me/c/12345/54321"
        ctx.msg.reply_to_message = reply_msg

        self.bot.client.pin_chat_message = AsyncMock()
        self.bot.client.unpin_chat_message = AsyncMock()
        self.bot.client.unpin_all_chat_messages = AsyncMock()

        # Pin
        ctx.input = "silent"
        res = await self.mod.cmd_pin(ctx)
        self.assertIn("Pinned", res)
        self.bot.client.pin_chat_message.assert_called_once_with(
            chat_id=self.chat.id, message_id=54321, disable_notification=True, both_sides=True
        )

        # Unpin single
        ctx.input = ""
        res = await self.mod.cmd_unpin(ctx)
        self.assertIn("Unpinned", res)
        self.bot.client.unpin_chat_message.assert_called_once_with(
            chat_id=self.chat.id, message_id=54321
        )

        # Unpin all
        ctx.input = "all"
        res = await self.mod.cmd_unpin(ctx)
        self.assertIn("Unpinned all", res)
        self.bot.client.unpin_all_chat_messages.assert_called_once_with(chat_id=self.chat.id)

    async def test_cmd_slowmode(self):
        ctx = self.create_ctx()
        self.bot.client.set_slow_mode = AsyncMock()

        # Set 10s
        ctx.input = "10s"
        res = await self.mod.cmd_slowmode(ctx)
        self.assertIn("Slow mode set to", res)
        self.assertIn("10", res)
        self.bot.client.set_slow_mode.assert_called_with(chat_id=self.chat.id, seconds=10)

        # Set off
        ctx.input = "off"
        res = await self.mod.cmd_slowmode(ctx)
        self.assertIn("Slow mode has been disabled", res)
        self.bot.client.set_slow_mode.assert_called_with(chat_id=self.chat.id, seconds=0)

        # Invalid interval (e.g. 45 seconds is not in allowed Telegram intervals)
        ctx.input = "45s"
        res = await self.mod.cmd_slowmode(ctx)
        self.assertIn("Telegram only supports slow mode intervals", res)

    async def test_cmd_zombies(self):
        ctx = self.create_ctx()

        m1 = MagicMock(spec=ChatMember)
        m1.user = MagicMock(spec=User)
        m1.user.id = 111
        m1.user.is_deleted = True

        m2 = MagicMock(spec=ChatMember)
        m2.user = MagicMock(spec=User)
        m2.user.id = 222
        m2.user.is_deleted = False

        async def fake_members(chat_id):
            for member in [m1, m2]:
                yield member

        self.bot.client.get_chat_members = fake_members
        self.bot.client.ban_chat_member = AsyncMock()
        self.bot.client.unban_chat_member = AsyncMock()

        # Scan only
        ctx.input = ""
        res = await self.mod.cmd_zombies(ctx)
        self.assertIn("Found", res)
        self.assertIn("1", res)
        self.assertIn("deleted accounts", res)

        # Clean
        ctx.input = "clean"
        res = await self.mod.cmd_zombies(ctx)
        self.assertIn("Cleaned", res)
        self.assertIn("1", res)
        self.bot.client.ban_chat_member.assert_called_once_with(
            chat_id=self.chat.id, user_id=111
        )

    async def test_cmd_purgeme(self):
        ctx = self.create_ctx()
        ctx.input = "5"

        msg1 = MagicMock(spec=Message)
        msg1.id = 101
        msg1.from_user = MagicMock(spec=User)
        msg1.from_user.id = 12345
        msg1.outgoing = True

        msg2 = MagicMock(spec=Message)
        msg2.id = 102
        msg2.from_user = MagicMock(spec=User)
        msg2.from_user.id = 99999
        msg2.outgoing = False

        msg3 = MagicMock(spec=Message)
        msg3.id = 103
        msg3.from_user = MagicMock(spec=User)
        msg3.from_user.id = 12345
        msg3.outgoing = True

        async def fake_history(chat_id, limit=300):
            for m in [msg3, msg2, msg1]:
                yield m

        self.bot.client.get_chat_history = fake_history
        self.bot.client.delete_messages = AsyncMock(return_value=2)

        await self.mod.cmd_purgeme(ctx)
        self.bot.client.delete_messages.assert_called_once_with(
            chat_id=self.chat.id,
            message_ids=[103, 101],
            revoke=True,
        )
        ctx.respond.assert_called_once()
        self.assertIn("Purged 2 messages of your own", ctx.respond.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
