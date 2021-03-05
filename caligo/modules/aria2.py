import asyncio
import os
from typing import Any, ClassVar, Dict, Tuple, Union

import aioaria2

from .. import command, module


class Aria2(module.Module):
    name: ClassVar[str] = "Aria2"

    aria: aioaria2.Aria2WebsocketTrigger
    server: aioaria2.AsyncAria2Server

    cache: Dict[str, str]
    downloads: Dict[str, Dict[str, Any]]

    async def on_load(self) -> None:
        self.cache = {}
        self.downloads = {}

        downloadPath = os.environ.get("HOME") + "/downloads"
        if not os.path.exists(downloadPath):
            os.makedirs(downloadPath)

        link = "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best.txt"
        async with self.bot.http.get(link) as resp:
            trackers_list: str = await resp.text()
            trackers: str = "[" + trackers_list.replace('\n\n', ',') + "]"

        cmd = [
            "aria2c",
            f"--dir={downloadPath}",
            "--enable-rpc",
            "--rpc-listen-all=false",
            "--rpc-listen-port=8080",
            "--max-connection-per-server=10",
            "--rpc-max-request-size=1024M",
            "--seed-ratio=1",
            "--seed-time=60",
            "--max-upload-limit=5K",
            "--max-concurrent-downloads=5",
            "--min-split-size=10M",
            "--follow-torrent=mem",
            "--split=10",
            f"--bt-tracker={trackers}",
            "--daemon=true",
            "--allow-overwrite=true",
        ]

        self.server = aioaria2.AsyncAria2Server(*cmd, daemon=True)

    async def on_start(self, time_us: int) -> None:  # skipcq: PYL-W0613
        await self.server.start()
        await self.server.wait()

    async def on_started(self) -> None:
        self.client = await aioaria2.Aria2WebsocketTrigger.new(
            url="http://localhost:8080/jsonrpc"
        )
        self.update_events()

    async def on_stop(self) -> None:
        await self.client.close()

    def update_event(self, name: str) -> None:

        async def func(
            trigger: aioaria2.Aria2WebsocketTrigger,  # skipcq: PYL-W0613
            data: Union[Dict[str, str], Any]
        ):
            method = data.get("method").strip("aria2.")

            update = getattr(self, method)
            await update(data.get("params")[0]["gid"])

        self.client.register(func, f"aria2.onDownload{name}")

    def update_events(self) -> None:
        # skipcq: PYL-W0106
        self.update_event("Start"),
        self.update_event("Pause"),
        self.update_event("Stop"),
        self.update_event("Complete"),
        self.update_event("Error"),

    async def get_file(self, gid: str) -> Dict[str, Any]:
        res = await self.client.tellStatus(
            gid,
            [
                "status", "totalLength", "completedLength", "downloadSpeed",
                "files", "numSeeders", "connections"
            ]
        )
        return res

    async def isDownloadMetaData(self, gid: str) -> Tuple[bool, str]:
        res = await self.client.tellStatus(gid, ["followedBy"])
        if res:
            return True, res["followedBy"][0]

        return False, None

    async def onDownloadStart(self, gid: str) -> None:
        self.log.info(f"Starting download: gid['{gid}']")

        res = await self.get_file(gid)
        self.downloads[gid] = res

    async def onDownloadPause(self, gid: str) -> None:
        self.log.info(f"GID: {gid} paused")

    async def onDownloadStop(self, gid: str) -> None:
        self.log.info(f"GID: {gid} stopped")

    async def onDownloadComplete(self, gid: str) -> None:
        isMetaData, newGid = await self.isDownloadMetaData(gid)

        if newGid is not None:
            self.downloads.pop(gid)
            self.cache.update({gid: [newGid, {"isMetaData": isMetaData}]})

            res = await self.get_file(newGid)
            self.downloads[newGid] = res
            return

        self.cache.update({gid: [None, {"isMetaData": isMetaData}]})
        self.log.info(f"GID: {gid} download completed")

    async def onDownloadError(self, gid: str) -> None:
        res = await self.client.tellStatus(gid, ["errorMessage"])
        self.log.warning(res["errorMessage"])

    async def cmd_test(self, ctx: command.Context) -> None:
        gid = await self.client.addUri([ctx.input])

        waiting = True
        while waiting:
            if self.cache.get(gid):
                waiting = False

            await asyncio.sleep(1)

        newGid = self.cache.get(gid)
        if newGid is not None:
            self.log.info(f"new GID: {gid}")
            # update progress
            return  # when metadata download is complete

        # handle if file is not metadata
        # update progress
        return  # when download is complete
