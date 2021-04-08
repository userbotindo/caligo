import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple, Union
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
        self.index_link = self.drive.index_link
        self.lock = self.api.lock
        self.log = self.api.log

        self.counter: Dict[str, int] = {}
        self.downloads: Dict[str, util.aria2.Download] = {}
        self.uploads: Dict[str, MediaFileUpload] = {}
        self.seedTask: List[asyncio.Task] = []

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
        server = aioaria2.AsyncAria2Server(*cmd, daemon=True)
        await server.start()
        await server.wait()

        self = cls(api)
        protocol = "http://127.0.0.1:8080/jsonrpc"
        client = await aioaria2.Aria2WebsocketTrigger.new(url=protocol)

        trigger = [(self.on_download_start, "onDownloadStart"),
                   (self.on_download_complete, "onDownloadComplete"),
                   (self.on_download_error, "onDownloadError")]
        for handler, name in trigger:
            client.register(handler, f"aria2.{name}")

        self.bot.loop.create_task(self.updateProgress())
        self.bot.loop.create_task(self.waitSeed())
        return client

    @property
    def count(self) -> int:
        return len(self.downloads)

    async def get_download(self, client: aioaria2.Aria2WebsocketTrigger,
                           gid: str) -> util.aria2.Download:
        res = await client.tellStatus(gid)
        return await util.run_sync(util.aria2.Download, client, res)

    async def on_download_start(self, trigger: aioaria2.Aria2WebsocketTrigger,
                                data: Union[Dict[str, str], Any]) -> None:
        gid = data["params"][0]["gid"]
        async with self.lock:
            self.downloads[gid] = await self.get_download(trigger, gid)
        self.log.info(f"Starting download: [gid: '{gid}']")

    async def on_download_complete(self,
                                   trigger: aioaria2.Aria2WebsocketTrigger,
                                   data: Union[Dict[str, str], Any]) -> None:
        gid = data["params"][0]["gid"]
        async with self.lock:
            self.downloads[gid] = await self.get_download(trigger, gid)
        file = self.downloads[gid]

        meta = ""
        if file.metadata is True:
            async with self.lock:
                del self.downloads[file.gid]
            meta += " - Metadata"
        else:
            if (Path(file.dir) / file.name).is_file():
                async with self.lock:
                    self.uploads[file.gid] = await self.drive.uploadFile(file)
            elif (Path(file.dir) / file.name).is_dir():
                async with self.lock:
                    self.counter[file.gid] = 0
                folderId = await self.drive.createFolder(file.name)
                async for task in self.drive.uploadFolder(
                        Path(file.dir) / file.name, parent_id=folderId):
                    await task
                    async with self.lock:
                        self.counter[file.gid] += 1

                folderLink = (
                    f"**GoogleDrive folderLink**: [{file.name}]"
                    f"(https://drive.google.com/drive/folders/{folderId})")
                if self.index_link is not None:
                    if self.index_link.endswith("/"):
                        indexLink = self.index_link + parse.quote(file.name +
                                                                  "/")
                    else:
                        indexLink = self.index_link + "/" + parse.quote(
                                                            file.name + "/")
                    folderLink += f"\n\n__IndexLink__: [Here]({indexLink})."
                async with self.lock:
                    del self.counter[file.gid]
                    del self.downloads[file.gid]
                    if self.count == 0:
                        await asyncio.gather(self.api.invoker.reply(folderLink),
                                             self.api.invoker.delete())
                        self.api.invoker = None
                    else:
                        await self.api.invoker.reply(folderLink)
            if file.bittorrent:
                task = self.bot.loop.create_task(self.seedFile(file))
                self.seedTask.append(task)

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
        async with self.lock:
            del self.downloads[file.gid]
            if self.count == 0:
                await self.api.invoker.delete()
                self.api.invoker = None

    @retry(wait=wait_random_exponential(multiplier=2, min=3, max=6),
           stop=stop_after_attempt(5),
           retry=retry_if_exception_type(KeyError))
    async def checkProgress(self) -> str:
        progress_string = ""
        time = util.time.format_duration_td
        human = util.misc.human_readable_bytes

        for file in list(self.downloads.values()):
            try:
                file = await file.update
            except aioaria2.exceptions.Aria2rpcException:
                continue
            if (file.failed or file.paused or
               (file.complete and file.metadata) or file.removed):
                continue

            if file.complete and not file.metadata:
                if (file.dir / file.name).is_dir():
                    progress_string += (
                        f"`{file.name}`\nComputing Upload: "
                        f"[{self.counter[file.gid]}/{len(file.files)}]\n\n")
                    continue

                async with self.lock:
                    f = self.uploads[file.gid]
                progress, done = await self.uploadProgress(f)
                if not done:
                    progress_string += progress
                else:
                    async with self.lock:
                        del self.downloads[file.gid]
                        if self.count == 0 and self.api.invoker is not None:
                            await self.api.invoker.delete()
                            self.api.invoker = None

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

        return progress_string

    async def updateProgress(self) -> None:
        last_update_time = None
        while not self.api.stopping:
            for gid in self.api.cancelled[:]:
                async with self.lock:
                    if gid in self.downloads:
                        del self.downloads[gid]
                    if gid in self.uploads:
                        del self.uploads[gid]
                    self.api.cancelled.remove(gid)
                    if self.count == 0 and self.api.invoker is not None:
                        await self.api.invoker.delete()
                        self.api.invoker = None

            progress = await self.checkProgress()
            now = datetime.now()

            if last_update_time is None or (
                    now - last_update_time).total_seconds() >= 5 and (
                        progress != "") and self.api.invoker is not None:
                try:
                    if self.api.invoker is not None:
                        async with self.lock:
                            await self.api.invoker.edit(progress)
                except pyrogram.errors.MessageNotModified:
                    pass
                finally:
                    last_update_time = now

            await asyncio.sleep(0.1)

    async def seedFile(self, file: util.aria2.Download) -> Literal["OK"]:
        self.log.info(f"Seeding: [gid: '{file.gid}']")
        port = util.aria2.get_free_port()
        file_path = Path.home() / "downloads" / file.info_hash
        cmd = [
            "aria2c", "--enable-rpc", "--rpc-listen-all=false",
            f"--rpc-listen-port={port}", "--bt-seed-unverified=true",
            "--seed-ratio=1", f"-i {str(file_path) + '.torrent'}"
        ]

        await util.system.run_command(*cmd)
        self.log.info(f"Seeding: [gid: '{file.gid}'] - Complete")

        return "OK"

    async def waitSeed(self) -> None:
        while not self.api.stopping:
            if len(self.seedTask) >= 1:
                tasks = self.seedTask[:]
                await asyncio.gather(*tasks)
                if len(tasks) != len(self.seedTask):
                    self.seedTask = self.seedTask[len(tasks):]

            await asyncio.sleep(1)

    async def uploadProgress(
            self, file: MediaFileUpload) -> Tuple[Union[str, None], bool]:
        time = util.time.format_duration_td
        human = util.misc.human_readable_bytes

        status, response = await util.run_sync(file.next_chunk, num_retries=5)
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
        fileLink = (f"**GoogleDrive Link**: [{file.name}]({mirrorLink}) "
                    f"(__{human(int(file_size))}__)")
        if self.index_link is not None:
            if self.index_link.endswith("/"):
                link = self.index_link + parse.quote(file.name)
            else:
                link = self.index_link + "/" + parse.quote(file.name)
            fileLink += f"\n\n__IndexLink__: [Here]({link})."

        await self.bot.respond(self.api.invoker, text=fileLink, mode="reply")
        async with self.lock:
            del self.uploads[file.gid]

        return None, True


