import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator, ClassVar, Dict, List, Tuple, Union
from urllib import parse

import aioaria2
import pyrogram
from googleapiclient.http import MediaFileUpload
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from .. import module, util


class Aria2WebSocket:

    server: aioaria2.AsyncAria2Server
    client: aioaria2.Aria2WebsocketTrigger

    def __init__(self, api: "Aria2") -> None:
        self.api = api
        self.bot = self.api.bot
        self.drive = self.bot.modules.get("GoogleDrive")
        self.log = self.api.log

        self.downloads: Dict[str, util.aria2.Download] = {}
        self.uploads: Dict[str, MediaFileUpload] = {}

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
            "--seed-time=0.01", "--seed-ratio=0.1",
            "--max-concurrent-downloads=5", "--min-split-size=10M",
            "--follow-torrent=mem", "--split=10", "--bt-save-metadata=true",
            f"--bt-tracker={trackers}", "--daemon=true",
            "--allow-overwrite=true"
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

        self.bot.loop.create_task(self._updateProgress())
        return client

    async def get_download(self, client: aioaria2.Aria2WebsocketTrigger,
                           gid: str) -> util.aria2.Download:
        res = await client.tellStatus(gid)
        return await util.run_sync(util.aria2.Download, client, res)

    async def on_download_start(self, trigger: aioaria2.Aria2WebsocketTrigger,
                                data: Union[Dict[str, str], Any]) -> None:
        gid = data["params"][0]["gid"]
        self.downloads[gid] = await self.get_download(trigger, gid)
        self.log.info(f"Starting download: [gid: '{gid}']")

    async def on_download_complete(self,
                                   trigger: aioaria2.Aria2WebsocketTrigger,
                                   data: Union[Dict[str, str], Any]) -> None:
        gid = data["params"][0]["gid"]
        self.downloads[gid] = await self.get_download(trigger, gid)
        file = self.downloads[gid]

        meta = ""
        if file.metadata is True:
            meta += " - Metadata"
            del self.downloads[file.gid]
        else:
            if (Path(file.dir) / file.name).is_file():
                self.uploads[file.gid] = await self.drive.uploadFile(file)
            elif (Path(file.dir) / file.name).is_dir():
                folderProgress = await self.api.invoker.reply(
                    "Initializing folder upload...")
                del self.downloads[file.gid]
                folderId = await self.drive.createFolder(file.name)
                await self.drive.uploadFolder(Path(file.dir) / file.name,
                                              parent_id=folderId,
                                              msg=folderProgress)

                driveFolderLink = "https://drive.google.com/drive/folders/" + folderId
                text = f"**GoogleDrive folderLink**: [{file.name}]({driveFolderLink})"
                if self.drive.index_link is not None:
                    link = self.drive.index_link + "/" + parse.quote(file.name +
                                                                     "/")
                    text += f"\n\n__Shareable link__: [Here]({link})."

                await folderProgress.reply(text)
                await folderProgress.delete()
            if file.bittorrent:
                self.bot.loop.create_task(self._seedFile(file))

        self.log.info(f"Complete download: [gid: '{gid}']{meta}")

    async def on_download_error(self, trigger: aioaria2.Aria2WebsocketTrigger,
                                data: Union[Dict[str, str], Any]) -> None:
        gid = data["params"][0]["gid"]

        file = await self.get_download(trigger, gid)
        await self.bot.respond(self.api.invoker, f"`{file.name}`\n"
                               f"Status: **{file.status.capitalize()}**\n"
                               f"Error: __{file.error_message}__\n"
                               f"Code: **{file.error_code}**",
                               mode="reply")

        self.log.warning(f"[gid: '{gid}']: {file.error_message}")
        del self.downloads[file.gid]

        if len(self.downloads) == 0:
            self.api.invoker = None

    @retry(wait=wait_random_exponential(multiplier=2, min=3, max=6),
           stop=stop_after_attempt(5),
           retry=retry_if_exception_type(KeyError))
    async def _checkProgress(self) -> str:
        completedList: List[str] = []
        progress_string = ""
        time = util.time.format_duration_td
        human = util.misc.human_readable_bytes

        for file in self.downloads.values():
            try:
                file = await file.update
            except aioaria2.exceptions.Aria2rpcException:
                continue
            if (file.failed or file.paused or
               (file.complete and file.metadata) or file.removed):
                continue

            if file.complete and not file.metadata:
                f = self.uploads[file.gid]
                progress, done = await self._uploadProgress(f)
                if not done:
                    progress_string += progress
                else:
                    completedList.append(file.gid)

                continue

            downloaded = file.completed_length
            file_size = file.total_length
            percent = file.progress
            speed = file.download_speed
            eta = file.eta_formatted
            bullets = "●" * int(round(percent * 10)) + "○"
            if len(bullets) > 10:
                bullets = bullets.replace("○", "")

            space = '    ' * (10 - len(bullets))
            progress_string += (
                f"`{file.name}`\nGID: `{file.gid}`\n"
                f"Status: **{file.status.capitalize()}**\n"
                f"Progress: [{bullets + space}] {round(percent * 100)}%\n"
                f"__{human(downloaded)} of {human(file_size)} @ "
                f"{human(speed, postfix='/s')}\neta - {time(eta)}__\n\n")

        return progress_string, self.completed(completedList)

    async def _updateProgress(self) -> None:
        last_update_time = None
        while not self.api.stopping:
            for gid in self.api.cancelled[:]:
                if gid in self.downloads:
                    del self.downloads[gid]
                if gid in self.uploads:
                    del self.uploads[gid]
                self.api.cancelled.remove(gid)

            if len(self.downloads) >= 1:
                progress, completed = await self._checkProgress()
                now = datetime.now()
                async for gid in completed:
                    del self.downloads[gid]

                if last_update_time is None or (
                        now - last_update_time).total_seconds() >= 5 and (
                            progress != ""):
                    try:
                        await self.api.invoker.edit(progress)
                    except pyrogram.errors.MessageNotModified:
                        pass

                    last_update_time = now
            elif len(self.downloads) == 0 and self.api.invoker is not None:
                await self.api.invoker.delete()
                self.api.invoker = None

            await asyncio.sleep(0.1)

    async def _seedFile(self, file: util.aria2.Download) -> None:
        self.log.info(f"Seeding: [gid: '{file.gid}']")
        port = util.aria2.get_free_port()
        file_path = Path.home() / "downloads" / file.info_hash
        cmd = [
            "aria2c", "--enable-rpc", "--rpc-listen-all=false",
            f"--rpc-listen-port={port}", "--bt-seed-unverified=true",
            "--seed-ratio=1", f"-i {str(file_path) + '.torrent'}"
        ]

        cpath = Path.home() / ".cache" / "caligo" / ".certs"
        if (Path(cpath / "cert.pem").is_file() and
                Path(cpath / "key.pem").is_file()):
            cmd.insert(3, "--rpc-secure=true")
            cmd.insert(3, f"--rpc-private-key={str(cpath / 'key.pem')}")
            cmd.insert(3, f"--rpc-certificate={str(cpath / 'cert.pem')}")

        await util.system.run_command(*cmd)
        self.log.info(f"Seeding: [gid: '{file.gid}'] - Complete")

        return None

    async def _uploadProgress(
            self, file: MediaFileUpload) -> Tuple[Union[str, None], bool]:
        time = util.time.format_duration_td
        human = util.misc.human_readable_bytes

        status, response = await util.run_sync(file.next_chunk)
        if status:
            file_size = status.total_size
            end = util.time.sec() - file.start_time
            uploaded = status.resumable_progress
            percent = uploaded / file_size
            speed = round(uploaded / end, 2)
            eta = timedelta(seconds=int(round((file_size - uploaded) / speed)))
            bullets = "●" * int(round(percent * 10)) + "○"
            if len(bullets) > 10:
                bullets = bullets.replace("○", "")

            space = '    ' * (10 - len(bullets))
            progress = (
                f"`{file.name}`\nGID: `{file.gid}`\n"
                f"Status: **Uploading**\n"
                f"Progress: [{bullets + space}] {round(percent * 100)}%\n"
                f"__{human(uploaded)} of {human(file_size)} @ "
                f"{human(speed, postfix='/s')}\neta - {time(eta)}__\n\n")

        if response is None:
            return progress, False

        file_size = response.get("size")
        mirrorLink = response.get("webContentLink")
        text = (f"**GoogleDrive Link**: [{file.name}]({mirrorLink}) "
                f"(__{human(int(file_size))}__)")
        if self.drive.index_link is not None:
            if self.drive.index_link.endswith("/"):
                link = self.drive.index_link + parse.quote(file.name)
            else:
                link = self.drive.index_link + "/" + parse.quote(file.name)
            text += f"\n\n__Shareable link__: [Here]({link})."

        await self.bot.respond(self.api.invoker, text=text, mode="reply")
        del self.uploads[file.gid]

        return None, True

    async def completed(self, completedList: List[str]) -> AsyncIterator[str]:
        for gid in completedList:
            yield gid


