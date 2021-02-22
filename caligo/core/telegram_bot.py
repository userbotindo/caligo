from typing import TYPE_CHECKING, Any

from .base import Base

if TYPE_CHECKING:
    from .bot import Bot

import os

import pyrogram


class TelegramBot(Base):
    # Initialized during instantiation
    loaded: bool

    # Initialized during startup
    client: pyrogram.Client
    prefix: str
    user: pyrogram.types.User
    uid: int
    start_time_us: int

    def __init__(self: "Bot", **kwargs: Any) -> None:
        self.loaded = False

        super().__init__(**kwargs)

    async def init_client(self: "Bot") -> None:
        api_id = self.getConfig("api_id")
        if api_id == 0:
            raise ValueError("API ID is empty")

        api_hash = self.getConfig("api_hash")
        if not isinstance(api_hash, str):
            raise TypeError("API HASH must be a string")

        string_session = self.getConfig("string_session")

        # Initialize TelegramClient with gathered parameters
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

        # Start TelegramClient
        await self.client.start()

        # Parse User info
        user = await self.client.get_me()
        if not isinstance(user, pyrogram.types.User):
            raise TypeError("Missing full self user information")
        self.user = user
        self.uid = user.id

    async def run(self: "Bot") -> None:
        try:
            # Start Client
            await self.start()

            # Idling client until disconnected
            self.log.info("Idling...")
            await pyrogram.idle()
        finally:
            await self.stop()

    def getConfig(self, name: str):
        config = {
            "api_id": os.environ.get("API_ID", 0),
            "api_hash": os.environ.get("API_HASH", None),
            "string_session": os.environ.get("STRING_SESSION", None)
        }
        return config.get(name)

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
