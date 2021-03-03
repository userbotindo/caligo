import asyncio
import pickle
from typing import ClassVar, Dict

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.discovery import Resource
from google.oauth2.credentials import Credentials
from motor.motor_asyncio import AsyncIOMotorDatabase
import pyrogram

from .. import command, module, util


class GoogleDrive(module.Module):
    name: ClassVar[str] = "GoogleDrive"

    configs: Dict[str, str]
    creds: Credentials
    db: AsyncIOMotorDatabase
    lock: asyncio.Lock
    service: Resource

    async def on_load(self) -> None:
        self.configs = self.bot.getConfig.gdrive_data
        self.creds = None
        self.lock = asyncio.Lock()

        self.db = self.bot.get_db("gdrive")

    async def on_started(self) -> None:
        data = await self.db.find_one({"_id": self.bot.uid})
        if not data:
            return

        self.creds = await util.run_sync(pickle.loads, data.get("creds"))

    async def cmd_gdcheck(self, ctx: command.Context) -> None:
        await ctx.respond("You are all set.")
        return

    async def getAccessToken(self, message: pyrogram.types.Message) -> str:
        flow = InstalledAppFlow.from_client_config(
            self.configs, ["https://www.googleapis.com/auth/drive"],
            redirect_uri=self.configs["installed"].get("redirect_uris")[0]
        )
        auth_url, _ = flow.authorization_url(
            access_type="offline", prompt="consent"
        )

        await self.bot.respond(message, "Check your **Saved Messages**.")
        link_msg = await self.bot.client.send_message(
            "me",
            f"Please visit the link:\n{auth_url}\nAnd reply the token here."
        )

        count = 0  # limit time 1 minute
        while True:
            if count > 60:
                break

            try:
                token = (
                    await self.bot.client.get_dialogs(pinned_only=True)
                )[0].top_message
            except IndexError:  # Workaround if don't have any saved message
                count += 3
                await asyncio.sleep(3)
                continue

            if not token.text.startswith("4/"):
                count += 3
                await asyncio.sleep(3)
                continue

            await self.bot.respond(message, "Token received...")
            break

        try:
            await util.run_sync(flow.fetch_token, code=token.text)
        except Exception:
            await link_msg.delete()
            return "**Invalid or empty token**"

        await token.delete()
        await link_msg.delete()

        self.creds = flow.credentials
        credential = await util.run_sync(pickle.dumps, self.creds)

        async with self.lock:
            await self.db.update_one(
                {"_id": self.bot.uid},
                {
                    "$set": {"creds": credential}
                },
                upsert=True
            )

        return "Credentials created."

    async def authorize(self, message: pyrogram.types.Message) -> None:
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
                await self.bot.respond(
                    message,
                    "Credential is empty, generating..."
                )
                await asyncio.sleep(1.5)  # give people time to read

                ret = await self.getAccessToken(message)

                await self.bot.respond(message, ret)

        self.service = build(
            "drive",
            "v3",
            credentials=self.creds,
            cache_discovery=False
        )
