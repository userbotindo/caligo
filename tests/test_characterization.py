import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from caligo.util import misc, text, tg, time
from caligo.command import Command
from caligo.core.command_dispatcher import CommandDispatcher
from caligo.core.telegram_bot import TelegramBot
from caligo.core.database.storage import PersistentStorage
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


if __name__ == "__main__":
    unittest.main()
