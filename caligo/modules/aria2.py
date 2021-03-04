import asyncio
import os
from typing import Any, ClassVar, Dict, Tuple, Union

import aioaria2

from .. import command, module


class Aria2(module.Module):
    name: ClassVar[str] = "Aria2"

    aria: aioaria2.Aria2WebsocketTrigger
    server: aioaria2.AsyncAria2Server

    downloads: Dict[str, Dict[str, Any]]

    async def on_load(self) -> None:
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
        self.aria = await aioaria2.Aria2WebsocketTrigger.new(
            url="http://localhost:8080/jsonrpc"
        )
        await self.update_events()

    async def on_stop(self) -> None:
        await self.aria.close()

    async def update_event(self, name: str) -> None:

        async def func(
            trigger: aioaria2.Aria2WebsocketTrigger,
            data: Union[Dict[str, str], Any]
        ):  # skipcq: PYL-W0613
            method = data.get("method").strip("aria2.")

            update = getattr(self, method)
            await update(data.get("params")[0]["gid"])

        self.aria.register(func, f"aria2.onDownload{name}")

    async def update_events(self) -> None:
        await asyncio.gather(
            self.update_event("Start"),
            self.update_event("Pause"),
            self.update_event("Stop"),
            self.update_event("Complete"),
            self.update_event("Error"),
        )

    async def changeGID(self, oldGid: str, newGid: str) -> None:
        self.log.info(f"Changing GID: {oldGid} -> {newGid}")
        self.downloads[newGid] = self.downloads.pop(oldGid)

    async def isDownloadMetaData(self, gid: str) -> Tuple[bool, str]:
        res = await self.aria.tellStatus(gid, ["followedBy"])
        if res:
            return True, res["followedBy"][0]

        return False, None

    async def onDownloadStart(self, gid: str) -> None:
        res = await self.aria.tellStatus(
            gid,
            [
                "status", "totalLength", "completedLength", "downloadSpeed",
                "files", "numSeeders", "connections"
            ]
        )
        self.downloads[gid] = res

    async def onDownloadPause(self, gid: str) -> None:
        self.log.info("Paused")

    async def onDownloadStop(self, gid: str) -> None:
        self.log.info("Stopped")

    async def onDownloadComplete(self, gid: str) -> None:
        isMetaData, newGid = await self.isDownloadMetaData(gid)

        if newGid is not None and isMetaData:
            await self.changeGID(gid, newGid)

    async def onDownloadError(self, gid: str) -> None:
        res = await self.aria.tellStatus(gid, ["errorMessage"])
        self.log.warning(res["errorMessage"])

    async def cmd_test(self, ctx: command.Context) -> None:
        gid = await self.aria.addUri([ctx.input])
        self.log.info(gid)
