import asyncio
from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from pyrogram import enums, errors, types
from pyrogram.enums import ChatMemberStatus, ChatType, ParseMode

from caligo import command
from caligo.modules.logging import Logging
from caligo.modules.pmguard import PMGuard, DEFAULT_WARN_TEMPLATE


class TestLoggingAndPMGuard(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Create mock Caligo bot
        self.bot = MagicMock()
        self.bot.prefix = "."
        self.bot.uid = 111111111
        self.bot.user = MagicMock()
        self.bot.user.id = 111111111
        self.bot.user.username = "botowner"
        self.bot.bot_uid = 999999999
        self.bot.helper_initialized = True
        self.bot.redact_message = MagicMock(side_effect=lambda t: t)

        # Mock Pyrogram clients
        self.client = AsyncMock()
        self.client_helper = AsyncMock()
        self.client_helper.is_connected = True
        self.bot.client = self.client
        self.bot.client_helper = self.client_helper

        # Mock MongoDB
        self.mongo_collections = {}

        def get_coll(name):
            if name not in self.mongo_collections:
                coll = AsyncMock()
                coll_data = {}

                async def find_one(filter_dict=None, projection=None):
                    doc_id = (filter_dict or {}).get("_id", 0)
                    return coll_data.get(doc_id)

                async def update_one(filter_dict, update_dict, upsert=False):
                    doc_id = (filter_dict or {}).get("_id", 0)
                    doc = coll_data.setdefault(doc_id, {"_id": doc_id})
                    if "$set" in update_dict:
                        doc.update(update_dict["$set"])
                    return MagicMock(acknowledged=True)

                async def delete_one(filter_dict):
                    doc_id = (filter_dict or {}).get("_id", 0)
                    coll_data.pop(doc_id, None)
                    return MagicMock(deleted_count=1)

                async def find_one_and_update(filter_dict, update_dict, upsert=False, return_document=None):
                    doc_id = (filter_dict or {}).get("_id", 0)
                    doc = coll_data.setdefault(doc_id, {"_id": doc_id})
                    if "$inc" in update_dict:
                        for k, v in update_dict["$inc"].items():
                            doc[k] = doc.get(k, 0) + v
                    if "$set" in update_dict:
                        doc.update(update_dict["$set"])
                    return dict(doc)

                coll.find_one = find_one
                coll.update_one = update_one
                coll.delete_one = delete_one
                coll.find_one_and_update = find_one_and_update
                coll._data = coll_data
                self.mongo_collections[name] = coll
            return self.mongo_collections[name]

        self.bot.db = MagicMock()
        self.bot.db.get_collection.side_effect = get_coll
        self.bot.db.__getitem__.side_effect = get_coll
        self.bot.modules = {}

        # Instantiate modules
        self.log_mod = Logging(self.bot)
        await self.log_mod.on_load()
        self.bot.modules["Logging"] = self.log_mod

        self.pm_mod = PMGuard(self.bot)
        await self.pm_mod.on_load()
        self.bot.modules["PMGuard"] = self.pm_mod

    # =========================================================================
    # Logging Module Tests
    # =========================================================================
    async def test_logging_default_state(self):
        self.assertFalse(self.log_mod.enabled)
        self.assertIsNone(self.log_mod.chat_id)

    async def test_logging_commands_on_off_status(self):
        ctx = MagicMock()
        ctx.input = "on"
        res = await self.log_mod.cmd_logging(ctx)
        self.assertIn("Logging enabled", res)
        self.assertTrue(self.log_mod.enabled)

        ctx.input = ""
        res = await self.log_mod.cmd_logging(ctx)
        self.assertIn("enabled", res)

        ctx.input = "off"
        res = await self.log_mod.cmd_logging(ctx)
        self.assertIn("Logging disabled", res)
        self.assertFalse(self.log_mod.enabled)

    async def test_setlog_private_chat_success(self):
        ctx = MagicMock()
        ctx.input = "123456789"
        mock_chat = MagicMock()
        mock_chat.id = 123456789
        mock_chat.type = ChatType.PRIVATE
        mock_chat.first_name = "TestUser"
        mock_chat.last_name = None
        self.client.get_chat.return_value = mock_chat

        res = await self.log_mod.cmd_setlog(ctx)
        self.assertIn("123456789", res)
        self.assertEqual(self.log_mod.chat_id, 123456789)

    async def test_setlog_without_args_in_private_chat(self):
        ctx = MagicMock()
        ctx.input = ""
        ctx.msg.chat.id = 555666777
        ctx.msg.chat.type = ChatType.PRIVATE
        ctx.msg.chat.first_name = "MyLogChat"
        ctx.msg.chat.last_name = None

        res = await self.log_mod.cmd_setlog(ctx)
        self.assertIn("555666777", res)
        self.assertEqual(self.log_mod.chat_id, 555666777)

    async def test_setlog_without_args_in_public_group(self):
        ctx = MagicMock()
        ctx.input = ""
        ctx.msg.chat.id = -100987654321
        ctx.msg.chat.type = ChatType.SUPERGROUP
        ctx.msg.chat.title = "Public Group"
        ctx.msg.chat.username = "publicgroup"

        res = await self.log_mod.cmd_setlog(ctx)
        self.assertIn("Cannot set a public chat or channel", res)
        self.assertIsNone(self.log_mod.chat_id)

    async def test_setlog_replaces_old_destination(self):
        self.log_mod.chat_id = 111111

        ctx = MagicMock()
        ctx.input = "222222"
        mock_chat = MagicMock()
        mock_chat.id = 222222
        mock_chat.type = ChatType.PRIVATE
        mock_chat.first_name = "NewLogChat"
        mock_chat.last_name = None
        self.client.get_chat.return_value = mock_chat

        res = await self.log_mod.cmd_setlog(ctx)
        self.assertIn("222222", res)
        self.assertEqual(self.log_mod.chat_id, 222222)

    async def test_setlog_private_channel_success(self):
        ctx = MagicMock()
        ctx.input = "-1001234567890"
        mock_chat = MagicMock()
        mock_chat.id = -1001234567890
        mock_chat.type = ChatType.CHANNEL
        mock_chat.title = "My Private Log Channel"
        mock_chat.username = None
        self.client.get_chat.return_value = mock_chat

        res = await self.log_mod.cmd_setlog(ctx)
        self.assertIn("-1001234567890", res)
        self.assertEqual(self.log_mod.chat_id, -1001234567890)

    async def test_setlog_rejects_public_channel(self):
        ctx = MagicMock()
        ctx.input = "public_channel"
        mock_chat = MagicMock()
        mock_chat.id = -1001234567890
        mock_chat.type = ChatType.CHANNEL
        mock_chat.username = "public_channel"
        self.client.get_chat.return_value = mock_chat

        res = await self.log_mod.cmd_setlog(ctx)
        self.assertIn("Cannot set a public chat or channel", res)
        self.assertIsNone(self.log_mod.chat_id)

    async def test_clearlog(self):
        self.log_mod.chat_id = 123456789
        ctx = MagicMock()
        res = await self.log_mod.cmd_clearlog(ctx)
        self.assertIn("Logging destination cleared", res)
        self.assertIsNone(self.log_mod.chat_id)

    async def test_send_log_helper_bot_when_configured(self):
        self.log_mod.enabled = True
        self.log_mod.chat_id = 123456789

        sent = await self.log_mod.send_log("<b>Test Log</b>")
        self.assertTrue(sent)
        self.client_helper.send_message.assert_called_once()
        args, kwargs = self.client_helper.send_message.call_args
        self.assertEqual(args[0], 123456789)
        self.assertEqual(args[1], "<b>Test Log</b>")
        self.client.send_message.assert_not_called()

    async def test_send_log_fallback_to_owner_when_no_destination(self):
        self.log_mod.enabled = True
        self.log_mod.chat_id = None

        sent = await self.log_mod.send_log("<b>Test Fallback Log</b>")
        self.assertTrue(sent)
        self.client_helper.send_message.assert_called_once()
        args, kwargs = self.client_helper.send_message.call_args
        self.assertEqual(args[0], self.bot.uid)

    async def test_send_log_fallback_to_userbot_when_helper_fails(self):
        self.log_mod.enabled = True
        self.log_mod.chat_id = 123456789
        self.client_helper.send_message.side_effect = errors.RPCError("Helper Bot Blocked")

        sent = await self.log_mod.send_log("<b>Test Log</b>")
        self.assertTrue(sent)
        self.client.send_message.assert_called_once()
        args, kwargs = self.client.send_message.call_args
        self.assertEqual(args[0], 123456789)

    async def test_mention_logging_in_group(self):
        self.log_mod.enabled = True
        self.log_mod.chat_id = 123456789

        msg = MagicMock(spec=types.Message)
        msg.outgoing = False
        msg.chat = MagicMock(spec=types.Chat)
        msg.chat.type = ChatType.SUPERGROUP
        msg.chat.id = -1001122334455
        msg.chat.title = "Test Group"
        msg.chat.username = "testgroup"
        msg.id = 555
        msg.from_user = MagicMock(spec=types.User)
        msg.from_user.id = 222222222
        msg.from_user.first_name = "Alice"
        msg.from_user.last_name = "Smith"
        msg.from_user.username = "alicesmith"
        msg.text = "Hello @botowner how are you?"
        msg.caption = None
        msg.reply_to_message = None

        # Mention entity
        entity = types.MessageEntity(
            type=enums.MessageEntityType.MENTION,
            offset=6,
            length=9,
        )
        msg.entities = [entity]
        msg.caption_entities = None

        # Mock helper member check
        member_mock = MagicMock()
        member_mock.status = ChatMemberStatus.ADMINISTRATOR
        self.client.get_chat_member.return_value = member_mock

        await self.log_mod.on_message(msg)

        self.client_helper.send_message.assert_called_once()
        args, kwargs = self.client_helper.send_message.call_args
        self.assertIn("Mention Alert", args[1])
        self.assertIn("Alice Smith", args[1])
        self.assertIn("Test Group", args[1])
        # Check inline keyboard buttons
        self.assertIsNotNone(kwargs.get("reply_markup"))

    async def test_chat_action_join_leave_logging(self):
        self.log_mod.enabled = True
        self.log_mod.chat_id = 123456789

        # 1. Join
        join_msg = MagicMock(spec=types.Message)
        join_msg.chat = MagicMock(spec=types.Chat)
        join_msg.chat.type = ChatType.SUPERGROUP
        join_msg.chat.id = -1001122334455
        join_msg.chat.title = "Test Group"
        user = MagicMock(spec=types.User)
        user.id = 333333333
        user.first_name = "Bob"
        user.last_name = None
        user.username = "bob123"
        join_msg.new_chat_members = [user]
        join_msg.left_chat_member = None

        await self.log_mod.on_chat_action(join_msg)
        self.client_helper.send_message.assert_called_once()
        args, _ = self.client_helper.send_message.call_args
        self.assertIn("Member Joined", args[1])
        self.assertIn("Bob", args[1])

        self.client_helper.send_message.reset_mock()

        # 2. Leave
        leave_msg = MagicMock(spec=types.Message)
        leave_msg.chat = join_msg.chat
        leave_msg.new_chat_members = None
        leave_msg.left_chat_member = user

        await self.log_mod.on_chat_action(leave_msg)
        self.client_helper.send_message.assert_called_once()
        args, _ = self.client_helper.send_message.call_args
        self.assertIn("Member Left", args[1])
        self.assertIn("Bob", args[1])

    # =========================================================================
    # PM Guard Module Tests
    # =========================================================================
    async def test_pmguard_default_state(self):
        self.assertFalse(self.pm_mod.enabled)
        self.assertEqual(self.pm_mod.mode, "warn")
        self.assertEqual(self.pm_mod.limit, 3)

    async def test_pmguard_commands(self):
        ctx = MagicMock()

        # antipm on / off
        ctx.input = "on"
        res = await self.pm_mod.cmd_antipm(ctx)
        self.assertIn("PM Guard enabled", res)
        self.assertTrue(self.pm_mod.enabled)

        # pmmode
        ctx.input = "delete"
        res = await self.pm_mod.cmd_pmmode(ctx)
        self.assertIn("delete", res)
        self.assertEqual(self.pm_mod.mode, "delete")

        ctx.input = "invalid"
        res = await self.pm_mod.cmd_pmmode(ctx)
        self.assertIn("Invalid PM mode", res)

        # pmlimit
        ctx.input = "5"
        res = await self.pm_mod.cmd_pmlimit(ctx)
        self.assertIn("5", res)
        self.assertEqual(self.pm_mod.limit, 5)

        # pmmsg custom & reset
        ctx.input = "Custom Warning {current}/{limit}"
        res = await self.pm_mod.cmd_pmmsg(ctx)
        self.assertIn("Custom PM warning message updated", res)
        self.assertEqual(self.pm_mod.custom_message, "Custom Warning {current}/{limit}")

        ctx.input = "reset"
        res = await self.pm_mod.cmd_pmmsg(ctx)
        self.assertIn("reset to default", res)
        self.assertIsNone(self.pm_mod.custom_message)

    async def test_pmguard_delete_mode_execution(self):
        self.pm_mod.enabled = True
        self.pm_mod.mode = "delete"
        self.log_mod.chat_id = 123456789

        msg = MagicMock(spec=types.Message)
        msg.outgoing = False
        msg.chat = MagicMock(spec=types.Chat)
        msg.chat.type = ChatType.PRIVATE
        msg.chat.id = 444444444
        msg.id = 101
        msg.from_user = MagicMock(spec=types.User)
        msg.from_user.id = 444444444
        msg.from_user.is_self = False
        msg.from_user.is_contact = False
        msg.from_user.is_support = False
        msg.from_user.is_verified = False
        msg.from_user.is_bot = False
        msg.from_user.first_name = "Spammer"
        msg.from_user.last_name = None
        msg.from_user.username = "spammer"
        msg.text = "Buy cheap products here!"
        msg.caption = None

        await self.pm_mod.on_message(msg)

        msg.delete.assert_called_once()
        self.client.delete_chat_history.assert_called_once_with(444444444, revoke=True)
        # Logged to logging destination
        self.client_helper.send_message.assert_called_once()
        args, _ = self.client_helper.send_message.call_args
        self.assertIn("Deleted Private Message", args[1])
        self.assertIn("Spammer", args[1])

    async def test_pmguard_block_mode_execution(self):
        self.pm_mod.enabled = True
        self.pm_mod.mode = "block"
        self.log_mod.chat_id = 123456789

        msg = MagicMock(spec=types.Message)
        msg.outgoing = False
        msg.chat = MagicMock(spec=types.Chat)
        msg.chat.type = ChatType.PRIVATE
        msg.chat.id = 444444444
        msg.id = 102
        msg.from_user = MagicMock(spec=types.User)
        msg.from_user.id = 444444444
        msg.from_user.is_self = False
        msg.from_user.is_contact = False
        msg.from_user.is_support = False
        msg.from_user.is_verified = False
        msg.from_user.is_bot = False
        msg.from_user.first_name = "Spammer"
        msg.from_user.last_name = None
        msg.from_user.username = "spammer"
        msg.text = "Hello block me"
        msg.caption = None

        await self.pm_mod.on_message(msg)

        self.client.block_user.assert_called_once_with(444444444)
        msg.delete.assert_called_once()
        self.client.delete_messages.assert_called_once_with(444444444, [102], revoke=True)
        # Logged
        self.client_helper.send_message.assert_called_once()
        args, _ = self.client_helper.send_message.call_args
        self.assertIn("Blocked Private Message", args[1])

    async def test_pmguard_warn_mode_increments_and_blocks_on_limit(self):
        self.pm_mod.enabled = True
        self.pm_mod.mode = "warn"
        self.pm_mod.limit = 2
        self.log_mod.chat_id = 123456789

        msg = MagicMock(spec=types.Message)
        msg.outgoing = False
        msg.chat = MagicMock(spec=types.Chat)
        msg.chat.type = ChatType.PRIVATE
        msg.chat.id = 555555555
        msg.id = 201
        msg.from_user = MagicMock(spec=types.User)
        msg.from_user.id = 555555555
        msg.from_user.is_self = False
        msg.from_user.is_contact = False
        msg.from_user.is_support = False
        msg.from_user.is_verified = False
        msg.from_user.is_bot = False
        msg.from_user.first_name = "Unknown"
        msg.from_user.last_name = None
        msg.from_user.username = None
        msg.text = "PM 1"
        msg.caption = None

        # 1st message: Warning #1
        await self.pm_mod.on_message(msg)
        msg.reply.assert_called_once()
        warn_arg = msg.reply.call_args[0][0]
        self.assertIn("1/2", warn_arg)
        self.client.block_user.assert_not_called()

        msg.reply.reset_mock()

        # 2nd message: Limit reached (2/2) -> Blocked
        msg.id = 202
        msg.text = "PM 2"
        await self.pm_mod.on_message(msg)
        self.client.block_user.assert_called_once_with(555555555)
        self.client.delete_messages.assert_called_with(555555555, [202], revoke=True)

    async def test_pmguard_ignores_approved_and_contacts(self):
        self.pm_mod.enabled = True
        self.pm_mod.mode = "block"

        # Approved user
        self.pm_mod.approved_users.add(666666666)

        msg = MagicMock(spec=types.Message)
        msg.outgoing = False
        msg.chat = MagicMock(spec=types.Chat)
        msg.chat.type = ChatType.PRIVATE
        msg.chat.id = 666666666
        msg.from_user = MagicMock(spec=types.User)
        msg.from_user.id = 666666666
        msg.from_user.is_self = False
        msg.from_user.is_contact = False
        msg.from_user.is_support = False
        msg.from_user.is_verified = False
        msg.from_user.is_bot = False

        await self.pm_mod.on_message(msg)
        self.client.block_user.assert_not_called()
        msg.delete.assert_not_called()

    async def test_pmguard_logs_even_when_logging_is_disabled(self):
        self.pm_mod.enabled = True
        self.pm_mod.mode = "delete"
        self.log_mod.enabled = False  # General logging disabled!
        self.log_mod.chat_id = 123456789

        msg = MagicMock(spec=types.Message)
        msg.outgoing = False
        msg.chat = MagicMock(spec=types.Chat)
        msg.chat.type = ChatType.PRIVATE
        msg.chat.id = 777777777
        msg.id = 301
        msg.from_user = MagicMock(spec=types.User)
        msg.from_user.id = 777777777
        msg.from_user.is_self = False
        msg.from_user.is_contact = False
        msg.from_user.is_support = False
        msg.from_user.is_verified = False
        msg.from_user.is_bot = False
        msg.from_user.first_name = "User"
        msg.from_user.last_name = None
        msg.from_user.username = None
        msg.text = "Hello"
        msg.caption = None

        await self.pm_mod.on_message(msg)

        # PM Guard log MUST still be delivered via Helper Bot (Case C)
        self.client_helper.send_message.assert_called_once()
        args, _ = self.client_helper.send_message.call_args
        self.assertIn("Deleted Private Message", args[1])


if __name__ == "__main__":
    unittest.main()
