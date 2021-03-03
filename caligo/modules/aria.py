from typing import ClassVar

import aioaria2

from .. import module


class Aria2(module.Module):
    name: ClassVar[str] = "Aria2"

    client: aioaria2.Aria2HttpClient
    server: aioaria2.AsyncAria2Server

    async def on_load(self) -> None:
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
            "--allow-overwrite=true"
        ]

        self.server = aioaria2.AsyncAria2Server(*cmd, daemon=True)

    async def on_start(self, time_us: int) -> None:  # skipcq: PYL-W0613
        await self.server.start()
        await self.server.wait()

    async def on_started(self) -> None:
        self.client = aioaria2.Aria2HttpClient(
            url="http://localhost:8080/jsonrpc",
            client_session=self.bot.http
        )
