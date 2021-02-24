from typing import TYPE_CHECKING, Any, Optional

import pyrogram
from pyrogram.filters import Filter
from pyrogram.handlers import MessageHandler, DeletedMessagesHandler, UserStatusHandler
from pyrogram.handlers.handler import Handler

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
        self.loaded = False
        self.getConfig = BotConfig()

        self._mevent_handlers = {}

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

        # Load modules
        self.load_all_modules()
        await self.dispatch_event("load")
        self.loaded = True

        # iter first because can't use *.keys()
        commands = []
        for cmd in self.commands.keys():
            commands.append(cmd)

        self.client.add_handler(
            MessageHandler(
                self.on_command, filters=(
                    pyrogram.filters.command(commands, prefixes=".", case_sensitive=True) &
                    pyrogram.filters.me &
                    pyrogram.filters.outgoing
                    )
                ), 0)

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

    def update_module_event(
        self: "Bot", name: str, handler_type: Handler,
        filters: Optional[Filter] = None,
        group: int = 0
    ) -> None:
        if name in self.listeners:
            # Add if there ARE listeners and it's NOT already registered
            if name not in self._mevent_handlers:

                async def update_handler(client, event) -> None:
                    if type(event) is not pyrogram.types.list.List and event.command:
                        self.log.info("Not processing from command event")
                        return
                    await self.dispatch_event(name, event)

                handler_info = self.client.add_handler(
                    handler_type(update_handler, filters), group)
                self._mevent_handlers[name] = handler_info
        elif name in self._mevent_handlers:
            # Remove if there are NO listeners and it's ALREADY registered
            self.client.remove_handler(*self._mevent_handlers[name])
            del self._mevent_handlers[name]

    def update_module_events(self: "Bot") -> None:
        self.update_module_event("message", MessageHandler, pyrogram.filters.all, 1)
        self.update_module_event("message_delete", DeletedMessagesHandler, pyrogram.filters.all, 2)
        self.update_module_event("user_update", UserStatusHandler, 3)

    def redact_message(self, text: str) -> str:
        api_id = self.getConfig.api_hash
        api_hash = self.getConfig.api_hash
        string_session = self.getConfig.string_session

        if api_id in text:
            text = text.replace(api_id, "[REDACTED]")
        if api_hash in text:
            text = text.replace(api_hash, "[REDACTED]")
        if string_session in text:
            text = text.replace(string_session, "[REDACTED]")

        return text

    async def respond(
        self: "Bot",
        msg: pyrogram.types.Message,
        text: Optional[str] = None,
        *,
        mode: Optional[str] = None,
        redact: Optional[bool] = True,
        response: Optional[pyrogram.types.Message] = None,
        **kwargs: Any,
    ) -> pyrogram.types.Message:
        if text is not None:
            text = self.redact_message(text)

        # Default to disabling link previews in responses
        if "disable_web_page_preview" not in kwargs:
            kwargs["disable_web_page_preview"] = False

        # Use selected response mode if not overridden by invoker
        if mode is None:
            mode = "edit"

        if mode == "edit":
            return await msg.edit(text=text, **kwargs)

        if mode == "reply":
            if response is not None:
                # Already replied, so just edit the existing reply to reduce spam
                return await response.edit(text=text, **kwargs)

            # Reply since we haven't done so yet
            return await msg.reply(text, **kwargs)

        if mode == "repost":
            if response is not None:
                # Already reposted, so just edit the existing reply to reduce spam
                return await response.edit(text=text, **kwargs)

            # Repost since we haven't done so yet
            response = await msg.reply(text, reply_to=msg.reply_to_msg_id, **kwargs)
            await msg.delete()
            return response

        raise ValueError(f"Unknown response mode '{mode}'")
