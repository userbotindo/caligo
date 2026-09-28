import asyncio
import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from anyio import Path as AsyncPath

from caligo.util import misc, text, tg, time
from caligo.command import Command
from caligo.core.command_dispatcher import CommandDispatcher
from caligo.core.telegram_bot import TelegramBot
from caligo.core.database.storage import PersistentStorage
from caligo.modules.network import Network
from caligo.modules.transfer import Transfer
from caligo.modules.system import System
from caligo.modules.stats import Stats, _calc_pct, _calc_pd, _calc_ph
from caligo.modules.text import Text


class TestCaligoCharacterization(unittest.IsolatedAsyncioTestCase):
    """Characterization tests to lock in current behavior and outputs."""

    def test_misc_human_readable_bytes(self):
        self.assertEqual(misc.human_readable_bytes(500), "500.00B")
        self.assertEqual(misc.human_readable_bytes(1024), "1.00KiB")
        self.assertEqual(misc.human_readable_bytes(1048576), "1.00MiB")
        self.assertEqual(misc.human_readable_bytes(1073741824, digits=1), "1.0GiB")
        self.assertEqual(
            misc.human_readable_bytes(5242880, digits=2, delim=" ", postfix="/s"),
            "5.00 MiB/s",
        )

    def test_misc_chunk_list(self):
        items = list(range(25))
        chunks = list(misc.chunk_list(items, chunk_size=10))
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0], list(range(10)))
        self.assertEqual(chunks[1], list(range(10, 20)))
        self.assertEqual(chunks[2], list(range(20, 25)))

    def test_text_join_list(self):
        items = ["one", "two", "three"]
        self.assertEqual(text.join_list(items), "one\n    • two\n    • three")

    def test_text_join_map(self):
        data = {"A": "1", "B": "2"}
        md_result = text.join_map(data, heading="Title", parse_mode="markdown")
        self.assertEqual(md_result, "**Title:**\n    • **A:** 1\n    • **B:** 2")

        html_result = text.join_map(data, heading="Title", parse_mode="html")
        self.assertEqual(html_result, "<b>Title:</b>\n    • <b>A:</b> 1\n    • <b>B:</b> 2")

        no_heading = text.join_map(data, parse_mode="markdown")
        self.assertEqual(no_heading, "**A:** 1\n    • **B:** 2")

    def test_text_has_emoji(self):
        self.assertTrue(text.has_emoji("Hello 😊 world"))
        self.assertFalse(text.has_emoji("Hello plain world 123!"))

    def test_time_duration_us(self):
        self.assertEqual(time.format_duration_us(500), "500 μs")
        self.assertEqual(time.format_duration_us(1500), "1 ms")
        self.assertEqual(time.format_duration_us(3000000), "3 sec")
        self.assertEqual(time.format_duration_us(150000000), "2m 30s")
        self.assertEqual(time.format_duration_us(7200000000), "2h 0m")
        self.assertEqual(time.format_duration_us(90000000000), "1d 1h")

    def test_time_duration_td(self):
        self.assertEqual(time.format_duration_td(timedelta(seconds=45)), "45s")
        self.assertEqual(time.format_duration_td(timedelta(minutes=2, seconds=15)), "2m15s")
        self.assertEqual(time.format_duration_td(timedelta(hours=3, minutes=10, seconds=5)), "3h10m5s")
        self.assertEqual(time.format_duration_td(timedelta(days=1, hours=2)), "1d2h")
        self.assertEqual(time.format_duration_td(timedelta(hours=3, minutes=10, seconds=5), precision=2), "3h10m")

    def test_time_parse_duration(self):
        self.assertEqual(time.parse_duration("10s"), timedelta(seconds=10))
        self.assertEqual(time.parse_duration("15m"), timedelta(minutes=15))
        self.assertEqual(time.parse_duration("2h"), timedelta(hours=2))
        self.assertEqual(time.parse_duration("1d"), timedelta(days=1))
        self.assertEqual(time.parse_duration("2w"), timedelta(weeks=2))
        self.assertEqual(time.parse_duration("1d12h"), timedelta(days=1, hours=12))
        self.assertIsNone(time.parse_duration("invalid"))

        dur, reason = time.extract_duration_and_reason("1d spam")
        self.assertEqual(dur, timedelta(days=1))
        self.assertEqual(reason, "spam")

    def test_tg_target_helpers(self):
        self.assertEqual(tg.get_target_id(12345), 12345)
        self.assertEqual(tg.format_target(12345), "[12345](tg://user?id=12345)")
        self.assertEqual(tg.format_target("@username"), "@username")

    def test_tg_render_progress_bar(self):
        bar_bullet_0 = tg.render_progress_bar(0.0, length=10, style="bullet")
        self.assertEqual(bar_bullet_0, "○○○○○○○○○○")
        bar_bullet_50 = tg.render_progress_bar(0.5, length=10, style="bullet")
        self.assertEqual(bar_bullet_50, "●●●●●○○○○○")
        bar_bullet_100 = tg.render_progress_bar(1.0, length=10, style="bullet")
        self.assertEqual(bar_bullet_100, "●●●●●●●●●●")

        bar_block = tg.render_progress_bar(0.6, length=10, style="block")
        self.assertEqual(bar_block, "██████░░░░")

    def test_tg_format_progress(self):
        result = tg.format_progress(
            file_name="test.mp4",
            status="Uploading",
            percent=0.5,
            current=5242880,
            total=10485760,
            speed=1048576.0,
            eta=timedelta(seconds=5),
            style="bullet",
        )
        self.assertIn("`test.mp4`", result)
        self.assertIn("Status: **Uploading**", result)
        self.assertIn("Progress: [●●●●●○○○○○] 50%", result)
        self.assertIn("5.00MiB of 10.00MiB @ 1.00MiB/s", result)
        self.assertIn("ETA: 5s", result)

    def test_tg_get_media_type(self):
        self.assertEqual(tg.get_media_type("photo.jpg"), "photo")
        self.assertEqual(tg.get_media_type("image.png"), "photo")
        self.assertEqual(tg.get_media_type("video.mp4"), "video")
        self.assertEqual(tg.get_media_type("audio.mp3"), "audio")
        self.assertEqual(tg.get_media_type("sticker.tgs"), "sticker")
        self.assertEqual(tg.get_media_type("archive.zip"), "document")

    def test_tg_truncate(self):
        short_text = "short text"
        self.assertEqual(tg.truncate(short_text), short_text)

        long_text = "a" * 5000
        truncated = tg.truncate(long_text)
        self.assertEqual(len(truncated), tg.MESSAGE_CHAR_LIMIT)
        self.assertTrue(truncated.endswith(tg.TRUNCATION_SUFFIX))

        long_code = "```" + ("b" * 5000) + "```"
        truncated_code = tg.truncate(long_code)
        self.assertTrue(truncated_code.endswith(tg.TRUNCATION_SUFFIX + "```"))

    def test_redact_message(self):
        class DummyBot(TelegramBot):
            def __init__(self):
                self.config = {
                    "telegram": {
                        "api_id": 1234567,
                        "api_hash": "secret_api_hash_abc",
                        "helper": {"token": "secret_bot_token_xyz"},
                    },
                    "bot": {"db_uri": "mongodb://user:pass@mongo:27017"},
                }

        bot = DummyBot()
        text_with_secrets = (
            "Connected with 1234567 and secret_api_hash_abc to "
            "mongodb://user:pass@mongo:27017 using secret_bot_token_xyz"
        )
        redacted = bot.redact_message(text_with_secrets)
        self.assertEqual(
            redacted,
            "Connected with [REDACTED] and [REDACTED] to [REDACTED] using [REDACTED]",
        )
        plain_text = "No secrets here!"
        self.assertEqual(bot.redact_message(plain_text), plain_text)

    async def test_persistent_storage_accessor(self):
        # Mock database and collection
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_db.__getitem__.return_value = mock_session

        storage = PersistentStorage(mock_db)

        # Mock find_one for _get
        mock_session.find_one = AsyncMock(return_value={"dc_id": 2, "api_id": 99999})
        dc = await storage.dc_id()
        self.assertEqual(dc, 2)
        mock_session.find_one.assert_called_with({"_id": 0}, {"dc_id": 1})

        api = await storage.api_id()
        self.assertEqual(api, 99999)

        # Mock update_one for _set
        mock_session.update_one = AsyncMock()
        await storage.dc_id(4)
        mock_session.update_one.assert_called_with(
            {"_id": 0}, {"$set": {"dc_id": 4}}, upsert=True
        )

    def test_stats_calc_helpers(self):
        self.assertEqual(_calc_pct(5, 10), "50")
        self.assertEqual(_calc_pct(1, 3), "33.3")
        self.assertEqual(_calc_pct(0, 10), "0")
        self.assertEqual(_calc_pct(10, 0), "0")

        # 1 hour uptime in usec
        hour_us = 3600 * 1000000
        self.assertEqual(_calc_ph(100, hour_us), "100")
        self.assertEqual(_calc_ph(50, hour_us * 2), "25")

        # 1 day uptime in usec
        day_us = 24 * hour_us
        self.assertEqual(_calc_pd(48, day_us), "48")

    async def test_cmd_stats(self):
        bot = MagicMock()
        stats_mod = Stats(bot)
        stats_mod.db = MagicMock()
        stats_mod.db.find_one = AsyncMock(
            return_value={
                "_id": 0,
                "start_time_usec": 1000000,
                "sent": 10,
                "sent_stickers": 2,
                "received": 20,
                "received_stickers": 4,
                "processed": 5,
                "stickers_created": 1,
            }
        )
        ctx = MagicMock()
        ctx.input = ""
        result = await stats_mod.cmd_stats(ctx)
        self.assertIn("Stats since last reset", result)
        self.assertIn("Messages received:", result)
        self.assertIn("Messages sent:", result)
        # Verify find_one was called exactly once to fetch all stats
        stats_mod.db.find_one.assert_called_once_with({"_id": 0})

    async def test_text_module_commands(self):
        bot = MagicMock()
        text_mod = Text(bot)

        # cmd_uni
        ctx = MagicMock()
        ctx.input = "0041"
        self.assertEqual(await text_mod.cmd_uni(ctx), "A")

        # cmd_clap
        ctx.input = "hello world from caligo"
        ctx.msg.reply_to_message = None
        self.assertEqual(await text_mod.cmd_clap(ctx), "hello👏world👏from👏caligo")

        # cmd_base64
        ctx.input = "caligo fast"
        encoded = await text_mod.cmd_base64encode(ctx)
        self.assertEqual(encoded, "Y2FsaWdvIGZhc3Q=")
        ctx.input = encoded
        decoded = await text_mod.cmd_base64decode(ctx)
        self.assertEqual(decoded, "caligo fast")

    def test_tg_parse_telegram_message_link(self):
        self.assertEqual(
            tg.parse_telegram_message_link("https://t.me/deltaDiscuss/208009"),
            ("deltaDiscuss", 208009),
        )
        self.assertEqual(
            tg.parse_telegram_message_link("http://t.me/deltaDiscuss/208009"),
            ("deltaDiscuss", 208009),
        )
        self.assertEqual(
            tg.parse_telegram_message_link("t.me/deltaDiscuss/208009"),
            ("deltaDiscuss", 208009),
        )
        self.assertEqual(
            tg.parse_telegram_message_link("https://t.me/deltaDiscuss/208009?single"),
            ("deltaDiscuss", 208009),
        )
        self.assertEqual(
            tg.parse_telegram_message_link("https://t.me/deltaDiscuss/123/208009"),
            ("deltaDiscuss", 208009),
        )
        self.assertEqual(
            tg.parse_telegram_message_link("https://t.me/c/1234567890/208009"),
            (-1001234567890, 208009),
        )
        self.assertEqual(
            tg.parse_telegram_message_link("https://t.me/c/1234567890/15/208009"),
            (-1001234567890, 208009),
        )
        self.assertEqual(
            tg.parse_telegram_message_link("https://telegram.me/deltaDiscuss/208009"),
            ("deltaDiscuss", 208009),
        )
        self.assertEqual(
            tg.parse_telegram_message_link("tg://resolve?domain=deltaDiscuss&post=208009"),
            ("deltaDiscuss", 208009),
        )
        self.assertIsNone(tg.parse_telegram_message_link("https://example.com/not_tg/123"))

    async def test_network_cmd_download_telegram_link(self):
        bot = MagicMock()
        bot.db = None
        bot.loop = asyncio.get_running_loop()
        trans_mod = Transfer(bot)
        await trans_mod.on_load()

        mock_msg = MagicMock()
        mock_msg.id = 208009
        mock_msg.empty = False
        mock_msg.media_group_id = None
        mock_media = MagicMock()
        mock_media.value = "document"
        mock_msg.media = mock_media
        mock_doc = MagicMock()
        mock_doc.file_name = "test_file.apk"
        mock_msg.document = mock_doc

        bot.client.get_messages = AsyncMock(return_value=mock_msg)
        bot.client.download_media = AsyncMock(return_value="/downloads/test_file.apk")

        ctx = MagicMock()
        ctx.input = "https://t.me/deltaDiscuss/208009"
        ctx.msg.id = 100
        ctx.msg.reply_to_message = None
        ctx.respond = AsyncMock()

        result = await trans_mod.cmd_download(ctx)
        bot.client.get_messages.assert_called_once_with("deltaDiscuss", 208009)
        bot.client.download_media.assert_called_once()
        self.assertIn("Downloaded to:", result)
        self.assertIn("/downloads/test_file.apk", result)

    async def test_network_cmd_download_reply_media(self):
        bot = MagicMock()
        bot.db = None
        bot.loop = asyncio.get_running_loop()
        trans_mod = Transfer(bot)
        await trans_mod.on_load()

        mock_media = MagicMock()
        mock_media.value = "photo"
        reply_msg = MagicMock()
        reply_msg.id = 555
        reply_msg.media = mock_media
        reply_msg.media_group_id = None
        reply_msg.photo = MagicMock()
        reply_msg.photo.file_name = "photo.jpg"

        bot.client.download_media = AsyncMock(return_value="/downloads/photo.jpg")

        ctx = MagicMock()
        ctx.input = ""
        ctx.msg.id = 101
        ctx.msg.reply_to_message = reply_msg
        ctx.respond = AsyncMock()

        result = await trans_mod.cmd_download(ctx)
        bot.client.download_media.assert_called_once()
        self.assertIn("Downloaded to:", result)
        self.assertIn("/downloads/photo.jpg", result)

    async def test_network_cmd_download_no_source(self):
        bot = MagicMock()
        bot.db = None
        bot.loop = asyncio.get_running_loop()
        trans_mod = Transfer(bot)
        await trans_mod.on_load()

        ctx = MagicMock()
        ctx.input = ""
        ctx.msg.id = 102
        ctx.msg.reply_to_message = None
        ctx.respond = AsyncMock()

        result = await trans_mod.cmd_download(ctx)
        self.assertIn("Pass a Telegram message link/ID", result)

    async def test_network_cmd_download_unique_sticker(self):
        bot = MagicMock()
        bot.db = None
        bot.loop = asyncio.get_running_loop()
        trans_mod = Transfer(bot)
        await trans_mod.on_load()

        mock_sticker = MagicMock()
        mock_sticker.file_unique_id = "AQAD999XYZ"
        mock_sticker.set_name = "CuteCats"
        mock_sticker.is_animated = False
        mock_sticker.is_video = False

        mock_media = MagicMock()
        mock_media.value = "sticker"
        reply_msg = MagicMock()
        reply_msg.id = 777
        reply_msg.media = mock_media
        reply_msg.media_group_id = None
        reply_msg.sticker = mock_sticker

        async def fake_download(msg, file_name=None, progress=None):
            return file_name

        bot.client.download_media = AsyncMock(side_effect=fake_download)
        trans_mod.get_download_dir = AsyncMock(return_value=AsyncPath("downloads"))

        ctx = MagicMock()
        ctx.input = ""
        ctx.msg.id = 103
        ctx.msg.reply_to_message = reply_msg
        ctx.respond = AsyncMock()

        result = await trans_mod.cmd_download(ctx)
        call_kwargs = bot.client.download_media.call_args.kwargs
        self.assertIn("downloads/sticker_CuteCats_AQAD999XYZ.webp", call_kwargs["file_name"])
        self.assertIn("sticker_CuteCats_AQAD999XYZ.webp", result)

    async def test_network_cmd_cleardownloads_single_and_all(self):
        bot = MagicMock()
        bot.db = None
        bot.loop = asyncio.get_running_loop()
        trans_mod = Transfer(bot)
        await trans_mod.on_load()
        with tempfile.TemporaryDirectory() as temp_dir:
            dl_dir = AsyncPath(temp_dir) / "downloads"
            await dl_dir.mkdir(parents=True, exist_ok=True)
            trans_mod.get_download_dirs = AsyncMock(return_value=[dl_dir])

            # Create test files
            f1 = dl_dir / "test1.txt"
            f2 = dl_dir / "test2.txt"
            await f1.write_text("hello 1")
            await f2.write_text("hello 2")

            # Test deleting single file
            ctx_single = MagicMock()
            ctx_single.input = "test1.txt"
            ctx_single.msg.reply_to_message = None
            res_single = await trans_mod.cmd_cleardownloads(ctx_single)
            self.assertIn("Deleted", res_single)
            self.assertIn("`test1.txt`", res_single)
            self.assertFalse(await f1.exists())
            self.assertTrue(await f2.exists())

            # Test deleting non-existent file
            ctx_notfound = MagicMock()
            ctx_notfound.input = "non_existent.txt"
            ctx_notfound.msg.reply_to_message = None
            res_notfound = await trans_mod.cmd_cleardownloads(ctx_notfound)
            self.assertIn("not found in downloads", res_notfound)

            # Test clearing all remaining files
            ctx_all = MagicMock()
            ctx_all.input = ""
            ctx_all.msg.reply_to_message = None
            res_all = await trans_mod.cmd_cleardownloads(ctx_all)
            self.assertIn("Cleared 1 file", res_all)
            self.assertFalse(await f2.exists())

            # Test clearing when already empty
            res_empty = await trans_mod.cmd_cleardownloads(ctx_all)
            self.assertIn("Downloads folder is already empty", res_empty)

    async def test_network_cmd_download_http_url(self):
        bot = MagicMock()
        bot.db = None
        bot.loop = asyncio.get_running_loop()
        trans_mod = Transfer(bot)
        await trans_mod.on_load()

        with tempfile.TemporaryDirectory() as temp_dir:
            dl_dir = AsyncPath(temp_dir) / "downloads"
            await dl_dir.mkdir(parents=True, exist_ok=True)
            trans_mod.get_download_dir = AsyncMock(return_value=dl_dir)

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {
                "content-disposition": 'attachment; filename="sample.bin"',
                "content-length": "12",
            }

            async def fake_aiter(chunk_size=65536):
                yield b"hello "
                yield b"httpx!"

            mock_resp.aiter_bytes = fake_aiter

            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def fake_stream(*args, **kwargs):
                yield mock_resp

            bot.http = MagicMock()
            bot.http.stream = fake_stream

            ctx = MagicMock()
            ctx.input = "https://example.com/files/sample.bin"
            ctx.msg.id = 104
            ctx.msg.reply_to_message = None
            ctx.respond = AsyncMock()
            ctx.last_update_time = None

            result = await trans_mod.cmd_download(ctx)
            self.assertIn("Downloaded to:", result)
            self.assertIn("sample.bin", result)
            self.assertTrue(await (dl_dir / "sample.bin").exists())

    async def test_autodel_module(self):
        bot = MagicMock()
        bot.delete_after = 15.0
        bot.db = MagicMock()
        bot.db.__getitem__.return_value.update_one = AsyncMock()

        mod = System(bot)
        await mod.on_load()

        # Query status
        ctx = MagicMock()
        ctx.input = ""
        res = await mod.cmd_autodel(ctx)
        self.assertIn("Auto-delete is set to", res)
        self.assertIn("15", res)

        # Set new duration
        ctx.input = "30"
        res = await mod.cmd_autodel(ctx)
        self.assertEqual(bot.delete_after, 30.0)
        self.assertIn("Auto-delete duration set to", res)
        self.assertIn("30", res)

        # Disable
        ctx.input = "off"
        res = await mod.cmd_autodel(ctx)
        self.assertIsNone(bot.delete_after)
        self.assertIn("Auto-delete has been disabled", res)

        # Query when disabled
        ctx.input = ""
        res = await mod.cmd_autodel(ctx)
        self.assertIn("Auto-delete is currently disabled", res)

        # Invalid input
        ctx.input = "invalid_string"
        res = await mod.cmd_autodel(ctx)
        self.assertIn("Invalid duration", res)

    async def test_system_cmd_processing(self):
        bot = MagicMock()
        bot.processing_status = None
        bot.db = MagicMock()
        bot.db.__getitem__.return_value.update_one = AsyncMock()

        mod = System(bot)
        await mod.on_load()

        # Query status when disabled
        ctx = MagicMock()
        ctx.input = ""
        res = await mod.cmd_processing(ctx)
        self.assertIn("disabled", res)

        # Enable default
        ctx.input = "on"
        res = await mod.cmd_processing(ctx)
        self.assertEqual(bot.processing_status, "__Processing...__")
        self.assertIn("set to:", res)

        # Set custom text
        ctx.input = "⏳ Working on it..."
        res = await mod.cmd_processing(ctx)
        self.assertEqual(bot.processing_status, "⏳ Working on it...")
        self.assertIn("⏳ Working on it...", res)

        # Disable
        ctx.input = "off"
        res = await mod.cmd_processing(ctx)
        self.assertIsNone(bot.processing_status)
        self.assertIn("disabled", res)

    async def test_dispatcher_global_delete_after(self):
        dispatcher = CommandDispatcher()
        dispatcher.delete_after = 15.0
        dispatcher.processing_status = None
        dispatcher.prefix = "."
        dispatcher.log = MagicMock()
        dispatcher.dispatch_event = AsyncMock()

        dummy_mod = MagicMock()
        dummy_mod.log = MagicMock()

        async def dummy_func(ctx):
            return "Command executed successfully!"

        dispatcher.register_command(dummy_mod, "testcmd", dummy_func)

        msg = MagicMock()
        msg.command = ["testcmd"]
        msg.text = ".testcmd"
        msg.continue_propagation = MagicMock()

        with patch("caligo.command.Context.respond", new_callable=AsyncMock) as mock_respond:
            await dispatcher.on_command(MagicMock(), msg)
            mock_respond.assert_called_once()
            call_kwargs = mock_respond.call_args.kwargs
            self.assertEqual(call_kwargs.get("delete_after"), 15.0)

    async def test_dispatcher_global_processing(self):
        dispatcher = CommandDispatcher()
        dispatcher.delete_after = None
        dispatcher.processing_status = "__Processing...__"
        dispatcher.prefix = "."
        dispatcher.log = MagicMock()
        dispatcher.dispatch_event = AsyncMock()

        dummy_mod = MagicMock()
        dummy_mod.log = MagicMock()

        async def dummy_func(ctx):
            return "Final output"

        dispatcher.register_command(dummy_mod, "proc_test", dummy_func)

        msg = MagicMock()
        msg.command = ["proc_test"]
        msg.text = ".proc_test"
        msg.continue_propagation = MagicMock()

        with patch("caligo.command.Context.respond", new_callable=AsyncMock) as mock_respond:
            await dispatcher.on_command(MagicMock(), msg)
            # Should have called respond twice: first for processing message, second for final output
            self.assertEqual(mock_respond.call_count, 2)
            first_call_text = mock_respond.call_args_list[0][0][0]
            second_call_text = mock_respond.call_args_list[1][0][0]
            self.assertEqual(first_call_text, "__Processing...__")
            self.assertEqual(second_call_text, "Final output")

    async def test_system_cmd_speedtest_modernized(self):
        bot = MagicMock()
        bot.db = None
        bot.loop = asyncio.get_running_loop()
        sys_mod = System(bot)

        fake_st = MagicMock()
        fake_st.get_best_server.return_value = {
            "sponsor": "PT Merdeka",
            "name": "Boyolali",
            "country": "Indonesia",
            "latency": 16.5,
            "d": 336.0,
        }
        fake_st.download.return_value = 100_000_000
        fake_st.upload.return_value = 50_000_000
        fake_st.results.client = {"isp": "MyRepublic", "country": "ID"}
        fake_st.results.share.return_value = "https://www.speedtest.net/result/12345.png"

        ctx = MagicMock()
        ctx.respond = AsyncMock()

        with patch("speedtest.Speedtest", return_value=fake_st):
            result = await sys_mod.cmd_speedtest(ctx)

        self.assertIn("<blockquote>", result)
        self.assertIn("<b>Speedtest:</b>", result)
        self.assertIn("100.00 Mbps", result)
        self.assertIn("50.00 Mbps", result)
        self.assertIn("16.50 ms", result)
        self.assertIn("PT Merdeka", result)
        self.assertIn("Boyolali, Indonesia", result)
        self.assertIn("MyRepublic (ID)", result)
        self.assertIn("https://www.speedtest.net/result/12345.png", result)

    async def test_text_cmd_translate(self):
        bot = MagicMock()
        text_mod = Text(bot)

        # Mock http response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [["Halo dunia", "en"]]
        bot.http.get = AsyncMock(return_value=mock_resp)

        # 1. Translate with direct input
        ctx = MagicMock()
        ctx.msg.reply_to_message = None
        ctx.input = "id Hello world"
        res = await text_mod.cmd_translate(ctx)
        self.assertIn("<b>English</b> (<code>en</code>) ➔ <b>Indonesian</b> (<code>id</code>)", res)
        self.assertIn("Halo dunia", res)
        self.assertIn("<blockquote expandable>", res)

        # 2. Translate with reply
        ctx = MagicMock()
        ctx.msg.reply_to_message = MagicMock()
        ctx.msg.reply_to_message.text = "Hello world"
        ctx.msg.reply_to_message.caption = None
        ctx.input = "id"
        res = await text_mod.cmd_translate(ctx)
        self.assertIn("Halo dunia", res)

        # 3. Empty input and no reply
        ctx = MagicMock()
        ctx.msg.reply_to_message = None
        ctx.input = ""
        res = await text_mod.cmd_translate(ctx)
        self.assertIn("Give me text to translate or reply to a message", res)


if __name__ == "__main__":
    unittest.main()

