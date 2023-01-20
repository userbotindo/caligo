from typing import TYPE_CHECKING, Any

from .base import CaligoBase
from .database import AsyncClient, AsyncDatabase

if TYPE_CHECKING:
    from .bot import Caligo


class DatabaseProvider(CaligoBase):
    db: AsyncDatabase

    def __init__(self: "Caligo", **kwargs: Any) -> None:
        client = AsyncClient(self.config["bot"]["db_uri"], connect=False)
        self.db = client.get_database("CALIGO")

        # Propagate initialization to other mixins
        super().__init__(**kwargs)
