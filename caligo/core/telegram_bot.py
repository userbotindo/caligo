import asyncio
import signal
from typing import TYPE_CHECKING, Any, Optional

import pyrogram
from pyrogram import filters, Client
from pyrogram.filters import Filter, create
from pyrogram.handlers import (
    CallbackQueryHandler,
    DeletedMessagesHandler,
    InlineQueryHandler,
    MessageHandler,
    UserStatusHandler
)
from pyrogram.handlers.handler import Handler

from ..util import BotConfig, silent, time, tg
from .base import Base

if TYPE_CHECKING:
    from .bot import Bot


class TelegramBot(Base):
    client: Client
    getConfig: BotConfig
    is_running: bool
    prefix: str
    user: pyrogram.types.User
    uid: int
    start_time_us: int

    bot_user: pyrogram.types.User
    bot_uid: int

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
        self.client = Client(api_id=api_id,
                             api_hash=api_hash,
                             session_name=mode)

        token = self.getConfig.token
        if token is not None:
            if not isinstance(token, str):
                raise TypeError("BOT TOKEN must be a string")

            self.client.bot = Client(api_id=api_id,
                                     api_hash=api_hash,
                                     bot_token=token,
                                     session_name=":memory:")

    async def start(self: "Bot") -> None:
        self.log.info("Starting")
        await self.init_client()

        # Load prefix
        db = self.get_db("core")
        try:
            self.prefix = (await db.find_one({"_id": "Core"}))["prefix"]
        except TypeError:
            self.prefix = "."  # Default is '.'-dot you can change later

            await db.find_one_and_update(
                {"_id": "Core"},
                {
                    "$set": {"prefix": self.prefix}
                },
                upsert=True
            )

        self.client.add_handler(
            MessageHandler(
                self.on_command,
                filters=(
                    self.command_predicate() &
                    filters.me &
                    filters.outgoing
                )
            ), 0)

        self.client.add_handler(
            MessageHandler(
                self.on_conversation,
                filters=self.conversation_predicate()
            ), 0)

        # Load modules
        self.load_all_modules()
        await self.dispatch_event("load")
        self.loaded = True

        async with silent():
            await self.client.start()
            if self.has_bot:
                await self.client.bot.start()

        user = await self.client.get_me()
        if not isinstance(user, pyrogram.types.User):
            raise TypeError("Missing full self user information")
        self.user = user
        self.uid = user.id

        if self.has_bot:
            bot = await self.client.bot.get_me()
            if not isinstance(user, pyrogram.types.User):
                raise TypeError("Missing full self bot user information")
            self.bot_user = bot
            self.bot_uid = bot.id

        self.start_time_us = time.usec()
        await self.dispatch_event("start", self.start_time_us)

        self.log.info("Bot is ready")
        await self.dispatch_event("started")

    async def idle(self: "Bot") -> None:
        def signal_handler(_, __):

            self.log.info(f"Stop signal received ({_}).")
            self.is_running = False

        for name in (signal.SIGINT, signal.SIGTERM, signal.SIGABRT):
            signal.signal(name, signal_handler)

        self.is_running = True

        while self.is_running:
            await asyncio.sleep(1)

    async def run(self: "Bot") -> None:
        try:
            await self.start()

            self.log.info("Idling...")
            await self.idle()
        finally:
            if not self.stop_manual:
                await self.stop()

    def update_module_event(self: "Bot",
                            name: str,
                            event_type: Handler,
                            filt: Optional[Filter] = None,
                            group: int = 0) -> None:
        if name in self.listeners:
            if name not in self._mevent_handlers:

                async def update_event(_, event) -> None:
                    await self.dispatch_event(name, event)

                event_info = self.client.add_handler(  # skipcq: PYL-E1111
                    event_type(update_event, filt), group)
                self._mevent_handlers[name] = event_info
        elif name in self._mevent_handlers:
            self.client.remove_handler(*self._mevent_handlers[name])
            del self._mevent_handlers[name]

    def update_bot_module_event(self: "Bot",
                                name: str,
                                event_type: Handler,
                                filt: Optional[Filter] = None,
                                group: int = 0) -> None:
        if name in self.listeners:
            if name not in self._mevent_handlers:

                async def update_event(_, event) -> None:
                    await self.dispatch_event(name, event)

                event_info = self.client.bot.add_handler(  # skipcq: PYL-E1111
                    event_type(update_event, filt), group)
                self._mevent_handlers[name] = event_info
        elif name in self._mevent_handlers:
            self.client.bot.remove_handler(*self._mevent_handlers[name])
            del self._mevent_handlers[name]

    def update_module_events(self: "Bot") -> None:
        self.update_module_event("message", MessageHandler,
                                 filters.all & ~filters.edited &
                                 ~self.command_predicate() &
                                 ~TelegramBot.chat_action(), 3)
        self.update_module_event("message_edit", MessageHandler,
                                 filters.edited, 3)
        self.update_module_event("message_delete", DeletedMessagesHandler,
                                 filters.all, 3)
        self.update_module_event("chat_action", MessageHandler,
                                 TelegramBot.chat_action(), 3)
        self.update_module_event("user_update", UserStatusHandler,
                                 filters.all, 5)
        if self.has_bot:
            self.update_bot_module_event("callback_query", CallbackQueryHandler,
                                         filters.regex(pattern=r"menu\((\w+)\)"))
            self.update_bot_module_event("inline_query", InlineQueryHandler)

    @property
    def events_activated(self: "Bot") -> int:
        return len(self._mevent_handlers)

    @property
    def has_bot(self: "Bot") -> bool:
        return hasattr(self.client, "bot")

    def redact_message(self: "Bot", text: str) -> str:
        redacted = "[REDACTED]"

        api_id = self.getConfig.api_hash
        api_hash = self.getConfig.api_hash
        db_uri = self.getConfig.db_uri
        gdrive_secret = self.getConfig.gdrive_secret
        string_session = self.getConfig.string_session
        token = self.getConfig.token

        if api_id in text:
            text = text.replace(api_id, redacted)
        if api_hash in text:
            text = text.replace(api_hash, redacted)
        if db_uri in text:
            text = text.replace(db_uri, redacted)
        if gdrive_secret is not None:
            client_id = gdrive_secret["installed"].get("client_id")
            client_secret = gdrive_secret["installed"].get("client_secret")

            if client_id in text:
                text = text.replace(client_id, redacted)
            if client_secret in text:
                text = text.replace(client_secret, redacted)
        if string_session in text:
            text = text.replace(string_session, redacted)
        if token is not None and token in text:
            text = text.replace(token, redacted)

        return text

    @staticmethod
    def chat_action() -> Filter:
        async def func(__, ___, chat: pyrogram.types.Message):
            return bool(chat.new_chat_members or chat.left_chat_member)

        return create(func)

    async def respond(
        self: "Bot",
        msg: pyrogram.types.Message,
        text: Optional[str] = None,
        *,
        input_arg: Optional[str] = None,
        mode: Optional[str] = None,
        redact: Optional[bool] = True,
        response: Optional[pyrogram.types.Message] = None,
        **kwargs: Any,
    ) -> pyrogram.types.Message:
        if text is not None:

            if redact:
                text = self.redact_message(text)

            # send as file if text > 4096
            if len(text) > tg.MESSAGE_CHAR_LIMIT:
                await msg.edit("Sending output as a file.")
                response = await tg.send_as_document(
                    text,
                    msg,
                    input_arg
                )

                await msg.delete()
                return response

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
            if kwargs.get("document"):
                del kwargs["disable_web_page_preview"]
                response = await msg.reply_document(**kwargs)
            else:
                response = await msg.reply(text,
                                           reply_to_message_id=msg.message_id,
                                           **kwargs)
            await msg.delete()
            return response

        raise ValueError(f"Unknown response mode '{mode}'")
