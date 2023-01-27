import asyncio
import bisect
from typing import TYPE_CHECKING, Any, MutableMapping, MutableSequence, Optional

from pyrogram.filters import Filter
from pyrogram.types import CallbackQuery, InlineQuery, Message

from caligo import module, util
from caligo.listener import Listener, ListenerFunc

from .base import CaligoBase

if TYPE_CHECKING:
    from .bot import Caligo


class EventDispatcher(CaligoBase):
    listeners: MutableMapping[str, MutableSequence[Listener]]

    def __init__(self: "Caligo", **kwargs: Any) -> None:
        self.listeners = {}

        super().__init__(**kwargs)

    def register_listener(
        self: "Caligo",
        mod: module.Module,
        event: str,
        func: ListenerFunc,
        *,
        priority: int = 100,
        regex: Optional[Filter] = None,
    ) -> None:
        listener = Listener(event, func, mod, priority, regex)

        if event in self.listeners:
            bisect.insort(self.listeners[event], listener)
        else:
            self.listeners[event] = [listener]

        self.update_module_events()

    def unregister_listener(self: "Caligo", listener: Listener) -> None:
        self.listeners[listener.event].remove(listener)
        if not self.listeners[listener.event]:
            del self.listeners[listener.event]

        self.update_module_events()

    def register_listeners(self: "Caligo", mod: module.Module) -> None:
        for event, func in util.misc.find_prefixed_funcs(mod, "on_"):
            done = True
            try:
                self.register_listener(
                    mod,
                    event,
                    func,
                    priority=getattr(func, "_listener_priority", 100),
                    regex=getattr(func, "_listener_regex", None),
                )
                done = True
            finally:
                if not done:
                    self.unregister_listeners(mod)

    def unregister_listeners(self: "Caligo", mod: module.Module) -> None:
        to_unreg = []

        for lst in self.listeners.values():
            for listener in lst:
                if listener.module == mod:
                    to_unreg.append(listener)

        for listener in to_unreg:
            self.unregister_listener(listener)

    async def dispatch_event(
        self: "Caligo", event: str, *args: Any, wait: bool = True, **kwargs: Any
    ) -> None:
        tasks = set()

        try:
            listeners = self.listeners[event]
        except KeyError:
            return None

        if not listeners:
            return

        matches = None
        index = None
        for lst in listeners:
            if lst.regex is not None:
                for idx, arg in enumerate(args):
                    if isinstance(arg, (CallbackQuery, InlineQuery, Message)):
                        match = await lst.regex(self.client, arg)
                        if not match:
                            continue

                        # Matches obj will dissapered after loop end
                        # So save the index and matches object
                        matches = arg.matches
                        index = idx
                        break

                    self.log.error("'%s' can't be used with pattern", event)
                else:
                    continue

            task = self.loop.create_task(lst.func(*args, **kwargs))
            tasks.add(task)

        if not tasks:
            return

        if matches and index:
            args[index].matches = matches
        self.log.debug("Dispatching event '%s' with data %s", event, args)
        if wait:
            await asyncio.wait(tasks)

    async def log_stat(self: "Caligo", stat: str) -> None:
        await self.dispatch_event("stat_event", stat, wait=False)
