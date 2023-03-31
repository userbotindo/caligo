import asyncio
import signal
from typing import TYPE_CHECKING, Any, List, Optional, Type, Union

from pyrogram import filters as filt
from pyrogram.client import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import AuthKeyDuplicated, AuthKeyInvalid, AuthKeyUnregistered
from pyrogram.handlers.callback_query_handler import CallbackQueryHandler
from pyrogram.handlers.deleted_messages_handler import DeletedMessagesHandler
from pyrogram.handlers.inline_query_handler import InlineQueryHandler
from pyrogram.handlers.message_handler import MessageHandler
from pyrogram.types import CallbackQuery, InlineQuery, Message, User

from caligo.util import tg, time

from .base import CaligoBase
from .database.storage import PersistentStorage

if TYPE_CHECKING:
    from .bot import Caligo

Handler = Union[
    CallbackQueryHandler, DeletedMessagesHandler, InlineQueryHandler, MessageHandler
]
Update = Union[CallbackQuery, InlineQuery, List[Message], Message]


class TelegramBot(CaligoBase):
    bot_client: Client
    client: Client
    prefix: str
    user: User
    uid: int
    start_time_us: int

    bot_user: User
    bot_uid: int

    __idle__: asyncio.Task[None]

    def __init__(self: "Caligo", **kwargs: Any) -> None:
        self.loaded = False

        self._mevent_handlers = {}

        self.__idle__ = None  # type: ignore

        super().__init__(**kwargs)

    async def init_client(self: "Caligo") -> None:
        api_id = self.config["telegram"]["api_id"]
        api_hash = self.config["telegram"]["api_hash"]

        # Initialize Telegram client with gathered parameters
        self.client = Client(
            name="caligo",
            api_id=api_id,
            api_hash=api_hash,
            workdir="caligo",
            in_memory=False,
            parse_mode=ParseMode.MARKDOWN,
        )
        self.client.storage = PersistentStorage(self.db)  # type: ignore

        self.prefix = self.config["bot"]["prefix"]
        # Override default prefix if found any saved in database
        data = await self.db["MAIN"].find_one({"_id": 0}, {"prefix": 1})
        if data and data.get("prefix"):
            self.prefix = data["prefix"]

    async def start(self: "Caligo") -> None:
        self.log.info("Starting")
        await self.init_client()

        # Command handler
        self.client.add_handler(
            MessageHandler(
                self.on_command,
                filters=(self.command_predicate() & filt.me & filt.outgoing),
            ),
            0,
        )

        # Conversation handler
        self.client.add_handler(
            MessageHandler(self.on_conversation, filters=self.conversation_predicate()),
            0,
        )

        # Load modules
        self.load_all_modules()
        await self.dispatch_event("load")
        self.loaded = True

        async with asyncio.Lock():
            await self.client.start()

            user = await self.client.get_me()
            if not isinstance(user, User):
                raise TypeError("Missing full self user information")

            self.user = user
            self.uid = user.id

        self.start_time_us = time.usec()
        await self.dispatch_event("start", self.start_time_us)

        self.log.info("Bot is ready")
        await self.dispatch_event("started")

    async def idle(self: "Caligo") -> None:
        if self.__idle__:
            raise RuntimeError("This bot instance is already running")

        signals = {
            k: v
            for v, k in signal.__dict__.items()
            if v.startswith("SIG") and not v.startswith("SIG_")
        }

        def clear_handler() -> None:
            for signame in (signal.SIGINT, signal.SIGTERM, signal.SIGABRT):
                self.loop.remove_signal_handler(signame)

        def signal_handler(signum: int):

            print(flush=True)
            self.log.info("Stop signal received ('%s').", signals[signum])
            clear_handler()

            self.__idle__.cancel()

        for name in (signal.SIGINT, signal.SIGTERM, signal.SIGABRT):
            self.loop.add_signal_handler(name, signal_handler)

        while True:
            self.__idle__ = asyncio.create_task(asyncio.sleep(300), name="idle")

            try:
                await self.__idle__
            except asyncio.CancelledError:
                break

    async def run(self: "Caligo") -> None:
        if self.__idle__:
            raise RuntimeError("This bot instance is already running")

        try:
            # Start client
            try:
                await self.start()
            except KeyboardInterrupt:
                self.log.warning("Received interrupt while connecting")
                return
            except (AuthKeyDuplicated, AuthKeyInvalid, AuthKeyUnregistered) as e:
                self.log.exception(
                    "Your session is invalid, please regenerate it", exc_info=e
                )

                # Delete session from DB
                await self.db["SESSION"].delete_one({"_id": 0})
                return

            await self.idle()
        finally:
            await self.stop()

    def update_module_event(
        self: "Caligo",
        name: str,
        event_type: Type[Handler],
        filters: Optional[filt.Filter] = None,
        group: int = 0,
    ) -> None:
        if name in self.listeners:
            if name not in self._mevent_handlers:

                async def update_event(_: Client, event: Update) -> None:
                    await self.dispatch_event(name, event)

                if filters is not None:
                    event_info = (event_type(update_event, filters), group)
                else:
                    event_info = (event_type(update_event), group)

                self.client.add_handler(*event_info)
                self._mevent_handlers[name] = event_info
        elif name in self._mevent_handlers:
            self.client.remove_handler(*self._mevent_handlers[name])
            del self._mevent_handlers[name]

    def update_module_events(self: "Caligo") -> None:
        self.update_module_event(
            "message",
            MessageHandler,
            filters=~filt.new_chat_members
            & ~filt.left_chat_member
            & ~filt.migrate_from_chat_id
            & ~filt.migrate_to_chat_id,
            group=0,
        )
        self.update_module_event("message_delete", DeletedMessagesHandler, group=1)
        self.update_module_event(
            "chat_action",
            MessageHandler,
            filt.new_chat_members | filt.left_chat_member,
            group=1,
        )

    @property
    def events_activated(self: "Caligo") -> int:
        return len(self._mevent_handlers)

    def redact_message(self: "Caligo", text: str) -> str:
        redacted = "[REDACTED]"

        api_id = str(self.config["telegram"]["api_id"])
        api_hash = self.config["telegram"]["api_hash"]
        db_uri = self.config["bot"]["db_uri"]

        if api_id in text:
            text = text.replace(api_id, redacted)
        if api_hash in text:
            text = text.replace(api_hash, redacted)
        if db_uri in text:
            text = text.replace(db_uri, redacted)

        return text

    async def respond(
        self: "Caligo",
        msg: Message,
        text: str = "",
        *,
        input_arg: str = "",
        mode: Optional[str] = None,
        redact: bool = True,
        response: Optional[Message] = None,
        **kwargs: Any,
    ) -> Message:
        if text:

            if redact:
                text = self.redact_message(text)

            # send as file if text > 4096
            if len(str(text)) > tg.MESSAGE_CHAR_LIMIT:
                await msg.edit("Sending output as a file.")
                response = await tg.send_as_document(text, msg, input_arg)

                await msg.delete()
                return response

        # Default to disabling link previews in responses
        if "disable_web_page_preview" not in kwargs:
            kwargs["disable_web_page_preview"] = True

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
                response = await msg.reply(text, reply_to_message_id=msg.id, **kwargs)
            await msg.delete()
            return response

        raise ValueError(f"Unknown response mode '{mode}'")
