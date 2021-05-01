import asyncio
import base64
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import (
    Any,
    AsyncIterator,
    ClassVar,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union
)

import aiofile
import pyrogram
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from motor.motor_asyncio import AsyncIOMotorDatabase
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError

from .. import command, module, util

MIME_TYPE = {
    "application/gzip": "📦",
    "application/octet-stream": "⚙️",
    "application/vnd.google-apps.folder": "📁️",
    "application/vnd.rar": "📦",
    "application/x-7z-compressed": "📦",
    "application/x-bzip": "📦",
    "application/x-bzip2": "📦",
    "application/x-tar": "📦",
    "application/zip": "📦",
    "audio/aac": "🎵",
    "audio/mp4": "🎵",
    "audio/mpeg": "🎵",
    "audio/ogg": "🎵",
    "audio/wav": "🎵",
    "audio/x-opus+ogg": "🎵",
    "image/gif": "🖼️",
    "image/jpeg": "🖼️",
    "image/png": "🖼️",
    "video/mp4": "🎥️",
    "video/x-matroska": "🎥️"
}


class GoogleDrive(module.Module):
    name: ClassVar[str] = "GoogleDrive"
    disabled: ClassVar[bool] = not util.BotConfig.mirror_enabled

    configs: Dict[str, str]
    creds: Credentials
    db: AsyncIOMotorDatabase
    service: Resource

    aria2: Any
    index_link: str
    parent_id: str
    task: Set[Tuple[int, asyncio.Task]]

    async def on_load(self) -> None:
        self.creds = None
        self.db = self.bot.get_db("gdrive")
        self.index_link = self.bot.getConfig.gdrive_index_link
        self.parent_id = self.bot.getConfig.gdrive_folder_id
        self.task = set()

        try:
            creds = (await self.db.find_one({"_id": self.name}))["creds"]
        except (KeyError, TypeError):
            self.configs = self.bot.getConfig.gdrive_secret
            if not self.configs:
                self.log.warning(f"{self.name} module secret not satisfy.")
                self.bot.unload_module(self)
                return
        else:
            self.aria2 = self.bot.modules["Aria2"]
            self.creds = await util.run_sync(pickle.loads, creds)
            # service will be overwrite if credentials is expired
            self.service = await util.run_sync(build,
                                               "drive",
                                               "v3",
                                               credentials=self.creds,
                                               cache_discovery=False)

    @command.desc("Check your GoogleDrive credentials")
    @command.alias("gdauth")
    async def cmd_gdcheck(self, ctx: command.Context) -> None:  # skipcq: PYL-W0613
        return "You are all set.", 5

    @command.desc("Clear/Reset your GoogleDrive credentials")
    @command.alias("gdreset")
    async def cmd_gdclear(self, ctx: command.Context) -> None:
        if not self.creds:
            return "__Credentials already empty.__"

        await self.db.delete_one({"_id": self.name})
        await asyncio.gather(self.on_load(), ctx.respond(
                             "__Credentials cleared.__"))

    async def getAccessToken(self, message: pyrogram.types.Message) -> str:
        flow = InstalledAppFlow.from_client_config(
            self.configs, ["https://www.googleapis.com/auth/drive"],
            redirect_uri=self.configs["installed"].get("redirect_uris")[0])
        auth_url, _ = flow.authorization_url(access_type="offline",
                                             prompt="consent")

        await self.bot.respond(message, "Check your **Saved Message.**")
        async with self.bot.conversation("me", timeout=60) as conv:
            request = await conv.send_message(
                f"Please visit the link:\n{auth_url}\n"
                "And reply the token here.\n**You have 60 seconds**.")

            try:
                response = await conv.get_response()
            except conv.Timeout:
                await request.delete()
                return "⚠️ <u>Timeout no token receive</u>"

        await self.bot.respond(message, "Token received...")
        token = response.text

        try:
            await asyncio.gather(request.delete(), response.delete(),
                                 util.run_sync(flow.fetch_token, code=token))
        except InvalidGrantError:
            return ("⚠️ **Error fetching token**\n\n"
                    "__Refresh token is invalid, expired, revoked, "
                    "or does not match the redirection URI.__")

        self.creds = flow.credentials
        credential = await util.run_sync(pickle.dumps, self.creds)

        await self.db.find_one_and_update({"_id": self.name},
                                          {"$set": {
                                              "creds": credential
                                          }},
                                          upsert=True)
        await self.on_load()

        return "Credentials created."

    async def authorize(self,
                        message: pyrogram.types.Message) -> Optional[bool]:
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.log.info("Refreshing credentials")
                await util.run_sync(self.creds.refresh, Request())

                credential = await util.run_sync(pickle.dumps, self.creds)
                await self.db.find_one_and_update(
                    {"_id": self.name}, {"$set": {
                        "creds": credential
                    }})
            else:
                await asyncio.gather(self.bot.respond(message,
                                     "Credential is empty, generating..."),
                                     asyncio.sleep(2.5))

                ret = await self.getAccessToken(message)

                await self.bot.respond(message, ret)
                if self.creds is None:
                    return False

            await self.on_load()

    async def getInfo(self, identifier: str, fields: List[str]) -> Dict[str,
                                                                        Any]:
        fields = ", ".join(fields)

        return await util.run_sync(self.service.files(
                                   ).get(fileId=identifier, fields=fields,
                                         supportsAllDrives=True).execute)

    async def createFolder(self,
                           folderName: str,
                           folderId: Optional[str] = None) -> str:
        folder_metadata = {
            "name": folderName,
            "mimeType": "application/vnd.google-apps.folder"
        }
        if folderId is not None:
            folder_metadata["parents"] = [folderId]
        elif folderId is None and self.parent_id is not None:
            folder_metadata["parents"] = [self.parent_id]

        folder = await util.run_sync(self.service.files().create(
            body=folder_metadata, fields="id", supportsAllDrives=True).execute)
        return folder["id"]

    async def uploadFolder(
        self,
        sourceFolder: Path,
        *,
        gid: Optional[str] = None,
        parent_id: Optional[str] = None,
        msg: Optional[pyrogram.types.Message] = None
    ) -> AsyncIterator[asyncio.Task]:
        for content in sourceFolder.iterdir():
            if content.is_dir():
                childFolder = await self.createFolder(content.name, parent_id)
                async for task in self.uploadFolder(content,
                                                    gid=gid,
                                                    parent_id=childFolder,
                                                    msg=msg):
                    yield task
            elif content.is_file():
                file = util.File(content)
                files = await self.uploadFile(file, parent_id)
                if isinstance(files, str):  # Skip because file size is 0
                    continue

                file.content, file.start_time = files, util.time.sec()
                file.invoker = msg

                yield self.bot.loop.create_task(file.progress(update=False),
                                                name=gid)

    async def uploadFile(self,
                         file: Union[util.File, util.aria2.Download],
                         parent_id: Optional[str] = None) -> MediaFileUpload:
        body = {"name": file.name, "mimeType": file.mime_type}
        if parent_id is not None:
            body["parents"] = [parent_id]
        elif parent_id is None and self.parent_id is not None:
            body["parents"] = [self.parent_id]

        if file.path.stat().st_size > 0:
            media_body = MediaFileUpload(file.path,
                                         mimetype=file.mime_type,
                                         resumable=True,
                                         chunksize=50 * 1024 * 1024)
            files = await util.run_sync(self.service.files().create,
                                        body=body,
                                        media_body=media_body,
                                        fields="id, size, webContentLink",
                                        supportsAllDrives=True)
        else:
            media_body = MediaFileUpload(file.path, mimetype=file.mime_type)
            files = await util.run_sync(self.service.files().create(
                body=body,
                media_body=media_body,
                fields="id, size, webContentLink",
                supportsAllDrives=True).execute)

            return files.get("id")

        if not isinstance(file, util.File):
            files.gid, files.name = file.gid, file.name
            files.start_time = util.time.sec()

        return files

    async def downloadFile(self, ctx: command.Context,
                           msg: pyrogram.types.Message) -> Optional[Path]:
        downloadPath = ctx.bot.getConfig.downloadPath

        before = util.time.sec()
        last_update_time = None
        human = util.misc.human_readable_bytes
        time = util.time.format_duration_td
        if msg.document:
            file_name = msg.document.file_name
        elif msg.audio:
            file_name = msg.audio.file_name
        elif msg.video:
            file_name = msg.video.file_name
        elif msg.sticker:
            file_name = msg.sticker.file_name
        elif msg.photo:
            date = datetime.fromtimestamp(msg.photo.date)
            file_name = f"photo_{date.strftime('%Y-%m-%d_%H-%M-%S')}.jpg"
        elif msg.voice:
            date = datetime.fromtimestamp(msg.voice.date)
            file_name = f"audio_{date.strftime('%Y-%m-%d_%H-%M-%S')}.ogg"

        def prog_func(current: int, total: int) -> None:
            nonlocal last_update_time

            percent = current / total
            after = util.time.sec() - before
            now = datetime.now()

            try:
                speed = round(current / after, 2)
                eta = timedelta(seconds=int(round((total - current) / speed)))
            except ZeroDivisionError:
                speed = 0
                eta = timedelta(seconds=0)
            bullets = "●" * int(round(percent * 10)) + "○"
            if len(bullets) > 10:
                bullets = bullets.replace("○", "")

            space = '    ' * (10 - len(bullets))
            progress = (
                f"`{file_name}`\n"
                f"Status: **Downloading**\n"
                f"Progress: [{bullets + space}] {round(percent * 100)}%\n"
                f"__{human(current)} of {human(total)} @ "
                f"{human(speed, postfix='/s')}\neta - {time(eta)}__\n\n")
            # Only edit message once every 5 seconds to avoid ratelimits
            if last_update_time is None or (
                    now - last_update_time).total_seconds() >= 5:
                self.bot.loop.create_task(ctx.respond(progress))

                last_update_time = now

        file_path = downloadPath / file_name
        file_path = await ctx.bot.client.download_media(msg,
                                                        file_name=file_path,
                                                        progress=prog_func)

        return Path(file_path) if file_path is not None else None

    @command.desc("Mirror Magnet/Torrent/Link/Message Media into GoogleDrive")
    @command.usage("[Magnet/Torrent/Link or reply to message]")
    async def cmd_gdmirror(self, ctx: command.Context) -> Optional[str]:
        if not ctx.input and not ctx.msg.reply_to_message:
            return "__Either link nor media found.__"
        if ctx.input and ctx.msg.reply_to_message:
            return "__Can't pass link while replying to message.__"

        if ctx.msg.reply_to_message:
            reply_msg = ctx.msg.reply_to_message

            if reply_msg.media:
                task = self.bot.loop.create_task(self.downloadFile(ctx,
                                                                   reply_msg))
                self.task.add((ctx.msg.message_id, task))
                try:
                    await task
                except asyncio.CancelledError:
                    return "__Transmission aborted.__"
                else:
                    path = task.result()
                    self.task.remove((ctx.msg.message_id, task))

                if path.suffix == ".torrent":
                    async with aiofile.async_open(path, "rb") as afp:
                        types = base64.b64encode(await afp.read())
                else:
                    file = util.File(path)
                    files = await self.uploadFile(file)
                    file.content, file.invoker = files, ctx.msg
                    file.start_time = util.time.sec()
                    if self.index_link is not None:
                        file.index_link = self.index_link

                    task = self.bot.loop.create_task(file.progress())
                    self.task.add((ctx.msg.message_id, task))
                    try:
                        await task
                    except asyncio.CancelledError:
                        return "__Transmission aborted.__"
                    else:
                        self.task.remove((ctx.msg.message_id, task))

                    return
            elif reply_msg.text:
                types = reply_msg.text
            else:
                return "__Unsupported types of download.__"
        else:
            types = ctx.input

        try:
            ret = await self.aria2.addDownload(types, ctx.msg)
            if ret is not None:
                return ret
        except NameError:
            return "__Mirroring torrent file/url needs Aria2 loaded.__"

    @command.pattern(
        r"(parent)=(\w+)|(limit)=(\d+)|(name)=(\w+)|"
        r"(?<=(q)=)(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')")
    @command.alias("gdlist", "gdls")
    @command.usage(
        "[parent=folderId] [name=file/folder name] [limit=number] "
        "[q=\"search query\", single/double quote important here]",
        optional=True)
    async def cmd_gdsearch(self, ctx):
        options = {}
        for match in ctx.matches:
            for index, option in enumerate(match.groups()):
                if option is not None and match.group(index + 2) is not None:
                    options[option] = match.group(index + 2)
                    break

        await ctx.respond("Collecting...")

        parent = options.get("parent")
        name = options.get("name")
        limit = int(options.get("limit", 15))
        if limit > 1000:
            return "__Can't use limit more than 1000.__", 5

        if parent is not None and name is not None:
            query = f"'{parent}' in parents and (name contains '{name}')"
        elif parent is not None and name is None:
            query = f"'{parent}' in parents and (name contains '*')"
        elif parent is None and name is not None:
            query = f"name contains '{name}'"
        else:
            query = ""

        try:
            # Ignore given parent and name options if q present
            # and remove " or ' from matches string
            q = options["q"]
            query = q.removesuffix(q[0]).removeprefix(q[0])
        except KeyError:
            pass

        fields = "nextPageToken, files(name, id, mimeType, webViewLink)"
        output = ""
        pageToken = None
        count = 0

        while True:
            try:
                response = await util.run_sync(self.service.files().list(
                    supportsAllDrives=True, includeItemsFromAllDrives=True,
                    q=query, spaces="drive", corpora="allDrives", fields=fields,
                    pageSize=limit, orderBy="folder, name asc",
                    pageToken=pageToken).execute)
            except HttpError as e:
                if "'location': 'q'" in str(e):
                    return "__Invalid parameters of query.__", 5

                return str(e), 7

            for file in response.get("files", []):
                if count >= limit:
                    break

                output += (MIME_TYPE.get(file["mimeType"], "📄") +
                           f" [{file['name']}]({file['webViewLink']})\n")
                count += 1

            if count >= limit:
                break

            pageToken = response.get("nextPageToken", None)
            if pageToken is None:
                break

        if query == "":
            query = "Not specified"

        return f"**Google Drive Search**:\n{query}\n\n**Result**\n{output}"
