import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Union

import aioaria2
import pyrogram
from async_property import async_property

from .. import module


class BitTorrent:

    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data or {}

    def __str__(self):
        return self.info["name"]

    @property
    def announce_list(self) -> Optional[List[List[str]]]:
        return self._data.get("announceList")

    @property
    def comment(self) -> Optional[str]:
        return self._data.get("comment")

    @property
    def creation_date(self) -> datetime:
        return datetime.fromtimestamp(self._data["creationDate"])

    @property
    def mode(self) -> Optional[str]:
        return self._data.get("mode")

    @property
    def info(self) -> Optional[dict]:
        return self._data.get("info")


class File:

    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data or {}

    def __str__(self):
        return str(self.path)

    def __eq__(self, other):
        return self.path == other.path

    @property
    def index(self) -> int:
        return int(self._data["index"])

    @property
    def path(self) -> Path:
        return Path(self._data["path"])

    @property
    def metadata(self) -> bool:
        return str(self.path).startswith("[METADATA]")

    @property
    def length(self) -> int:
        return int(self._data["length"])

    @property
    def completed_length(self) -> int:
        return int(self._data["completedLength"])

    @property
    def uris(self) -> Optional[List[str]]:
        return self._data.get("uris")


class Download:

    def __init__(self, api: "Aria2", data: Dict[str, Any]) -> None:
        self.api = api
        self._data = data or {}

        self._name = ""
        self._files: List[File] = []
        self._bittorrent = None

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self.gid == other.gid

    @async_property
    async def update(self) -> "Download":
        self._data = await self.api.client.tellStatus(self.gid)

        self._name = ""
        self._files = []
        self._bittorrent = None

        return self

    @property
    def name(self) -> str:
        if not self._name:
            if self.bittorrent and self.bittorrent.info:
                self._name = self.bittorrent.info["name"]
            elif self.files[0].metadata:
                self._name = str(self.files[0].path)
            else:
                file_path = str(self.files[0].path.absolute())
                dir_path = str(self.dir.absolute())
                if file_path.startswith(dir_path):
                    start_pos = len(dir_path) + 1
                    self._name = Path(file_path[start_pos:]).parts[0]
                else:
                    try:
                        self._name = self.files[0].uris[0]["uri"].split("/")[-1]
                    except IndexError:
                        pass
        return self._name

    @property
    def gid(self) -> str:
        return self._data["gid"]

    @property
    def status(self) -> str:
        return self._data["status"]

    @property
    def active(self) -> bool:
        return self.status == "active"

    @property
    def waiting(self) -> bool:
        return self.status == "waiting"

    @property
    def paused(self) -> bool:
        return self.status == "paused"

    @property
    def failed(self) -> bool:
        return self.status == "error"

    @property
    def complete(self) -> bool:
        return self.status == "complete"

    @property
    def total_length(self) -> int:
        return int(self._data["totalLength"])

    @property
    def completed_length(self) -> int:
        return int(self._data["completedLength"])

    @property
    def download_speed(self) -> int:
        return int(self._data["downloadSpeed"])

    @property
    def info_hash(self) -> Optional[str]:
        return self._data.get.get("infoHash")

    @property
    def num_seeders(self) -> int:
        return int(self._data.get["numSeeders"])

    @property
    def seeder(self) -> bool:
        res = self._data.get("seeder")
        return res if res is not None else False

    @property
    def connections(self) -> int:
        return int(self._data["connections"])

    @property
    def error_code(self) -> Optional[str]:
        return self._data.get("errorCode")

    @property
    def error_message(self) -> Optional[str]:
        return self._data.get("errorMessage")

    @property
    def dir(self) -> Path:
        return Path(self._data["dir"])

    @property
    def files(self) -> List[File]:
        if not self._files:
            self._files = [File(data) for data in self._data.get("files", [])]

        return self._files

    @property
    def bittorrent(self) -> Optional[BitTorrent]:
        if not self._bittorrent and "bittorrent" in self._data:
            self._bittorrent = BitTorrent(self._data.get("bittorrent"))
        return self._bittorrent

    @property
    def metadata(self) -> bool:
        return bool(self.followed_by)

    @property
    def followed_by(self) -> List[str]:
        return self._data.get("followedBy", [])

    @property
    def progress(self) -> float:
        try:
            return self.completed_length / self.total_length * 100
        except ZeroDivisionError:
            return 0.0

    @property
    def eta(self) -> Union[int, str]:
        try:
            return round(
                (self.total_length - self.completed_length) /
                self.download_speed
            )
        except ZeroDivisionError:
            return "N/A"

    @async_property
    async def remove(self, force: bool = False) -> bool:
        if force is True:
            func = self.api.client.forceRemove
        else:
            func = self.api.client.remove

        res = await func(self.gid)
        if isinstance(res, str):
            return True

        return False

    @async_property
    async def pause(self, force: bool = False) -> bool:
        if force is True:
            func = self.api.client.forcePause
        else:
            func = self.api.client.pause

        res = await func(self.gid)
        if isinstance(res, str):
            return True

        return False

    @async_property
    async def resume(self) -> bool:
        res = await self.api.client.unpause(self.gid)
        if isinstance(res, str):
            return True

        return False


