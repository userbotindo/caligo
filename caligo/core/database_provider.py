from typing import TYPE_CHECKING, Any

from .base import Base
from .. import util

if TYPE_CHECKING:
    from .bot import Bot


class DatabaseProvider(Base):
    db: util.db.AsyncDB

    def __init__(self: "Bot", **kwargs: Any):
        client = util.db.AsyncClient(self.getConfig["db_uri"], connect=False)
        self.db = client.get_database("caligo")

        super().__init__(**kwargs)
