from typing import TYPE_CHECKING, Any

import pyrogram

from .base import Base
from ..util import BotConfig

if TYPE_CHECKING:
    from .bot import Bot


class TelegramBot(Base):
    client: pyrogram.Client
    getConfig: BotConfig
    prefix: str
    user: pyrogram.types.User
    uid: int
    start_time_us: int

    def __init__(self: "Bot", **kwargs: Any) -> None:
        self.getConfig = BotConfig()

        super().__init__(**kwargs)

    async def init_client(self: "Bot") -> None:
        api_id = self.getConfig.api_id
        if api_id == 0:
            raise ValueError("API ID is invalid nor empty.")

        api_hash = self.getConfig.api_hash
        if not isinstance(api_hash, str):
            raise TypeError("API HASH must be a string")

        string_session = self.getConfig.string_session

        if isinstance(string_session, str):
            mode = string_session
        else:
            mode = ":memory:"
        self.client = pyrogram.Client(
            api_id=api_id,
            api_hash=api_hash,
            session_name=mode
        )

    async def start(self: "Bot") -> None:
        self.log.info("Starting")
        await self.init_client()

        await self.client.start()

        user = await self.client.get_me()
        if not isinstance(user, pyrogram.types.User):
            raise TypeError("Missing full self user information")
        self.user = user
        self.uid = user.id

    async def run(self: "Bot") -> None:
        try:
            await self.start()

            self.log.info("Idling...")
            await pyrogram.idle()
        finally:
            await self.stop()

    def redact_message(self, text: str) -> str:
        api_id = self.getConfig("api_hash")
        api_hash = self.getConfig("api_hash")
        string_session = self.getConfig("string_session")

        if api_id in text:
            text = text.replace(api_id, "[REDACTED]")
        if api_hash in text:
            text = text.replace(api_hash, "[REDACTED]")
        if string_session in text:
            text = text.replace(string_session, "[REDACTED]")

        return text
