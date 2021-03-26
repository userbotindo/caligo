import asyncio
from datetime import timedelta
from mimetypes import guess_type
from pathlib import Path
from urllib import parse
from typing import Optional, Tuple, Union

from async_property import async_property

from .async_helpers import run_sync
from .misc import human_readable_bytes as human
from .time import format_duration_td as time, sec


class File:

    def __init__(self, path: Path) -> None:
        self._path = path

        self._name = ""
        self._content = None
        self._invoker = None
        self._index_link = None
        self._start_time = None

    @property
    def name(self) -> str:
        if not self._name:
            filePath = str(self._path.absolute())
            dirPath = str(self._path.parent.absolute())
            if filePath.startswith(dirPath):
                start = len(dirPath) + 1
                self._name = Path(filePath[start:]).parts[0]
            else:
                self._name = self._path.parts[-1]

        return self._name

    @property
    def path(self) -> Path:
        return self._path

    @property
    def dir(self) -> Path:
        return self.path.parent.absolute()

    @property
    def mime_type(self) -> str:
        return guess_type(self.path)[0]

    @property
    def content(self) -> None:
        return self._content

    @content.setter
    def content(self, val):
        self._content = val

    @property
    def invoker(self) -> None:
        return self._invoker

    @invoker.setter
    def invoker(self, val):
        self._invoker = val

    @property
    def index_link(self) -> None:
        if self._index_link is not None:
            if self._index_link.endswith("/"):
                link = self._index_link + parse.quote(self.name)
            else:
                link = self._index_link + "/" + parse.quote(self.name)

        return self._index_link if self._index_link is None else link

    @index_link.setter
    def index_link(self, val):
        self._index_link = val

    @property
    def start_time(self) -> None:
        return self._start_time

    @start_time.setter
    def start_time(self, val):
        self._start_time = val

    @async_property
    async def progress_string(self) -> Tuple[Union[str, None], bool, None]:
        file = self.content
        status, response = await run_sync(file.next_chunk)
        if status:
            after = sec() - self.start_time
            size = status.total_size
            current = status.resumable_progress
            percent = current / size
            speed = round(current / after, 2)
            eta = timedelta(seconds=int(round((size - current) / speed)))
            bullets = "●" * int(round(percent * 10)) + "○"
            if len(bullets) > 10:
                bullets = bullets.replace("○", "")

            space = '    ' * (10 - len(bullets))
            progress = (
                f"`{self.name}`\n"
                f"Status: **Uploading**\n"
                f"Progress: [{bullets + space}] {round(percent * 100)}%\n"
                f"__{human(current)} of {human(size)} @ "
                f"{human(speed, postfix='/s')}\neta - {time(eta)}__\n\n")

        if response is None:
            return progress, False, None

        size = response.get("size")
        mirrorLink = response.get("webContentLink")
        text = (f"**GoogleDrive Link**: [{self.name}]({mirrorLink}) "
                f"(__{human(int(size))}__)")
        if self._index_link is not None:
            text += f"\n\n__Shareable link__: [Here]({self._index_link})."

        return None, True, text

    async def progress(self, update: Optional[bool] = True) -> None:
        invoker = self.invoker

        done = False
        while not done:
            progress, done, link = await self.progress_string
            if invoker is not None and progress is not None:
                await invoker.edit(progress)

                await asyncio.sleep(5)
                continue

            await asyncio.sleep(1)

        if invoker is not None and update is True:
            await invoker.reply(link)
            await invoker.delete()
