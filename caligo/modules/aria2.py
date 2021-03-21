import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Tuple, Union
from urllib import parse

import aioaria2
import pyrogram
from googleapiclient.http import MediaFileUpload
from pyrogram.errors import MessageEmpty, MessageNotModified

from .. import module, util


class Aria2WebSocket:

    server: aioaria2.AsyncAria2Server
    client: aioaria2.Aria2WebsocketTrigger

    def __init__(self, api: "Aria2") -> None:
        self.api = api
        self.log = self.api.log
        self.drive = self.api.bot.modules.get("GoogleDrive")

        self._start = False
        self._bot = self.api.bot

        self.complete: List[str] = []
        self.downloads: Dict[str, util.aria2.Download] = {}
        self.uploads: Dict[str, List[Any]] = {}

    @classmethod
    async def init(cls, api: "Aria2") -> "Aria2WebSocket":
        path = Path.home() / "downloads"
        path.mkdir(parents=True, exist_ok=True)

        link = "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best.txt"
        async with api.bot.http.get(link) as resp:
            trackers_list: str = await resp.text()
            trackers: str = "[" + trackers_list.replace("\n\n", ",") + "]"

        cmd = [
            "aria2c", f"--dir={str(path)}", "--enable-rpc",
            "--rpc-listen-all=false", "--rpc-listen-port=8080",
            "--max-connection-per-server=10", "--rpc-max-request-size=1024M",
            "--seed-time=0.01", "--seed-ratio=0.1", "--max-upload-limit=5K",
            "--max-concurrent-downloads=5", "--min-split-size=10M",
            "--follow-torrent=mem", "--split=10", f"--bt-tracker={trackers}",
            "--daemon=true", "--allow-overwrite=true"
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

        trigger = [(self.on_download_start, "onDownloadStart"),
                   (self.on_download_complete, "onDownloadComplete"),
                   (self.on_download_error, "onDownloadError")]
        for handler, name in trigger:
            client.register(handler, f"aria2.{name}")
        return client

    async def get_download(self, client: aioaria2.Aria2WebsocketTrigger,
                           gid: str) -> util.aria2.Download:
        res = await client.tellStatus(gid)
        return await util.run_sync(util.aria2.Download, client, res)

    async def on_download_start(self, trigger: aioaria2.Aria2WebsocketTrigger,
                                data: Union[Dict[str, str], Any]) -> None:
        gid = data["params"][0]["gid"]
        async with self.api.lock:
            self.downloads[gid] = await self.get_download(trigger, gid)
        self.log.info(f"Starting download: [gid: '{gid}']")

        # Only create task once, because we running on forever loop
        if self._start is False:
            self._start = True
            self._bot.loop.create_task(await self._updateProgress())

    async def on_download_complete(self,
                                   trigger: aioaria2.Aria2WebsocketTrigger,
                                   data: Union[Dict[str, str], Any]) -> None:
        gid = data["params"][0]["gid"]
        self.downloads[gid] = await self.get_download(trigger, gid)
        file = self.downloads[gid]

        meta = ""
        async with self.api.lock:
            if file.metadata is True:
                meta += " - Metadata"
                del self.downloads[file.gid]
            else:
                _file = await self.drive.uploadFile(self, file.gid)
                self.uploads[file.gid] = [_file, file.name, file.gid, util.time.sec()]

        self.log.info(f"Complete download: [gid: '{gid}']{meta}")

    async def on_download_error(self, trigger: aioaria2.Aria2WebsocketTrigger,
                                data: Union[Dict[str, str], Any]) -> None:
        gid = data["params"][0]["gid"]

        file = await self.get_download(trigger, gid)
        await self._bot.respond(self.api.invoker,
                                f"`{file.name}`\n"
                                f"Status: **{file.status.capitalize()}**\n"
                                f"Error: __{file.error_message}__\n"
                                f"Code: **{file.error_code}**", mode="reply")

        self.log.warning(f"[gid: '{gid}']: {file.error_message}")
        async with self.api.lock:
            del self.downloads[file.gid]

            if len(self.downloads) == 0:
                self.api.invoker = None

    async def _checkProgress(self) -> str:
        progress_string = ""
        time = util.time.format_duration_td
        human = util.misc.human_readable_bytes
        for file in self.downloads.values():
            file = await file.update
            if file.failed or file.paused or (file.complete and file.metadata):
                continue

            if file.complete and not file.metadata:
                file = self.uploads[file.gid]
                progress, done = await self._uploadProgress(file)
                if not done:
                    progress_string += progress

                continue

            downloaded = file.completed_length
            file_size = file.total_length
            percent = file.progress
            speed = file.download_speed
            eta = file.eta_formatted
            bullets = "●" * int(round(percent * 10)) + "○"
            if len(bullets) > 10:
                bullets = bullets.replace("○", "")

            space = '   ' * (10 - len(bullets))
            progress_string += (
                f"`{file.name}`\nGID: `{file.gid}`\n"
                f"Status: **{file.status.capitalize()}**\n"
                f"Progress: [{bullets + space}] {round(percent * 100)}%\n"
                f"__{human(downloaded)} of {human(file_size)} @ "
                f"{human(speed, postfix='/s')}\neta - {time(eta)}__\n\n")

        return progress_string

    async def _updateProgress(self) -> None:
        while not self.api.stopping:
            if len(self.complete) != 0:
                for gid in self.complete:
                    if gid in self.downloads and gid in self.uploads:
                        async with self.api.lock:
                            del self.downloads[gid]
                            del self.uploads[gid]

            if len(self.downloads) >= 1:
                progress = await self._checkProgress()
                try:
                    await self.api.invoker.edit(progress)
                except (MessageNotModified, MessageEmpty):
                    await asyncio.sleep(1)
                else:
                    await asyncio.sleep(5)
                finally:
                    continue
            elif len(self.downloads) == 0 and self.api.invoker is not None:
                self.complete = []  # CHECKME
                await self.api.invoker.delete()
                self.api.invoker = None

            await asyncio.sleep(1)

    async def _uploadProgress(
        self, file: List[Union[MediaFileUpload, str]]
    ) -> Tuple[Union[str, None], bool]:
        file_name = file[1]
        gid = file[2]
        start = file[3]
        time = util.time.format_duration_td
        human = util.misc.human_readable_bytes

        file = file[0]
        status, response = await util.run_sync(file.next_chunk)
        if status:
            file_size = status.total_size
            end = util.time.sec() - start
            uploaded = status.resumable_progress
            percent = uploaded / file_size
            speed = round(uploaded / end, 2)
            eta = timedelta(seconds=int(round((file_size - uploaded) / speed)))
            bullets = "●" * int(round(percent * 10)) + "○"
            if len(bullets) > 10:
                bullets = bullets.replace("○", "")

            space = '   ' * (10 - len(bullets))
            progress = (
                f"`{file_name}`\nGID: `{gid}`\n"
                f"Status: **Uploading**\n"
                f"Progress: [{bullets + space}] {round(percent * 100)}%\n"
                f"__{human(uploaded)} of {human(file_size)} @ "
                f"{human(speed, postfix='/s')}\neta - {time(eta)}__\n\n"
            )

        if response is None:
            return progress, False

        file_size = response.get("size")
        mirrorLink = response.get("webContentLink")
        text = (f"**GoogleDrive Link**: [{file_name}]({mirrorLink}) "
                f"(__{human(file_size)}__)")
        if self.drive.index_link is not None:
            if self.drive.index_link.endswith("/"):
                link = self.drive.index_link + parse.quote(file_name)
            else:
                link = self.drive.index_link + "/" + parse.quote(file_name)
            text += f"\n\n__Shareable link__: [{file_name}]({link})"

        await self._bot.respond(
            self.api.invoker,
            text=text,
            mode="reply"
        )

        self.complete.append(gid)

        return None, True


class Aria2(module.Module):
    name: ClassVar[str] = "Aria2"

    client: Aria2WebSocket
    invoker: pyrogram.types.Message
    lock: asyncio.Lock
    stopping: bool

    async def on_load(self) -> None:
        self.client = await Aria2WebSocket.init(self)

        self.invoker = None
        self.stopping = False

        self.lock = asyncio.Lock()

    async def on_stop(self) -> None:
        self.stopping = True
        await self.client.close()

    async def addDownload(self, uri: str, msg: pyrogram.types.Message) -> None:
        await self.client.addUri([uri])

        # Save the message but delete first so we don't spam chat with new download
        if self.invoker is not None:
            async with self.lock:
                await self.invoker.delete()
        self.invoker = msg

    async def pauseDownload(self, gid: str) -> str:
        return await self.client.pause(gid)

    async def removeDownload(self, gid: str) -> str:
        return await self.client.remove(gid)

    async def cancelMirror(self, gid: str):
        await self.pauseDownload(gid)
        await self.removeDownload(gid)
