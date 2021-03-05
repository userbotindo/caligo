import asyncio
import functools
from typing import Any, Callable

import pyrogram

from . import util

ListenerFunc = Any
Decorator = Callable[[ListenerFunc], ListenerFunc]


def priority(_prio: int) -> Decorator:
    """Sets priority on the given listener function."""

    def prio_decorator(func: ListenerFunc) -> ListenerFunc:
        setattr(func, "_listener_priority", _prio)
        return func

    return prio_decorator


class Listener:
    event: str
    func: ListenerFunc
    module: Any
    priority: int

    def __init__(self, event: str, func: ListenerFunc, mod: Any,
                 prio: int) -> None:
        self.event = event
        self.func = func
        self.module = mod
        self.priority = prio

    def __lt__(self, other: "Listener") -> bool:
        return self.priority < other.priority


@util.mongkey.patch(pyrogram.client.Client)
class Client:

    @util.mongkey.patchable
    def __init__(self, *args, **kwargs):
        self.conversation = {}

        self.old__init__(*args, **kwargs)

    @util.mongkey.patchable
    async def listen(self, chat_id, filters=None, timeout=None):
        if type(chat_id) != int:
            chat = await self.get_chat(chat_id)
            chat_id = chat.id

        future = asyncio.get_event_loop().create_future()
        future.add_done_callback(
            functools.partial(self.clear_listener, chat_id)
        )
        self.conversation.update({
            chat_id: {"future": future, "filters": filters}
        })
        return await asyncio.wait_for(future, timeout)

    @util.mongkey.patchable
    async def ask(
        self,
        chat_id,
        text,
        filters=None,
        timeout=None,
        *args,
        **kwargs
    ):  # skipcq: PYL-W1113
        request = await self.send_message(chat_id, text, *args, **kwargs)
        response = await self.listen(chat_id, filters, timeout)
        response.request = request
        return response

    @util.mongkey.patchable
    def clear_listener(self, chat_id, future):
        if future == self.conversation[chat_id]:
            self.conversation.pop(chat_id, None)

    @util.mongkey.patchable
    def cancel_listener(self, chat_id):
        listener = self.conversation.get(chat_id)
        if not listener or listener['future'].done():
            return

        listener['future'].set_exception(asyncio.CancelledError())
        self.clear_listener(chat_id, listener['future'])


@util.mongkey.patch(pyrogram.handlers.message_handler.MessageHandler)
class MessageHandler:

    @util.mongkey.patchable
    def __init__(self, callback: callable, filters=None):
        self.user_callback = callback
        self.old__init__(self.resolve_listener, filters)

    @util.mongkey.patchable
    async def resolve_listener(self, client, message, *args):
        listener = client.conversation.get(message.chat.id)
        if listener and not listener['future'].done():
            listener['future'].set_result(message)
        else:
            if listener and listener['future'].done():
                client.clear_listener(message.chat.id, listener['future'])
            await self.user_callback(client, message, *args)

    @util.mongkey.patchable
    async def check(self, client, update):
        listener = client.conversation.get(update.chat.id)

        if listener and not listener['future'].done():
            return await listener['filters'](
                client, update) if callable(listener['filters']) else True

        return (
            await self.filters(client, update)
            if callable(self.filters)
            else True
        )
