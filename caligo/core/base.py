from typing import TYPE_CHECKING, Any

CaligoBase: Any
if TYPE_CHECKING:
    from .bot import Caligo

    CaligoBase = Caligo
else:
    import abc

    CaligoBase = abc.ABC
