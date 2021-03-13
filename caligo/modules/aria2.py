import asyncio
from pathlib import Path
from typing import Any, ClassVar, Dict, Union

import aioaria2
from bprint import bprint

from .. import module


class Aria2WebSocket:

    server: aioaria2.AsyncAria2Server
    client: aioaria2.Aria2WebsocketTrigger

    def __init__(self, mod: "Aria2"):
        self.mod = mod

    @classmethod
    async def init(cls, mod: "Aria2"):
        path = Path.home() / "downloads"
        path.mkdir(parents=True, exist_ok=True)

        link = "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best.txt"
        async with mod.bot.http.get(link) as resp:
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
            mod.log.debug("Using TLS/SSL protocol")
            cmd.insert(3, "--rpc-secure=true")
            cmd.insert(3, f"--rpc-private-key={str(cpath / 'key.pem')}")
            cmd.insert(3, f"--rpc-certificate={str(cpath / 'cert.pem')}")
            protocol = "https://localhost:8080/jsonrpc"

        server = aioaria2.AsyncAria2Server(*cmd, daemon=True)

        await server.start()
        await server.wait()

        self = cls(mod)
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
            cache = await trigger.tellStatus(gid, ["followedBy"])
            res = self.mod.data[gid]
            if cache:
                res.put_nowait((cache["followedBy"][0], True))

        update = getattr(self.mod, method)
        await update(gid)


class Aria2(module.Module):
    name: ClassVar[str] = "Aria2"

    client: Aria2WebSocket
    data: Dict[str, asyncio.Queue]
    downloads: Dict[str, str]

    async def on_load(self) -> None:
        self.data = {}
        self.downloads = {}
        self.client = await Aria2WebSocket.init(self)

        version = bprint(await self.client.getVersion(), stream=str)
        self.log.debug(version.replace("dict", "").replace("list", "").rstrip())

    async def on_stop(self) -> None:
        await self.client.close()

    async def onDownloadStart(self, gid: str) -> None:
        self.log.info(f"Starting download: [gid: '{gid}']")

    async def onDownloadComplete(self, gid: str):
        meta = ""
        metadata = await self.client.tellStatus(gid, ["followedBy"])
        if bool(metadata) is True:
            meta += " - Metadata"

        self.log.info(f"Complete download: [gid: '{gid}']{meta}")

    async def onDownloadError(self, gid: str) -> None:
        res = await self.client.tellStatus(gid, ["errorMessage"])
        self.log.warning(res["errorMessage"])

    async def addDownload(self, uri: str) -> str:
        gid = await self.client.addUri([uri])

        self.data[gid] = asyncio.Queue(1)

        try:
            fut, metadata = await asyncio.wait_for(self.data[gid].get(), 10)
        except asyncio.TimeoutError:
            fut, metadata = (None, False)

        if fut is not None and metadata is True:
            return fut

        return gid

    async def pauseDownload(self, gid: str) -> str:
        return await self.client.pause(gid)

    async def removeDownload(self, gid: str) -> str:
        return await self.client.remove(gid)

    async def getDownload(self, gid: str) -> Dict[str, Any]:
        res = await self.client.tellStatus(
            gid,
            [
                "status", "totalLength", "completedLength", "downloadSpeed",
                "files", "numSeeders", "connections"
            ]
        )
        return res
