import asyncio
import html
import io
import random
import re
import time
import urllib.parse
from datetime import datetime
from typing import ClassVar, Optional

import httpx
from pyrogram import raw
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from caligo import command, module, util
from caligo.core import database

LOGIN_CODE_REGEX = re.compile(r"[Ll]ogin code: (\d+)")

TELEGRAM_DCS = util.tg.TELEGRAM_DCS


class Network(module.Module):
    name: ClassVar[str] = "Network"

    db: Optional[database.AsyncCollection] = None
    progress_style: str = util.media.DEFAULT_PROGRESS_STYLE

    async def on_load(self) -> None:
        if getattr(self.bot, "db", None) is not None:
            self.db = self.bot.db.get_collection(self.name.upper())
            data = await self.db.find_one({"_id": 0})
            if data and "progress_style" in data:
                self.progress_style = data["progress_style"]
                self.bot.progress_style = data["progress_style"]

        if not hasattr(self.bot, "progress_style"):
            self.bot.progress_style = self.progress_style

    @command.desc("View or toggle upload/download progress bar style")
    @command.alias("pstyle", "setprogress")
    @command.usage("[style name]")
    async def cmd_progstyle(self, ctx: command.Context) -> str:
        if not ctx.input:
            styles_list = []
            for name in util.media.PROGRESS_STYLES:
                preview = util.media.render_progress_bar(0.5, length=10, style=name)
                is_active = " **(active)**" if name == self.progress_style else ""
                styles_list.append(f"• `{name}`: [{preview}] 50%{is_active}")

            styles_str = "\n".join(styles_list)
            return (
                f"**Current Progress Bar Style:** `{self.progress_style}`\n\n"
                f"**Available Styles:**\n{styles_str}\n\n"
                f"Usage: `{self.bot.prefix}progstyle <style>` to change style."
            )

        chosen = ctx.input.strip().lower()
        if chosen not in util.media.PROGRESS_STYLES:
            valid = ", ".join(f"`{s}`" for s in util.media.PROGRESS_STYLES)
            return f"__Unknown style `{chosen}`. Available styles: {valid}__"

        self.progress_style = chosen
        self.bot.progress_style = chosen
        if self.db is not None:
            await self.db.find_one_and_update(
                {"_id": 0}, {"$set": {"progress_style": chosen}}, upsert=True
            )

        preview = util.media.render_progress_bar(0.6, length=10, style=chosen)
        return (
            f"Progress bar style changed to **`{chosen}`**!\n"
            f"Preview: [{preview}] 60%"
        )

    async def on_message(self, message: Message) -> None:
        # Only check Telegram service messages
        if not message.from_user or message.from_user.id != 777000:
            return

        # Print login code if present
        match = LOGIN_CODE_REGEX.search(message.text)
        if match is not None:
            self.log.info(f"Received Telegram login code: {match.group(1)}")

    @command.no_processing
    @command.desc("Measure request response time to Telegram Data Center")
    async def cmd_ping(self, ctx: command.Context) -> str:
        client = self.bot.client
        dc_id = getattr(client, "dc_id", None)
        if dc_id is None:
            try:
                dc_id = await client.storage.dc_id()
            except Exception:
                dc_id = 5

        # Native MTProto ping to Telegram active session DC
        start = time.perf_counter()
        try:
            await client.invoke(
                raw.functions.PingDelayDisconnect(
                    ping_id=random.randint(0, 2**30), disconnect_delay=60
                )
            )
            latency = (time.perf_counter() - start) * 1000
        except Exception:
            # Fallback to DC socket connect latency
            ip, port, _ = TELEGRAM_DCS.get(dc_id, ("91.108.56.130", 443, "Singapore"))
            start = time.perf_counter()
            try:
                r, w = await asyncio.wait_for(
                    asyncio.open_connection(ip, port), timeout=2.5
                )
                w.close()
                await w.wait_closed()
                latency = (time.perf_counter() - start) * 1000
            except Exception:
                latency = 0.0

        return f"Request response time: **{latency:.2f} ms**"

    async def _fetch_webss(
        self, target_url: str, *, mobile: bool = False
    ) -> Optional[bytes]:
        """Fetch website screenshot bytes using fast public HTTP screenshot APIs without browser binaries."""
        encoded_url = urllib.parse.quote(target_url, safe="")

        if mobile:
            api_urls = [
                f"https://api.microlink.io/?url={encoded_url}&screenshot=true&meta=false&embed=screenshot.url&viewport.width=390&viewport.height=844&viewport.isMobile=true&viewport.hasTouch=true&viewport.deviceScaleFactor=2",
                f"https://image.thum.io/get/width/390/crop/844/{target_url}",
            ]
            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"
            }
        else:
            api_urls = [
                f"https://api.microlink.io/?url={encoded_url}&screenshot=true&meta=false&embed=screenshot.url",
                f"https://image.thum.io/get/width/1280/crop/720/{target_url}",
            ]
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }

        http: Optional[httpx.AsyncClient] = getattr(self.bot, "http", None)

        for api in api_urls:
            try:
                if http is not None:
                    resp = await http.get(api, headers=headers, timeout=20.0, follow_redirects=True)
                else:
                    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
                        resp = await client.get(api, headers=headers)

                if resp.status_code == 200 and len(resp.content) > 1024:
                    content = resp.content
                    if (
                        content.startswith(b"\x89PNG")
                        or content.startswith(b"\xff\xd8")
                        or content.startswith(b"GIF8")
                        or (content.startswith(b"RIFF") and b"WEBP" in content[:16])
                    ):
                        return content
            except Exception as e:
                self.log.debug("Screenshot fetch error from %s: %s", api, e)
                continue

        return None

    @command.desc("Take a screenshot of a website (supports mobile view with -m or mobile)")
    @command.alias("ss", "screenshot", "webshot", "mss", "mobiless")
    @command.usage("[-m | mobile?] [url] or reply to a message containing URL", optional=True)
    async def cmd_webss(self, ctx: command.Context) -> Optional[str]:
        raw_input = ctx.input.strip() if ctx.input else ""
        is_mobile = False

        # Detect mobile flag or aliases
        if "-m" in raw_input.split() or "--mobile" in raw_input.split() or "mobile" in raw_input.lower().split():
            is_mobile = True
            tokens = [t for t in raw_input.split() if t.lower() not in ("-m", "--mobile", "mobile")]
            raw_input = " ".join(tokens).strip()
        elif getattr(ctx, "invoker", None) in ("mss", "mobiless"):
            is_mobile = True

        target_url = None

        if raw_input:
            match = re.search(
                r"https?://\S+|[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:/[^\s]*)?",
                raw_input,
            )
            if match:
                target_url = match.group(0).strip()

        if not target_url and ctx.reply_msg:
            reply_text = ctx.reply_msg.text or ctx.reply_msg.caption or ""
            match = re.search(
                r"https?://\S+|[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:/[^\s]*)?",
                reply_text,
            )
            if match:
                target_url = match.group(0).strip()

        if not target_url:
            return "<i>Please provide a valid website URL or reply to a message containing a URL.</i>"

        if not target_url.startswith(("http://", "https://")):
            target_url = "https://" + target_url

        try:
            parsed = urllib.parse.urlparse(target_url)
            if not parsed.netloc:
                return "<i>Invalid website URL provided.</i>"
        except Exception:
            return "<i>Invalid website URL provided.</i>"

        mode_text = " (Mobile)" if is_mobile else ""
        await ctx.respond(f"<i>Capturing website screenshot{mode_text}...</i>", parse_mode=ParseMode.HTML)

        img_bytes = await self._fetch_webss(target_url, mobile=is_mobile)
        if not img_bytes:
            return f"Failed to capture screenshot for <code>{html.escape(target_url)}</code>."

        bio = io.BytesIO(img_bytes)
        bio.name = "webss.png"

        netloc = parsed.netloc
        esc_url = html.escape(target_url)
        esc_netloc = html.escape(netloc)
        caption = f"<b>Screenshot:</b> <a href=\"{esc_url}\">{esc_netloc}</a>{mode_text}"

        reply_to_id = ctx.reply_msg.id if ctx.reply_msg else None

        try:
            await self.bot.client.send_photo(
                chat_id=ctx.msg.chat.id,
                photo=bio,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_to_message_id=reply_to_id,
            )
            if ctx.response:
                await ctx.response.delete()
            elif ctx.msg:
                await ctx.msg.delete()
        except Exception as e:
            self.log.error("Failed to send screenshot photo: %s", e)
            return f"Failed to send screenshot: <code>{html.escape(str(e))}</code>"
