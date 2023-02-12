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

MAX_ACCOUNTS = 100
MAX_PROJECTS = 12
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


async def progress_gen(
    message: str, ctx: command.Context
) -> AsyncGenerator[None, None]:
    i = 0
    while True:
        for x in range(0, 4):
            dots = "." * x
            i += 1

            await ctx.respond(message + dots)
            await asyncio.sleep(3)

        yield


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

                    if not response.get("done", False):
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

    async def _create_projects(self, amount: int) -> List[str]:
        projects = []
        count = 0
        while count != amount:
            project, response = await self._create_project()
            while True:
                err = response.get("error", None)
                if err and err["code"] == 8:
                    return []

                if response.get("done", False):
                    count += 1
                    projects.append(f"`{project}`")
                    break

                await asyncio.sleep(3.5)
                response = await self._get_project(response["name"])
                continue

        return projects

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
    def _generate_id(prefix="caligo-") -> str:
        chars = "-abcdefghijklmnopqrstuvwxyz1234567890"
        return prefix + "".join(choice(chars) for _ in range(15)) + choice(chars[1:])

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
    def _get_projects(self) -> List[Mapping[str, str]]:
        while True:
            try:
                response: Mapping[str, Any] = (
                    self.cloud.projects().list(filter="lifecycleState:ACTIVE").execute()
                )
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
        await self.db.delete_one({"_id": 0})
        await asyncio.gather(
            self.on_load(), ctx.respond("Credentials cleared.", delete_after=3)
        )

    @check
    @command.desc("Get list of projects")
    async def cmd_gls_project(self, ctx: command.Context) -> str:
        projects = await self._get_projects()
        return "**Existing projects**:\n    • " + "\n    • ".join(
            [f"`{project['projectId']}`" for project in projects]
        )

    @check
    @command.usage("[project_id?]", optional=True)
    @command.desc(
        "List service account on project (if not specified, it will list on default project)"
    )
    async def cmd_gls_sas(self, ctx: command.Context) -> str:
        project = ctx.input or self.project_id
        return util.tg.pretty_print_entity(await self._get_service_accounts(project))

    @check
    @command.usage("[project_id?]", optional=True)
    @command.desc(
        "Create service accounts on a project (if not specified, it will create on all projects)"
    )
    async def cmd_gmk_sas(self, ctx: command.Context) -> None:
        projects = [ctx.input] if ctx.input else await self._get_projects()
        start_time = util.time.usec()
        for project in projects:
            uid = project if isinstance(project, str) else project["projectId"]

            task = self.bot.loop.create_task(self._create_service_accounts(uid))
            progress = progress_gen(f"Creating", ctx)
            while not task.done():
                await progress.__anext__()

            await progress.aclose()

        end_time = util.time.usec()

        await ctx.respond(
            "Done."
            + f"\n\nTime elapsed: {util.time.format_duration_us(end_time - start_time)}",
            delete_after=3,
        )

    @check
    @command.usage(f"[amount (max: {MAX_PROJECTS})]")
    @command.desc("Create new amount of project(s) [1-12]")
    async def cmd_gmk_project(self, ctx: command.Context) -> str:
        if not ctx.input:
            return "Please specify the amount of project to create."

        try:
            amount = int(ctx.input)
        except ValueError:
            return "Please specify a valid number."

        if amount > MAX_PROJECTS or amount < 1:
            return f"Please specify a number greater than **0** and less than **{MAX_PROJECTS}**."

        start_time = util.time.usec()
        plural = "s" if amount > 1 else ""

        current_amount = len(await self._get_projects())
        if current_amount + amount > MAX_PROJECTS:
            return (
                "⚠️ **Error creating projects**\n\n"
                f"__You can't create '{amount}' project{plural} because it will exceed the maximum amount of projects ({MAX_PROJECTS})."
                f"\nYou currently have '{current_amount}' project{plural}__."
            )

        await ctx.respond(f"Creating '{amount}' project{plural}...")

        projects = await self._create_projects(amount)
        if not projects:
            return "⚠️ **Error creating projects**\n\n__You've reached your project limit. You can create more projects after you [request a project limit increase](https://support.google.com/code/contact/project_quota_increase). Alternatively, you can schedule some projects to be deleted after 30 days on the [Manage Resources Page](https://console.cloud.google.com/cloud-resource-manager)__."

        end_time = util.time.usec()
        return (
            f"Created '{amount}' project{plural}:\n    • "
            + "\n    • ".join(projects)
            + f"\n\nTime elapsed: {util.time.format_duration_us(end_time - start_time)}"
        )
