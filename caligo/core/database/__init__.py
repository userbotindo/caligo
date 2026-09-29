from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.cursor import AsyncCursor
from pymongo.asynchronous.database import AsyncDatabase as _AsyncDatabase

class AsyncDatabase(_AsyncDatabase):
    """AsyncDatabase with convenience close method."""

    async def close(self) -> None:
        await self.client.close()


class AsyncClient(AsyncMongoClient):
    """Pure async AsyncMongoClient compatible with Caligo."""

    def get_database(self, *args, **kwargs) -> AsyncDatabase:
        db = super().get_database(*args, **kwargs)
        db.__class__ = AsyncDatabase
        return db

    def __getitem__(self, name: str) -> AsyncDatabase:
        db = super().__getitem__(name)
        db.__class__ = AsyncDatabase
        return db


from .storage import PersistentStorage
from .sync import sync_mongo_to_sqlite, sync_sqlite_to_mongo


__all__ = [
    "AsyncClient",
    "AsyncCollection",
    "AsyncCursor",
    "AsyncDatabase",
    "AsyncMongoClient",
    "PersistentStorage",
    "sync_mongo_to_sqlite",
    "sync_sqlite_to_mongo",
]

