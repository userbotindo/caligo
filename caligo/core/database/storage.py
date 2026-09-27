# Taken from https://github.com/animeshxd/pyromongo

import asyncio
import inspect
import time
from typing import Any, Iterable, List, Optional, Tuple, Union

from pymongo import UpdateOne
from pyrogram.raw.types.input_peer_channel import InputPeerChannel
from pyrogram.raw.types.input_peer_chat import InputPeerChat
from pyrogram.raw.types.input_peer_user import InputPeerUser
from pyrogram.storage.sqlite_storage import get_input_peer
from pyrogram.storage.storage import Storage, UpdateState

from pymongo.asynchronous.database import AsyncDatabase


class PersistentStorage(Storage):
    """
    database: caligo AsyncDatabase
        required database object of AsyncDatabase
    remove_peers: bool = False
        remove peers collection on logout (by default, it will not remove peers)
    """

    db: AsyncDatabase
    lock: asyncio.Lock
    USERNAME_TTL = 8 * 60 * 60

    def __init__(self, database: AsyncDatabase, remove_peers: bool = False) -> None:
        # Propagate initialization
        super().__init__()

        self.db = database
        self.lock = asyncio.Lock()

        self._peer = database["PEERS"]
        self._usernames = database["USERNAMES"]
        self._update_state = database["UPDATE_STATE"]
        self._remove_peers = remove_peers
        self._session = database["SESSION"]

    async def open(self) -> None:
        """
        dc_id          INTEGER PRIMARY KEY,
        server_address TEXT,
        port           INTEGER,
        api_id         INTEGER,
        test_mode      INTEGER,
        auth_key       BLOB,
        date           INTEGER NOT NULL,
        user_id        INTEGER,
        is_bot         INTEGER
        """

        if await self._session.find_one({"_id": 0}, {}):
            return

        await self._session.insert_one(
            {
                "_id": 0,
                "dc_id": 2,
                "server_address": None,
                "port": None,
                "api_id": None,
                "test_mode": None,
                "auth_key": b"",
                "date": 0,
                "user_id": 0,
                "is_bot": 0,
            }
        )

    async def save(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def delete(self) -> None:
        try:
            await self._session.delete_one({"_id": 0})
            if self._remove_peers:
                await self._peer.delete_many({})
                await self._usernames.delete_many({})
                await self._update_state.delete_many({})
        except Exception:  # skipcq: PYL-W0703
            return

    async def update_usernames(
        self, usernames: Iterable[Tuple[int, List[Optional[str]]]]
    ) -> None:
        usernames_list = list(usernames)
        if not usernames_list:
            return

        ids = [id_ for id_, _ in usernames_list]
        await self._usernames.delete_many({"peer_id": {"$in": ids}})

        bulk = []
        for id_, names in usernames_list:
            for username in names:
                if username is not None:
                    bulk.append(
                        UpdateOne(
                            {"_id": username.lower()},
                            {"$set": {"peer_id": id_, "username": username}},
                            upsert=True,
                        )
                    )
        if bulk:
            await self._usernames.bulk_write(bulk)

    async def update_peers(self, peers: Iterable[Any]) -> None:
        """(id, access_hash, type, phone_number) in Kurigram, or (id, access_hash, type, username, phone_number) in legacy"""
        s = int(time.time())
        bulk = []
        for i in peers:
            doc: dict = {
                "access_hash": i[1],
                "type": i[2],
                "last_update_on": s,
            }
            if len(i) == 4:
                doc["phone_number"] = i[3]
            elif len(i) >= 5:
                doc["username"] = i[3]
                doc["phone_number"] = i[4]

            bulk.append(
                UpdateOne(
                    {"_id": i[0]},
                    {"$set": doc},
                    upsert=True,
                )
            )

        if not bulk:
            return

        await self._peer.bulk_write(bulk)

    async def get_peer_by_id(
        self, peer_id: int
    ) -> Union[InputPeerUser, InputPeerChat, InputPeerChannel]:
        # id, access_hash, type
        res = await self._peer.find_one(
            {"_id": peer_id}, {"_id": 1, "access_hash": 1, "type": 1}
        )
        if not res:
            raise KeyError(f"ID not found: {peer_id}")

        return get_input_peer(res["_id"], res["access_hash"], res["type"])

    async def get_peer_by_username(
        self, username: str
    ) -> Union[InputPeerUser, InputPeerChat, InputPeerChannel]:
        # id, access_hash, type, last_update_on,
        res = await self._peer.find_one(
            {"username": username},
            {"_id": 1, "access_hash": 1, "type": 1, "last_update_on": 1},
        )

        if not res:
            u_doc = await self._usernames.find_one({"_id": username.lower()})
            if u_doc:
                res = await self._peer.find_one(
                    {"_id": u_doc["peer_id"]},
                    {"_id": 1, "access_hash": 1, "type": 1, "last_update_on": 1},
                )

        if not res:
            raise KeyError(f"Username not found: {username}")

        if abs(time.time() - res.get("last_update_on", 0)) > self.USERNAME_TTL:
            raise KeyError(f"Username expired: {username}")

        return get_input_peer(res["_id"], res["access_hash"], res["type"])

    async def get_peer_by_phone_number(
        self, phone_number: str
    ) -> Union[InputPeerUser, InputPeerChat, InputPeerChannel]:
        #  _id, access_hash, type,
        res = await self._peer.find_one(
            {"phone_number": phone_number}, {"_id": 1, "access_hash": 1, "type": 1}
        )

        if not res:
            raise KeyError(f"Phone number not found: {phone_number}")

        return get_input_peer(res["_id"], res["access_hash"], res["type"])

    async def _get(self) -> Optional[Any]:
        attr = inspect.stack()[2].function
        data = await self._session.find_one({"_id": 0}, {attr: 1})
        if not data:
            return

        return data[attr]

    async def _set(self, value: Any) -> None:
        attr = inspect.stack()[2].function
        await self._session.update_one({"_id": 0}, {"$set": {attr: value}}, upsert=True)

    async def _accessor(self, value: Any = object) -> Any:
        return await self._get() if value == object else await self._set(value)

    async def dc_id(self, value=object) -> Optional[int]:
        return await self._accessor(value)

    async def api_id(self, value=object) -> Optional[int]:
        return await self._accessor(value)

    async def test_mode(self, value=object) -> Optional[bool]:
        return await self._accessor(value)

    async def auth_key(self, value=object) -> Optional[bytes]:
        return await self._accessor(value)

    async def date(self, value=object) -> Optional[int]:
        return await self._accessor(value)

    async def user_id(self, value=object) -> Optional[int]:
        return await self._accessor(value)

    async def is_bot(self, value=object) -> Optional[bool]:
        return await self._accessor(value)

    async def server_address(self, value=object) -> Optional[str]:
        return await self._accessor(value)

    async def port(self, value=object) -> Optional[int]:
        return await self._accessor(value)

    async def get_update_states(
        self, ids: Union[int, Iterable[int], None] = None
    ) -> List[UpdateState]:
        if ids is None:
            cursor = self._update_state.find().sort("date", 1)
        elif isinstance(ids, int):
            cursor = self._update_state.find({"_id": ids}).sort("date", 1)
        else:
            state_ids = list(ids)
            if not state_ids:
                return []
            cursor = self._update_state.find({"_id": {"$in": state_ids}}).sort("date", 1)

        states: List[UpdateState] = []
        async for doc in cursor:
            states.append(
                UpdateState(
                    id=doc["_id"],
                    pts=doc.get("pts"),
                    qts=doc.get("qts"),
                    date=doc.get("date"),
                    seq=doc.get("seq"),
                )
            )
        return states

    async def set_update_state(
        self, update_state: Union[UpdateState, Iterable[UpdateState]]
    ) -> None:
        states = (
            [update_state]
            if isinstance(update_state, UpdateState)
            else list(update_state)
        )
        if not states:
            return

        bulk = []
        for state in states:
            update_fields: dict = {}
            if state.pts is not None:
                update_fields["pts"] = state.pts
            if state.qts is not None:
                update_fields["qts"] = state.qts
            if state.date is not None:
                update_fields["date"] = state.date
            if state.seq is not None:
                update_fields["seq"] = state.seq

            if update_fields:
                bulk.append(
                    UpdateOne(
                        {"_id": state.id},
                        {"$set": update_fields},
                        upsert=True,
                    )
                )

        if bulk:
            await self._update_state.bulk_write(bulk)

    async def delete_update_state(
        self, state_id: Union[int, Iterable[int]]
    ) -> None:
        if isinstance(state_id, int):
            await self._update_state.delete_one({"_id": state_id})
        else:
            state_ids = list(state_id)
            if state_ids:
                await self._update_state.delete_many({"_id": {"$in": state_ids}})
