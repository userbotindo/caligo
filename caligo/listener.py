from typing import Any, Callable, Optional

from pyrogram.filters import Filter

ListenerFunc = Any
Decorator = Callable[[ListenerFunc], ListenerFunc]


def priority(_prio: int) -> Decorator:
    """Sets priority on the given listener function."""

    def prio_decorator(func: ListenerFunc) -> ListenerFunc:
        setattr(func, "_listener_priority", _prio)
        return func

    return prio_decorator


def filters(_filters: Filter) -> Decorator:
    """Sets filters on the given listener function."""

    def filters_decorator(func: ListenerFunc) -> ListenerFunc:
        setattr(func, "_listener_filters", _filters)
        return func

    return filters_decorator


class Listener:
    event: str
    func: ListenerFunc
    module: Any
    priority: int
    filters: Optional[Filter]

    def __init__(
        self,
        event: str,
        func: ListenerFunc,
        mod: Any,
        prio: int,
        listener_filter: Optional[Filter],
    ) -> None:
        self.event = event
        self.func = func
        self.module = mod
        self.priority = prio
        self.filters = listener_filter

    def __lt__(self, other: "Listener") -> bool:
        return self.priority < other.priority

    def __repr__(self) -> str:
        return f"<listener module '{self.event}' from '{self.module.name}'>"
