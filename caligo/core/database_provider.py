from typing import TYPE_CHECKING, Any

from .base import Base
from .database import AsyncClient, AsyncDatabase

if TYPE_CHECKING:
    from .bot import Bot


class DatabaseProvider(Base):
    db: AsyncDatabase

    def __init__(self: "Bot", **kwargs: Any) -> None:
        client = AsyncClient(self.config["db_uri"], connect=False)
        self.db = client.get_database("AnjaniBot")

        # Propagate initialization to other mixins
        super().__init__(**kwargs)
