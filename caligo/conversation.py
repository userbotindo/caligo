import asyncio
import inspect
import logging
from typing import TYPE_CHECKING, Union

import pyrogram
from pyrogram.raw import functions

from . import util

if TYPE_CHECKING:
    from .core import Bot


class AlreadyInConversation(Exception):
    pass


class Conversation:

    log: logging.Logger

    def __init__(
        self,
        bot: "Bot",
        input_chat: Union[str, int],
        timeout: int,
        max_messages: int
    ):
        self.bot = bot
        self.log = self.bot.log

        self._input_chat = input_chat
        self._timeout = timeout
        self._max_incoming = max_messages

        self._counter = 0

        self._chat_id: int

    async def send_message(self, text, **kwargs) -> pyrogram.types.Message:
        sent = await self.bot.client.send_message(self._chat_id, text, **kwargs)

        return sent

    async def send_file(self, document, **kwargs) -> pyrogram.types.Message:
        file = await self.bot.client.send_document(self._chat_id, document, **kwargs)

        return file

    async def get_response(self, **kwargs) -> pyrogram.types.Message:
        response = await self._get_message()

        return response

    async def get_reply(self, **kwargs) -> pyrogram.types.Message:
        filters = pyrogram.filters.reply
        response = await self._get_message(filters)

        return response

    async def _get_message(self, filters=None, **kwargs) -> pyrogram.types.Message:
        if self._counter >= self._max_incoming:
            raise ValueError("Received max messages")

        fut = self.bot.CONVERSATION[self._chat_id]
        timeout = kwargs.get("timeout") or self._timeout

        before = util.time.usec()
        while True:
            after = util.time.usec()
            el_us = before - after
            result = await self._get_result(fut, timeout - el_us)

            if filters is not None and callable(filters):
                ready = filters(self.bot.client, result)
                if inspect.iscoroutine(ready):
                    ready = await ready
                if not ready:
                    continue

            break

        self._counter += 1
        if kwargs.get("mark_read"):
            await self._mark_read()

        return result

    async def _get_result(
        self,
        future: asyncio.Queue,
        due: Union[int, float],
        **kwargs
    ) -> pyrogram.types.Message:
        return await asyncio.wait_for(future.get(), max(0.1, due))

    async def _mark_read(self, **kwargs) -> None:
        await asyncio.gather(
            self.bot.client.send(functions.messages.ReadMentions(
                peer=await self.bot.client.resolve_peer(
                    self._chat_id, **kwargs)
                )
            ),
            self.bot.client.read_history(self._chat_id, **kwargs)
        )

    async def __aenter__(self) -> "Conversation":
        self._chat_id = self._input_chat
        if not isinstance(self._chat_id, int):
            chat = await self.bot.client.get_chat(self._input_chat)
            self._chat_id = chat.id
        self.log.info(f"Opening conversation with '{self._chat_id}'")

        if self._chat_id in self.bot.CONVERSATION:
            self.log.error(f"Conversation with '{self._chat_id}' already open")
            raise AlreadyInConversation

        self.bot.CONVERSATION[self._chat_id] = asyncio.Queue(self._max_incoming)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.log.info(f"Closing conversation with '{self._chat_id}'")
        conv = self.bot.CONVERSATION[self._chat_id]

        conv.put_nowait(None)
        del self.bot.CONVERSATION[self._chat_id]
