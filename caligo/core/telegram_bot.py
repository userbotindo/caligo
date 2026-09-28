import asyncio
import platform
import signal
from functools import partial
from hashlib import sha256
from typing import TYPE_CHECKING, Any, List, Optional, Type, Union

from anyio import Path as AsyncPath
from pyrogram import filters as filt
from pyrogram.client import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import AuthKeyDuplicated, AuthKeyInvalid, AuthKeyUnregistered
from pyrogram.handlers.callback_query_handler import CallbackQueryHandler
from pyrogram.handlers.deleted_messages_handler import DeletedMessagesHandler
from pyrogram.handlers.inline_query_handler import InlineQueryHandler
from pyrogram.handlers.message_handler import MessageHandler
from pyrogram.types import CallbackQuery, InlineQuery, LinkPreviewOptions, Message, User

from caligo.util import tg, time
from caligo.version import __version__

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
        sleep_threshold = self.config["telegram"].get("sleep_threshold", 60)
        device_model = self.config["telegram"].get("device_model", "Caligo Userbot")
        system_version = (
            self.config["telegram"].get("system_version")
            or f"{platform.system()} {platform.machine()}"
        )
        app_version = self.config["telegram"].get(
            "app_version", f"Caligo v{__version__}"
        )
        lang_code = self.config["telegram"].get("lang_code", "en")
        system_lang_code = self.config["telegram"].get("system_lang_code", "en")

        # Initialize Telegram client with gathered parameters
        self.client = Client(
            name="caligo",
            api_id=api_id,
            api_hash=api_hash,
            workdir="caligo",
            in_memory=False,
            parse_mode=ParseMode.MARKDOWN,
            sleep_threshold=sleep_threshold,
            device_model=device_model,
            system_version=system_version,
            app_version=app_version,
            lang_code=lang_code,
            system_lang_code=system_lang_code,
        )
        self.client.storage = PersistentStorage(self.db)  # type: ignore

        self.prefix = self.config["bot"]["prefix"]
        # Override default prefix and delete_after if found any saved in database
        data = await self.db["MAIN"].find_one(
            {"_id": 0}, {"prefix": 1, "delete_after": 1}
        )
        if data:
            if data.get("prefix"):
                self.prefix = data["prefix"]
            if "delete_after" in data:
                self.delete_after = data["delete_after"]

        # Initialize bot client helper if has token
        bot_token = self.config["telegram"]["helper"].get("token")
        if bot_token:
            # Load session helper from database
            sess = await self.db.get_collection("SESSION_HELPER").find_one(
                {"_id": sha256(str(api_id).encode()).hexdigest()}
            )
            file = AsyncPath("caligo/caligo_helper.session")
            if sess and not await file.exists():
                self.log.info("Loading session helper from database")
                await file.write_bytes(sess["session"])

            self.client_helper = Client(
                name="caligo_helper",
                api_id=api_id,
                api_hash=api_hash,
                bot_token=bot_token,
                workdir="caligo",
                sleep_threshold=sleep_threshold,
                device_model=f"{device_model} Helper",
                system_version=system_version,
                app_version=app_version,
                lang_code=lang_code,
                system_lang_code=system_lang_code,
            )

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

            if self.helper_initialized:
                await self.client_helper.start()
                bot_user = await self.client_helper.get_me()
                if isinstance(bot_user, User):
                    self.bot_user = bot_user
                    self.bot_uid = bot_user.id

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
                try:
                    self.loop.remove_signal_handler(signame)
                except (NotImplementedError, RuntimeError):
                    pass

        def signal_handler(signum: int):

            print(flush=True)
            self.log.info("Stop signal received ('%s').", signals[signum])
            clear_handler()

            if self.__idle__ and not self.__idle__.done():
                self.__idle__.cancel()

        for name in (signal.SIGINT, signal.SIGTERM, signal.SIGABRT):
            try:
                self.loop.add_signal_handler(name, partial(signal_handler, name))
            except (NotImplementedError, RuntimeError):
                pass

        while True:
            self.__idle__ = asyncio.create_task(asyncio.sleep(300), name="idle")

            try:
                await self.__idle__
            except asyncio.CancelledError:
                break

        self.__idle__ = None

    async def run(self: "Caligo") -> None:
        if self.__idle__:
            raise RuntimeError("This bot instance is already running")

        try:
            # Start client
            try:
                await self.start()
            except (KeyboardInterrupt, asyncio.CancelledError):
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

    def update_helper_event(
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
                    if isinstance(event, CallbackQuery):
                        try:
                            await event.answer()
                        except Exception:
                            pass

                if filters is not None:
                    event_info = (event_type(update_event, filters), group)
                else:
                    event_info = (event_type(update_event), group)

                self.client_helper.add_handler(*event_info)
                self._mevent_handlers[name] = event_info
        elif name in self._mevent_handlers:
            self.client_helper.remove_handler(*self._mevent_handlers[name])
            del self._mevent_handlers[name]

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
        self.update_module_event(
            "chat_action",
            MessageHandler,
            filt.new_chat_members | filt.left_chat_member,
            group=1,
        )
        if self.helper_initialized:
            self.update_helper_event("callback_query", CallbackQueryHandler)
            self.update_helper_event("inline_query", InlineQueryHandler)

    @property
    def events_activated(self: "Caligo") -> int:
        return len(self._mevent_handlers)

    @property
    def helper_initialized(self: "Caligo") -> bool:
        return hasattr(self, "client_helper") and isinstance(self.client_helper, Client)

    def _get_redact_secrets(self: "Caligo") -> Tuple[str, ...]:
        if not hasattr(self, "_redact_secrets"):
            secrets: List[str] = []
            try:
                tg_cfg = self.config.get("telegram", {})
                api_id = tg_cfg.get("api_id")
                if api_id is not None:
                    secrets.append(str(api_id))
                api_hash = tg_cfg.get("api_hash")
                if api_hash:
                    secrets.append(str(api_hash))
                bot_cfg = self.config.get("bot", {})
                db_uri = bot_cfg.get("db_uri")
                if db_uri:
                    secrets.append(str(db_uri))
                helper_token = tg_cfg.get("helper", {}).get("token")
                if helper_token:
                    secrets.append(str(helper_token))
            except Exception:
                pass
            self._redact_secrets = tuple(secrets)
        return self._redact_secrets

    def redact_message(self: "Caligo", text: str) -> str:
        redacted = "[REDACTED]"
        for secret in self._get_redact_secrets():
            if secret in text:
                text = text.replace(secret, redacted)

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
        if "disable_web_page_preview" in kwargs:
            disabled = kwargs.pop("disable_web_page_preview")
            if "link_preview_options" not in kwargs and disabled is not None:
                kwargs["link_preview_options"] = LinkPreviewOptions(is_disabled=disabled)
        elif "link_preview_options" not in kwargs:
            kwargs["link_preview_options"] = LinkPreviewOptions(is_disabled=True)

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
                kwargs.pop("link_preview_options", None)
                if msg.reply_to_message:
                    response = await msg.reply_to_message.reply_document(**kwargs)
                else:
                    response = await self.client.send_document(msg.chat.id, **kwargs)
            else:
                if msg.reply_to_message:
                    response = await msg.reply_to_message.reply(text, **kwargs)
                else:
                    response = await self.client.send_message(msg.chat.id, text, **kwargs)
            await msg.delete()
            return response

        raise ValueError(f"Unknown response mode '{mode}'")
