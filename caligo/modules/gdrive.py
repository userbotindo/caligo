import asyncio
import json
import pickle
from typing import ClassVar, Dict, Union

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from motor.motor_asyncio import AsyncIOMotorDatabase
import pyrogram

from .. import command, module, util


class GoogleDrive(module.Module):
    name: ClassVar[str] = "GDrive"

    configs: Dict[str, str]
    creds: Credentials
    db: AsyncIOMotorDatabase
    flow: InstalledAppFlow
    lock: asyncio.Lock
    service: Resource

    async def on_load(self) -> None:
        self.configs = json.loads(self.bot.getConfig.gdrive_data)
        self.creds = None
        self.data = None
        self.lock = asyncio.Lock()

        self.db = self.bot.get_db("gdrive")

    async def cmd_gdlist(self, ctx: command.Context):
        if self.creds is None:
            return "You haven't auth your gdrive"

        results = self.service.files().list(
            pageSize=10, fields="nextPageToken, files(id, name)").execute()
        items = results.get('files', [])

        if not items:
            return "No files found."

        text = ""
        for item in items:
            text += f"{item['name']} {item['id']}\n"
        return text

    async def cmd_gdauth(self, ctx: command.Context) -> Union[str, None]:
        if self.creds is not None:
            return "Credentials is exists, skipping."

        flow = InstalledAppFlow.from_client_config(
            self.configs, ["https://www.googleapis.com/auth/drive"],
            redirect_uri=self.configs["installed"].get("redirect_uris")[0]
        )
        auth_url, _ = flow.authorization_url(
            access_type="offline", prompt="consent"
        )

        await ctx.respond("Check your log group.")
        log_msg = await ctx.bot.client.send_message(
            ctx.bot.getConfig.log,
            f"Please visit the link:\n{auth_url}\nAnd reply the token."
        )

        async def wait_for_token(timeout: int):
            for sleep in range(timeout):
                if self.data:
                    break
                await asyncio.sleep(1)

        await self.bot.loop.create_task(wait_for_token(45))
        if not self.data:
            return "Timeout: no token receive."

        await log_msg.delete()
        await self.data.delete()
        try:
            await util.run_sync(flow.fetch_token, code=self.data.text)
        except Exception as E:
            self.data = None
            return (
                "**Invalid token received**\n\n"
                f"**Error**:\n\n```{util.error.format_exception(E)}```"
            )

        creds = flow.credentials
        credential = await util.run_sync(pickle.dumps, creds)

        async with self.lock:
            await self.db.update_one(
                {"_id": self.bot.uid},
                {
                    "$set": {"creds": credential}
                },
                upsert=True
            )

        self.data = None
        return "Credentials created."

    async def on_started(self) -> None:
        data = await self.db.find_one({"_id": self.bot.uid})
        if not data:
            return

        self.creds = await util.run_sync(pickle.loads, data.get("creds"))
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.log.info("Refreshing credentials")
                await util.run_sync(self.creds.refresh, Request())
                credential = await util.run_sync(pickle.dumps, self.creds)
                async with self.lock:
                    await self.db.update_one(
                        {"_id": self.bot.uid},
                        {
                            "$set": {"creds": credential}
                        }
                    )
            else:
                return
        self.service = build('drive', 'v3', credentials=self.creds, cache_discovery=False)

    async def on_token(self, event: pyrogram.types.Message) -> None:
        if self.creds is not None:
            return

        if event.text.startswith("4/"):
            self.data = event
