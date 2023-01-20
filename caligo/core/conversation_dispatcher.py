import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, Union

from pyrogram.client import Client
from pyrogram.filters import Filter, create
from pyrogram.types import Message

from ..conversation import Conversation, ConversationExistError
from .base import CaligoBase

if TYPE_CHECKING:
    from .bot import Caligo


class ConversationDispatcher(CaligoBase):
    CONVERSATION: Dict[int, asyncio.Queue]

    def __init__(self: "Caligo", **kwargs: Any) -> None:
        self.CONVERSATION = {}

        super().__init__(**kwargs)

    def conversation_predicate(self: "CaligoBase") -> Filter:
        async def func(_, __, conv: Message):
            return bool(
                self.CONVERSATION and conv.chat and conv.chat.id in self.CONVERSATION
            )

        return create(func)

    @asynccontextmanager
    async def conversation(
        self: "Caligo",
        chat_id: Union[str, int],
        *,
        timeout: int = 7,
        max_messages: int = 7,
    ) -> AsyncGenerator[Conversation, None]:
        conv = await Conversation.new(self, chat_id, timeout, max_messages)
        chat_name = conv.chat.title if conv.chat.title else conv.chat.first_name
        if conv.chat.id in self.CONVERSATION:
            raise ConversationExistError(f"Conversation with '{chat_name}' exist")

        self.CONVERSATION[conv.chat.id] = asyncio.Queue(max_messages)

        try:
            yield conv
        finally:
            self.CONVERSATION[conv.chat.id].put_nowait(None)
            del self.CONVERSATION[conv.chat.id]

    async def on_conversation(
        self: "Caligo", client: Client, msg: Message  # skipcq: PYL-W0613
    ) -> None:
        cache = self.CONVERSATION[msg.chat.id]
        cache.put_nowait(msg)
        msg.continue_propagation()
