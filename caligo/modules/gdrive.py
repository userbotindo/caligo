import asyncio
import pickle
from typing import ClassVar, Dict, Union

import pyrogram
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.discovery import Resource
from google.oauth2.credentials import Credentials
from motor.motor_asyncio import AsyncIOMotorDatabase
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError

from .. import command, module, util


class GoogleDrive(module.Module):
    name: ClassVar[str] = "GoogleDrive"

    configs: Dict[str, str]
    creds: Credentials
    db: AsyncIOMotorDatabase
    lock: asyncio.Lock
    service: Resource

    async def on_load(self) -> None:
        self.db = self.bot.get_db("gdrive")
        self.creds = None
        data = await self.db.find_one({"_id": self.name})

        self.configs = self.bot.getConfig.gdrive_secret
        if self.configs is None and data is None:
            self.log.warning("GoogleDrive module secret not satisfy.")
            self.bot.unload_module(self)
            return

        self.lock = asyncio.Lock()

        if data:
            self.creds = await util.run_sync(pickle.loads, data.get("creds"))
            # service will be overwrite if credentials is expired
            self.service = build(
                "drive",
                "v3",
                credentials=self.creds,
                cache_discovery=False
            )

    @command.desc("Check your GoogleDrive credentials")
    @command.alias("gdauth")
    async def cmd_gdcheck(self, ctx: command.Context) -> None:
        await ctx.respond("You are all set.")

    async def getAccessToken(self, message: pyrogram.types.Message) -> str:
        flow = InstalledAppFlow.from_client_config(
            self.configs, ["https://www.googleapis.com/auth/drive"],
            redirect_uri=self.configs["installed"].get("redirect_uris")[0]
        )
        auth_url, _ = flow.authorization_url(
            access_type="offline", prompt="consent"
        )

        await self.bot.respond(message, "Check your **Saved Message.**")
        async with self.bot.conversation("me", timeout=60) as conv:
            request = await conv.send_message(
                f"Please visit the link:\n{auth_url}\n"
                "And reply the token here.\n**You have 60 seconds**."
            )

            try:
                response = await conv.get_response()
            except asyncio.TimeoutError:
                await request.delete()
                return "⚠️ Timeout no token receive"

        await self.bot.respond(message, "Token received...")
        token = response.text

        await request.delete()
        await response.delete()

        try:
            await util.run_sync(flow.fetch_token, code=token)
        except InvalidGrantError:
            return (
                "⚠️ Error fetching token\n\n"
                "Refresh token is invalid, expired, revoked, "
                "or does not match the redirection URI."
            )

        self.creds = flow.credentials
        credential = await util.run_sync(pickle.dumps, self.creds)

        async with self.lock:
            await self.db.find_one_and_update(
                {"_id": self.name},
                {
                    "$set": {"creds": credential}
                },
                upsert=True
            )

        return "Credentials created."

    async def authorize(self, message: pyrogram.types.Message) -> Union[None, bool]:
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.log.info("Refreshing credentials")
                await util.run_sync(self.creds.refresh,
                                    await util.run_sync(Request))

                credential = await util.run_sync(pickle.dumps, self.creds)
                async with self.lock:
                    await self.db.find_one_and_update(
                        {"_id": self.name},
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
                if self.creds is None:
                    return False

            self.service = build(
                "drive",
                "v3",
                credentials=self.creds,
                cache_discovery=False
            )
