from hashlib import sha256
from typing import ClassVar

from aiopath import AsyncPath
from bson.binary import Binary
from pyrogram.raw.functions.updates.get_state import GetState

from caligo import module


class Main(module.Module):
    name: ClassVar[str] = "Main"

    async def on_load(self) -> None:
        self.db = self.bot.db["SESSION"]

    async def on_stop(self) -> None:
        return

        file = AsyncPath("caligo/caligo.session")
        if not await file.exists():
            return

        data = await self.bot.client.invoke(GetState())
        await self.db.update_one(
            {"_id": sha256(self.bot.config["api_id"].encode()).hexdigest()},
            {
                "$set": {
                    "session": Binary(await file.read_bytes()),
                    "date": data.date,
                    "pts": data.pts,
                    "qts": data.qts,
                    "seq": data.seq,
                }
            },
            upsert=True,
        )