class Aria2WebSocket:

    server: aioaria2.AsyncAria2Server
    client: aioaria2.Aria2WebsocketTrigger

    def __init__(self, api: "Aria2") -> None:
        self.api = api

    @classmethod
    async def init(cls, api: "Aria2") -> "Aria2WebSocket":
        path = Path.home() / "downloads"
        path.mkdir(parents=True, exist_ok=True)

        link = "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best.txt"
        async with api.bot.http.get(link) as resp:
            trackers_list: str = await resp.text()
            trackers: str = "[" + trackers_list.replace('\n\n', ',') + "]"

        cmd = [
            "aria2c",
            f"--dir={str(path)}",
            "--enable-rpc",
            "--rpc-listen-all=false",
            "--rpc-listen-port=8080",
            "--max-connection-per-server=10",
            "--rpc-max-request-size=1024M",
            "--seed-ratio=1",
            "--seed-time=60",
            "--max-upload-limit=1024K",
            "--max-concurrent-downloads=5",
            "--min-split-size=10M",
            "--follow-torrent=mem",
            "--split=10",
            f"--bt-tracker={trackers}",
            "--daemon=true",
            "--allow-overwrite=true",
        ]
        protocol = "http://localhost:8080/jsonrpc"

        cpath = Path.home() / ".cache" / "caligo" / ".certs"
        if (Path(cpath / "cert.pem").is_file() and
                Path(cpath / "key.pem").is_file()):
            cmd.insert(3, "--rpc-secure=true")
            cmd.insert(3, f"--rpc-private-key={str(cpath / 'key.pem')}")
            cmd.insert(3, f"--rpc-certificate={str(cpath / 'cert.pem')}")
            protocol = "https://localhost:8080/jsonrpc"

        server = aioaria2.AsyncAria2Server(*cmd, daemon=True)

        await server.start()
        await server.wait()

        self = cls(api)
        client = await aioaria2.Aria2WebsocketTrigger.new(url=protocol)

        trigger_names = ["Start", "Complete", "Error"]
        for handler_name in trigger_names:
            client.register(self.on_trigger, f"aria2.onDownload{handler_name}")
        return client

    async def on_trigger(
        self,
        trigger: aioaria2.Aria2WebsocketTrigger,
        data: Union[Dict[str, str], Any]
    ):
        method = data.get("method").removeprefix("aria2.")
        gid = data["params"][0]["gid"]

        if method == "onDownloadComplete":
            self.api.downloads[gid] = await self.api.downloads[gid].update
            file = self.api.downloads[gid]
            queue = self.api.data[gid]

            if file.metadata is True:
                newGid = file.followed_by[0]
                self.api.downloads[newGid] = await self.api.getDownload(newGid)
                queue.put_nowait(newGid)

        update = getattr(self.api, method)
        await update(gid)


class Aria2(module.Module):
    name: ClassVar[str] = "Aria2"

    client: Aria2WebSocket
    data: Dict[str, asyncio.Queue]
    downloads: Dict[str, str]

    async def on_load(self) -> None:
        self.bot.unload_module(self)

        self.data = {}
        self.downloads = {}
        self.client = await Aria2WebSocket.init(self)

    async def on_stop(self) -> None:
        await self.client.close()

    async def onDownloadStart(self, gid: str) -> None:
        self.log.info(f"Starting download: [gid: '{gid}']")

    async def onDownloadComplete(self, gid: str):
        meta = ""
        file = self.downloads[gid]
        if file.metadata is True:
            meta += " - Metadata"

        self.log.info(f"Complete download: [gid: '{gid}']{meta}")

    async def onDownloadError(self, gid: str) -> None:
        file = await self.downloads[gid].update
        self.log.warning(file.error_message)

    async def addDownload(self, uri: str, msg: pyrogram.types.Message) -> str:
        gid = await self.client.addUri([uri])
        self.downloads[gid] = await self.getDownload(gid)
        self.bot.loop.create_task(self.checkProgress(gid))

        self.data[gid] = asyncio.Queue(1)

        try:
            fut = await asyncio.wait_for(self.data[gid].get(), 10)
        except asyncio.TimeoutError:
            fut = None
        finally:
            del self.data[gid]

        if fut is not None:
            return fut

        return gid

    async def pauseDownload(self, gid: str) -> str:
        return await self.client.pause(gid)

    async def removeDownload(self, gid: str) -> str:
        return await self.client.remove(gid)

    async def getDownload(self, gid: str) -> Download:
        res = await self.client.tellStatus(gid)
        return Download(self, res)

    async def checkProgress(self, gid: str) -> Union[str, pyrogram.types.Message]:
        complete = False
        while not complete:
            file = await self.downloads[gid].update
            complete = file.complete
            try:
                if not complete and not file.error_message:
                    percentage = file.progress
                    downloaded = file.total_length
                    speed = file.download_speed
                    eta = file.eta
                    text = f"{percentage}%: {downloaded} -> {speed} - {eta}"

                    self.log.info(text)
                await asyncio.sleep(2)
                file = await self.downloads[gid].update
                complete = file.complete
                if complete:
                    del self.downloads[gid]
                    self.log.info("Completed")
                else:
                    continue
            except Exception as e:
                self.log.info("ERROR: ", e)
                return

    async def cmd_test(self, ctx):
        gid = await self.addDownload(ctx.input, ctx.msg)

        if gid:
            file = self.downloads[gid]
            self.log.info(dir(file))
            await file.pause
            await file.remove
        return
