from pathlib import Path
from typing import Any, ClassVar, Dict, Union

import aioaria2

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
            "--max-upload-limit=5K",
            "--max-concurrent-downloads=5",
            "--min-split-size=10M",
            "--follow-torrent=mem",
            "--split=10",
            f"--bt-tracker={trackers}",
            "--daemon=true",
            "--allow-overwrite=true",
        ]

        server = aioaria2.AsyncAria2Server(*cmd, daemon=True)

        await server.start()
        await server.wait()

        self = cls(mod)
        client = await aioaria2.Aria2WebsocketTrigger.new(
            url="http://localhost:8080/jsonrpc"
        )

        trigger_names = ["Start", "Pause", "Stop", "Complete", "Error"]
        for handler_name in trigger_names:
            client.register(self.on_trigger, f"aria2.onDownload{handler_name}")
        return client

    async def on_trigger(
        self,
        trigger: aioaria2.Aria2WebsocketTrigger,  # skipcq: PYL-W0613
        data: Union[Dict[str, str], Any]
    ):
        method = data.get("method").removeprefix("aria2.")

        update = getattr(self.mod, method)
        await update(data.get("params")[0]["gid"])


class Aria2(module.Module):
    name: ClassVar[str] = "Aria2"
    disabled: ClassVar[bool] = True

    client: Aria2WebSocket

    async def on_load(self) -> None:
        self.client = await Aria2WebSocket.init(self)

    async def on_stop(self) -> None:
        await self.client.close()

    async def get_file(self, gid: str) -> Dict[str, Any]:
        res = await self.client.tellStatus(
            gid,
            [
                "status", "totalLength", "completedLength", "downloadSpeed",
                "files", "numSeeders", "connections"
            ]
        )
        return res
