import asyncio
import pickle
from functools import wraps
from random import choice
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    ClassVar,
    Coroutine,
    List,
    Mapping,
    Optional,
    Tuple,
    Union,
)

from bson.binary import Binary
from google.auth import external_account_authorized_user
from google.auth.transport.requests import Request
from google.oauth2 import credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError
from pyrogram.types import Message

from caligo import command, module, util
from caligo.core import database

MAX_PROJECTS = 12
MAX_ACCOUNTS = 100
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/iam",
]


def _run_async(func: Callable[..., Any]) -> Callable[..., Coroutine[Any, Any, Any]]:
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return await util.run_sync(func, *args, **kwargs)

    return wrapper


def check(func: command.CommandFunc):
    @wraps(func)
    async def wrapper(self: "GoogleAPI", ctx: command.Context) -> Optional[str]:
        if self.creds and self.creds.expired and self.creds.refresh_token:
            self.log.info("Refreshing credentials")
            await util.run_sync(self.creds.refresh, Request())

            credential = await util.run_sync(pickle.dumps, self.creds)
            await self.db.update_one(
                {"_id": 0}, {"$set": {"creds": Binary(credential)}}
            )
        else:
            if not self.creds or not self.creds.valid:
                await ctx.respond("Credential is empty, generating...")

                ret = await self.get_access_token(ctx.msg)
                await ctx.respond(ret)

                if not self.creds:
                    return

                await ctx.respond("Enabling services...")

                err_str = "⚠️ **Problem enabling service '{service}'**\nPlease enable it manually."
                for service in {"iam", "drive"}:
                    try:
                        response = await _run_async(self.enable_service)(
                            self.project_id, service
                        )
                    except HttpError:
                        await ctx.respond(err_str.format(service=service))
                        continue

                    if not response["done"]:
                        await ctx.respond(
                            err_str.format(service=service)
                            + "\n\n__Some operation took longer to complete.__"
                        )
                        continue

        return await func(self, ctx)

    return wrapper


