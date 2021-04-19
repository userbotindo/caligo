from typing import Any, Callable, Pattern

ListenerFunc = Any
Decorator = Callable[[ListenerFunc], ListenerFunc]


def priority(_prio: int) -> Decorator:
    """Sets priority on the given listener function."""

    def prio_decorator(func: ListenerFunc) -> ListenerFunc:
        setattr(func, "_listener_priority", _prio)
        return func

    return prio_decorator


def pattern(_pattern: Pattern[str]) -> Decorator:
    """Sets regex pattern on the given listener function."""

    def pattern_decorator(func: ListenerFunc) -> ListenerFunc:
        setattr(func, "_listener_pattern", _pattern)
        return func

    return pattern_decorator


class Listener:
    event: str
    func: ListenerFunc
    module: Any
    priority: int
    p: Pattern[str]

    def __init__(self, event: str, func: ListenerFunc, mod: Any,
                 prio: int, p: Pattern[str]) -> None:
        self.event = event
        self.func = func
        self.module = mod
        self.priority = prio
        self.pattern = p

    def __lt__(self, other: "Listener") -> bool:
        return self.priority < other.priority
