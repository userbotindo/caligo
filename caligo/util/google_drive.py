import asyncio
import pickle

from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from .. import command, module
from .async_helpers import run_sync


async def check_credential(drive: module.Module, ctx: command.Context):
    if not drive.creds or not drive.creds.valid:
        if drive.creds and drive.creds.expired and drive.creds.refresh_token:
            drive.log.info("Refreshing credentials")
            await run_sync(drive.creds.refresh, Request())

            credential = await run_sync(pickle.dumps, drive.creds)
            async with drive.lock:
                await drive.db.update_one(
                    {"_id": ctx.bot.uid},
                    {
                        "$set": {"creds": credential}
                    }
                )
        else:
            await ctx.respond("Credential is empty, generating...")
            await asyncio.sleep(1.5)  # give people time to read

            ret = await drive.get_access_token(ctx)

            await ctx.respond(ret)

    drive.service = build(
        "drive",
        "v3",
        credentials=drive.creds,
        cache_discovery=False
    )
