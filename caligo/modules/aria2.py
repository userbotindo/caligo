import asyncio
import os
from typing import ClassVar, Dict, Union

import aioaria2

from .. import command, module


class Aria2(module.Module):
    name: ClassVar[str] = "Aria2"

    aria: aioaria2.Aria2WebsocketTrigger
    server: aioaria2.AsyncAria2Server

    downloads: Dict[str, Union[str, int]]

    async def on_load(self) -> None:
        self.downloads = {}
        self.event_handler = {}

        DownloadPath = os.environ.get("HOME") + "/Downloads"
        if not os.path.exists(DownloadPath):
            os.makedirs(DownloadPath)

        link = "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best.txt"
        async with self.bot.http.get(link) as resp:
            trackers_list: str = await resp.text()
            trackers: str = "[" + trackers_list.replace('\n\n', ',') + "]"

        cmd = [
            "aria2c",
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
            f"--dir={DownloadPath}"
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
            data: Dict[str, str]
        ):
            method = data.get("method").strip("aria2.")

            update = getattr(self, method)
            await update(data)

        self.aria.register(func, f"aria2.onDownload{name}")

    async def update_events(self) -> None:
        await asyncio.gather(
            self.update_event("Start"),
            self.update_event("Pause"),
            self.update_event("Stop"),
            self.update_event("Complete"),
            self.update_event("Error"),
        )

    async def onDownloadStart(self, data) -> None:
        self.log.info(data)

    async def onDownloadPause(self, data) -> None:
        self.log.info(data)

    async def onDownloadStop(self, data) -> None:
        self.log.info(data)

    async def onDownloadComplete(self, data) -> None:
        self.log.info(data)

    async def onDownloadError(self, data) -> None:
        self.log.info(data)

    async def cmd_test(self, ctx: command.Context) -> None:
        await self.aria.addUri([ctx.input])