class GoogleAPI(module.Module):
    name: ClassVar[str] = "Google API"

    db: database.AsyncCollection
    project_id: str

    creds: Union[credentials.Credentials, external_account_authorized_user.Credentials]
    drive: Any
    cloud: Resource
    iam: Resource
    serviceusage: Resource

    @_run_async
    def _create_project(self) -> Tuple[str, Mapping[str, Any]]:
        project = self._generate_id()
        response = self.cloud.projects().create(body={"projectId": project}).execute()
        return project, response

    async def _create_projects(self, amount: int) -> AsyncGenerator[str, None]:
        count = 0
        while count != amount:
            project, response = await self._create_project()
            while True:
                if response["done"]:
                    yield project
                    count += 1
                    break

                await asyncio.sleep(3.5)
                response = await self._get_project(project)
                continue

    @_run_async
    def _create_service_account(self, project_id: str) -> int:
        uid = self._generate_id()
        self.iam.projects().serviceAccounts().create(
            name=f"projects/{project_id}",
            body={"accountId": uid, "serviceAccount": {"displayName": uid}},
        ).execute()
        return 1

    async def _create_service_accounts(self, project_id: str) -> None:
        sas = len(await self._get_service_accounts(project_id))
        while sas != MAX_ACCOUNTS:
            try:
                sas += await self._create_service_account(project_id)
            except HttpError as e:
                if e.resp.status == 429:
                    await asyncio.sleep(0.3)
                    continue

                self.log.debug("Error creating service account '%d':", sas, exc_info=e)
                await asyncio.sleep(1)

    @_run_async
    def _delete_service_account(self, name: str) -> None:
        self.iam.projects().serviceAccounts().delete(name=name).execute()

    async def _delete_service_accounts(self, project_id: str) -> None:
        list_sa = await self._get_service_accounts(project_id)
        for sa in list_sa:
            while True:
                try:
                    await self._delete_service_account(sa["name"])
                except HttpError as e:
                    if e.resp.status == 429:
                        await asyncio.sleep(0.3)
                        continue
                else:
                    break

    @staticmethod
    def _generate_id(prefix="clg-") -> str:
        chars = "-abcdefghijklmnopqrstuvwxyz1234567890"
        return prefix + "".join(choice(chars) for _ in range(25)) + choice(chars[1:])

    @_run_async
    def _get_service_accounts(self, project_id: str) -> List[Mapping[str, Any]]:
        response = (
            self.iam.projects()
            .serviceAccounts()
            .list(name=f"projects/{project_id}", pageSize=100)
            .execute()
        )
        try:
            return response["accounts"]
        except KeyError:
            return []

    @_run_async
    def _get_project(self, project_id: str) -> Mapping[str, Any]:
        return self.cloud.operations().get(name=project_id).execute()

    @_run_async
    def _get_projects(self) -> Mapping[str, str]:
        while True:
            try:
                response: Mapping[str, Any] = self.cloud.projects().list().execute()
            except HttpError as e:
                if e.resp.status == 403:
                    self.enable_service(
                        self.project_id,
                        "cloudresourcemanager",
                    )
                    continue

                raise

            return response["projects"]

    async def on_load(self):
        self.db = self.bot.db.get_collection(self.name.upper())
        self.creds = None  # type: ignore
        self.project_id = self.bot.config["googleapis"]["project_id"]

        data = await self.db.find_one({"_id": 0})
        if not data:
            return

        self.creds = await util.run_sync(pickle.loads, data["creds"])

        self.cloud, self.drive, self.iam, self.serviceusage = await asyncio.gather(
            util.run_sync(
                build,
                "cloudresourcemanager",
                "v1",
                credentials=self.creds,
                cache_discovery=False,
            ),
            util.run_sync(
                build, "drive", "v3", credentials=self.creds, cache_discovery=False
            ),
            util.run_sync(
                build, "iam", "v1", credentials=self.creds, cache_discovery=False
            ),
            util.run_sync(
                build,
                "serviceusage",
                "v1",
                credentials=self.creds,
                cache_discovery=False,
            ),
        )

    async def get_access_token(self, message: Message) -> str:
        flow = InstalledAppFlow.from_client_config(
            {"installed": self.bot.config["googleapis"]},
            SCOPES,
            redirect_uri=self.bot.config["googleapis"]["redirect_uris"][0],
        )
        auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")

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
                return "⚠️ __Timeout no token received.__"

        await self.bot.respond(message, "Token received...")
        token = response.text

        try:
            await asyncio.gather(
                request.delete(),
                response.delete(),
                util.run_sync(flow.fetch_token, code=token),
            )
        except InvalidGrantError:
            return (
                "⚠️ **Error fetching token**\n\n"
                "__Refresh token is invalid, expired, revoked, "
                "or does not match the redirection URI.__"
            )

        self.creds = flow.credentials
        await self.db.update_one(
            {"_id": 0},
            {"$set": {"creds": Binary(await util.run_sync(pickle.dumps, self.creds))}},
            upsert=True,
        )
        await self.on_load()

        return "Credentials created."

    # Not async because some methods called this func already inside _run_async
    def enable_service(self, project_id: str, name: str) -> Mapping[str, Any]:
        return (
            self.serviceusage.services()
            .enable(name=f"projects/{project_id}/services/{name}.googleapis.com")
            .execute()
        )

    @check
    @command.desc("Check your Google credentials")
    @command.alias("gauth")
    async def cmd_gcheck(self, ctx: command.Context) -> str:  # skipcq: PYL-W0613
        return "Credentials is valid."

    @command.desc("Clear/Reset your Google credentials")
    @command.alias("greset")
    async def cmd_gclear(self, ctx: command.Context) -> Optional[str]:
        if not self.creds:
            await ctx.respond("Credentials already empty.", delete_after=3)
            return

        await self.db.delete_one({"_id": 0})
        await asyncio.gather(
            self.on_load(), ctx.respond("Credentials cleared.", delete_after=3)
        )

    @check
    @command.usage("[project_id?]", optional=True)
    @command.desc(
        "List service account on project (if not specified, it will list on all projects)"
    )
    async def cmd_glist_sas(self, ctx: command.Context) -> None:
        project = ctx.input or self.bot.config["googleapis"]["project_id"]
        self.log.info(await self._get_service_accounts(project))

    @check
    @command.usage("[project_id?]", optional=True)
    @command.desc(
        "Create service accounts on a projects (if not specified, it will create on all projects)"
    )
    async def cmd_gmk_sa(self, ctx: command.Context) -> None:
        project = ctx.input or self.project_id
        self.log.info(await self._create_service_accounts(project))
