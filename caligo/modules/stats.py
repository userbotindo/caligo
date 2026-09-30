from typing import Any, ClassVar, Optional

from pyrogram.types import Message

from caligo import command, module, util
from caligo.core import database

USEC_PER_HOUR = util.time.USEC_PER_HOUR
USEC_PER_DAY = util.time.USEC_PER_DAY
_calc_pct = util.time.calc_pct
_calc_ph = util.time.calc_ph
_calc_pd = util.time.calc_pd


class Stats(module.Module):
    name: ClassVar[str] = "Stats"

    db: database.AsyncCollection

    async def get(self, key: str) -> Optional[Any]:
        collection = await self.db.find_one({"_id": 0})
        return collection.get(key) if collection else None

    async def inc(self, key: str, value: int) -> None:
        await self.db.find_one_and_update(
            {"_id": 0}, {"$inc": {key: value}}, upsert=True
        )

    async def delete(self, key: str) -> None:
        await self.db.find_one_and_update({"_id": 0}, {"$unset": {key: ""}})

    async def put(self, key: str, value: int) -> None:
        await self.db.find_one_and_update(
            {"_id": 0}, {"$set": {key: value}}, upsert=True
        )

    async def on_load(self) -> None:
        self.db = self.bot.db.get_collection(self.name.upper())

        if await self.get("stop_time_usec") or await self.get("uptime"):
            self.log.info("Migrating stats timekeeping format")

        last_time = await self.get("stop_time_usec")
        if last_time is not None:
            await self.inc("uptime", util.time.usec() - last_time)
            await self.delete("stop_time_usec")

        uptime = await self.get("uptime")
        if uptime is not None:
            await self.put("start_time_usec", self.bot.start_time_us - uptime)
            await self.delete("uptime")

    async def on_start(self, time_us: int) -> None:
        # Initialize start_time_usec for new instances
        doc = await self.db.find_one({"_id": 0})
        if not doc or "start_time_usec" not in doc:
            await self.put("start_time_usec", time_us)

    async def on_message(self, msg: Message) -> None:
        stat = "sent" if msg.outgoing else "received"
        await self.bot.log_stat(stat)

        if msg.sticker:
            sticker_stat = stat + "_stickers"
            await self.bot.log_stat(sticker_stat)

    async def on_command(
        self,
        cmd: command.Command,  # skipcq: PYL-W0613
        msg: Message,  # skipcq: PYL-W0613
    ) -> None:
        await self.bot.log_stat("processed")

    async def on_stat_event(self, key: str) -> None:
        await self.inc(key, 1)

    async def get_start_time(self) -> int:
        return await self.get("start_time_usec") or self.bot.start_time_us

    @command.desc("Show chat stats (pass `reset` to reset stats)")
    @command.usage('["reset" to reset stats?]', optional=True)
    @command.alias("stat")
    async def cmd_stats(self, ctx: command.Context) -> str:
        if ctx.input == "reset":
            await self.db.find_one_and_delete({"_id": 0})
            await self.on_load()
            await self.on_start(util.time.usec())
            return "__All stats have been reset.__"

        doc = await self.db.find_one({"_id": 0}) or {}
        start_time: Optional[int] = doc.get("start_time_usec")
        if start_time is None:
            start_time = util.time.usec()
            await self.put("start_time_usec", start_time)
        uptime = util.time.usec() - start_time

        sent: int = doc.get("sent") or 0
        sent_stickers: int = doc.get("sent_stickers") or 0
        recv: int = doc.get("received") or 0
        recv_stickers: int = doc.get("received_stickers") or 0
        processed: int = doc.get("processed") or 0
        stickers: int = doc.get("stickers_created") or 0

        stats_data = {
            "Total time elapsed": f"<code>{util.time.format_duration_us(uptime)}</code>",
            "Messages received": (
                f"<code>{recv:,}</code> (<code>{_calc_ph(recv, uptime)}/h</code>) • "
                f"<code>{_calc_pct(recv_stickers, recv)}%</code> are stickers"
            ),
            "Messages sent": (
                f"<code>{sent:,}</code> (<code>{_calc_ph(sent, uptime)}/h</code>) • "
                f"<code>{_calc_pct(sent_stickers, sent)}%</code> are stickers"
            ),
            "Total messages sent": (
                f"<code>{_calc_pct(sent, sent + recv)}%</code> of all accounted messages"
            ),
            "Commands processed": (
                f"<code>{processed:,}</code> (<code>{_calc_ph(processed, uptime)}/h</code>) • "
                f"<code>{_calc_pct(processed, sent)}%</code> of sent messages"
            ),
            "Stickers created": (
                f"<code>{stickers:,}</code> (<code>{_calc_pd(stickers, uptime)}/day</code>)"
            ),
        }

        body = util.text.join_map(
            stats_data, heading="Stats since last reset", parse_mode="html"
        )
        return f"<blockquote expandable>\n{body}\n</blockquote>"