class Aria2(module.Module):
    name: ClassVar[str] = "Aria2"

    cancelled: List[str]
    client: Aria2WebSocket
    invoker: pyrogram.types.Message
    stopping: bool

    async def on_load(self) -> None:
        self.cancelled = []

        try:
            self.client = await Aria2WebSocket.init(self)
        except FileNotFoundError:
            self.log.warning("Aria2 package is not installed.")
            self.bot.unload_module(self)
            return

        self.invoker = None
        self.stopping = False

    async def on_stop(self) -> None:
        self.stopping = True
        await self.client.close()

    async def addDownload(self, types: Union[str, bytes],
                          msg: pyrogram.types.Message) -> None:
        if isinstance(types, str):
            await self.client.addUri([types])
        elif isinstance(types, bytes):
            await self.client.addTorrent(str(types, "utf-8"))
        else:
            self.log.error(f"Unknown types of {type(types)}")
            return

        # Save the message but delete first so we don't spam chat with new download
        if self.invoker is not None:
            await self.invoker.delete()
        self.invoker = msg

    async def pauseDownload(self, gid: str) -> str:
        return await self.client.pause(gid)

    async def removeDownload(self, gid: str) -> str:
        return await self.client.remove(gid)

    async def cancelMirror(self, gid: str) -> str:
        status = (await self.client.tellStatus(gid, ["status"]))["status"]
        if status == "active":
            await self.client.forcePause(gid)
            await self.client.forceRemove(gid)
            ret = f"__Aborted download: [gid: '{gid}']__"
        elif status == "complete":
            ret = f"__Aborted upload: [gid: '{gid}']__"
        else:
            ret = f"__Aborted: [gid: '{gid}']__"

        self.cancelled.append(gid)
        return ret