class Aria2(module.Module):
    name: ClassVar[str] = "Aria2"

    cancelled: List[str]
    client: Aria2WebSocket
    invoker: pyrogram.types.Message
    lock: asyncio.Lock
    stopping: bool

    async def on_load(self) -> None:
        self.cancelled = []
        self.invoker = None
        self.lock = asyncio.Lock()
        self.stopping = False

    async def on_started(self) -> None:
        try:
            self.client = await Aria2WebSocket.init(self)
        except FileNotFoundError:
            self.log.warning("Aria2 package is not installed.")
            self.bot.unload_module(self)
            return

    async def on_stop(self) -> None:
        self.stopping = True
        await self.client.shutdown()
        await self.client.close()

    async def on_stopped(self) -> None:
        self.invoker = None

    async def addDownload(self, types: Union[str, bytes],
                          msg: pyrogram.types.Message) -> Optional[str]:
        if isinstance(types, str):
            try:
                await self.client.addUri([types])
            except aioaria2.exceptions.Aria2rpcException as e:
                if "No URI to download" in str(e):
                    return "__Invalid URI.__"

                return str(e)
        elif isinstance(types, bytes):
            await self.client.addTorrent(str(types, "utf-8"))
        else:
            self.log.error(f"Unknown types of {type(types)}")
            return f"__Unknown types of {type(types)}__"

        # Save the message but delete first so we don't spam chat with new download
        async with self.lock:
            if self.invoker is not None:
                await self.invoker.delete()
            self.invoker = msg
        return None

    async def pauseDownload(self, gid: str) -> str:
        return await self.client.pause(gid)

    async def removeDownload(self, gid: str) -> str:
        return await self.client.remove(gid)

    async def cancelMirror(self, gid: str) -> str:
        status = (await self.client.tellStatus(gid, ["status"]))["status"]
        metadata = bool((await self.client.tellStatus(gid, ["followedBy"])
                    ).get("followedBy"))
        if status == "active":
            await self.client.forcePause(gid)
            await self.client.forceRemove(gid)
            ret = f"**Aborted download: [gid: '{gid}']**"
        elif status == "complete":
            if metadata is True:
                ret = "__That GID belongs to finished Metadata, can't be abort.__"
            else:
                ret = f"**Aborted upload: [gid: '{gid}']**"
        else:
            ret = f"**Aborted: [gid: '{gid}']**"

        self.cancelled.append(gid)
        return ret
