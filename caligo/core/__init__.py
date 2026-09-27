from typing import TYPE_CHECKING
from .database import *  # skipcq: PY-W2000

if TYPE_CHECKING:
    from .bot import Caligo  # skipcq: PY-W2000


def __getattr__(name: str):
    if name == "Caligo":
        from .bot import Caligo

        return Caligo
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

