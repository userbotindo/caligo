from typing import TYPE_CHECKING, Any

from motor.core import AgnosticCollection
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .base import Base

if TYPE_CHECKING:
    from .bot import Bot


class DataBase(Base):
    _db: AsyncIOMotorClient
    db: AsyncIOMotorDatabase

    def __init__(self: "Bot", **kwargs: Any):
        self._init_db()

        self.db = self._db.get_database("caligo")

        super().__init__(**kwargs)

    def _init_db(self) -> None:
        self._db = AsyncIOMotorClient(self.getConfig.db_uri, connect=False)

    def disconnect_db(self) -> None:
        self._db.close()

    def get_db(self: "Bot", name: str) -> AgnosticCollection:
        return self.db.get_collection(name)
