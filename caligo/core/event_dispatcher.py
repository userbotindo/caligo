import asyncio
import bisect
import re
from typing import (
    TYPE_CHECKING,
    Any,
    MutableMapping,
    MutableSequence,
    Optional,
    Pattern
)

from pyrogram.types import Message, CallbackQuery, InlineQuery

from .. import module, util
from ..listener import Listener, ListenerFunc
from .base import Base

if TYPE_CHECKING:
    from .bot import Bot


class EventDispatcher(Base):
    listeners: MutableMapping[str, MutableSequence[Listener]]

    def __init__(self: "Bot", **kwargs: Any) -> None:
        self.listeners = {}

        super().__init__(**kwargs)

    def register_listener(
        self: "Bot",
        mod: module.Module,
        event: str,
        func: ListenerFunc,
        *,
        priority: Optional[int] = 100,
        pattern: Optional[Pattern[str]] = None
    ) -> None:
        listener = Listener(event, func, mod, priority, pattern)

        if event in self.listeners:
            bisect.insort(self.listeners[event], listener)
        else:
            self.listeners[event] = [listener]

        self.update_module_events()

    def unregister_listener(self: "Bot", listener: Listener) -> None:
        self.listeners[listener.event].remove(listener)
        if not self.listeners[listener.event]:
            del self.listeners[listener.event]

        self.update_module_events()

    def register_listeners(self: "Bot", mod: module.Module) -> None:
        for event, func in util.misc.find_prefixed_funcs(mod, "on_"):
            done = True
            try:
                self.register_listener(mod,
                                       event,
                                       func,
                                       priority=getattr(func,
                                                        "_listener_priority",
                                                        100),
                                       pattern=getattr(func,
                                                       "_listener_pattern",
                                                       None))
                done = True
            finally:
                if not done:
                    self.unregister_listeners(mod)

    def unregister_listeners(self: "Bot", mod: module.Module) -> None:
        to_unreg = []

        for lst in self.listeners.values():
            for listener in lst:
                if listener.module == mod:
                    to_unreg.append(listener)

        for listener in to_unreg:
            self.unregister_listener(listener)

    async def dispatch_event(self: "Bot",
                             event: str,
                             *args: Any,
                             wait: bool = True,
                             **kwargs: Any) -> None:
        tasks = set()

        try:
            listeners = self.listeners[event]
        except KeyError:
            return None

        if not listeners:
            return

        for lst in listeners:
            if lst.pattern is not None:
                if isinstance(lst.pattern, str):
                    lst.pattern = re.compile(lst.pattern)

                update = args[0]
                if isinstance(update, Message):
                    value = update.text or args[0].caption
                elif isinstance(update, CallbackQuery):
                    value = update.data
                elif isinstance(update, InlineQuery):
                    value = update.query
                else:
                    self.log.error(f"Regex pattern '{event}' doesn't work "
                                   f"with {type(update)}")
                    continue

                if value:
                    update.matches = list(lst.pattern.finditer(value)) or None

            task = self.loop.create_task(lst.func(*args, **kwargs))
            tasks.add(task)

        self.log.debug("Dispatching event '%s' with data %s", event, args)
        if wait:
            await asyncio.wait(tasks)

    async def log_stat(self: "Bot", stat: str) -> None:
        await self.dispatch_event("stat_event", stat, wait=False)
