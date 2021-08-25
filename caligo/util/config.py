import json
import os
from pathlib import Path
from typing import Any, ClassVar, Iterator, MutableMapping, TypeVar

from aiopath import AsyncPath

_KT = TypeVar("_KT", bound=str, contravariant=True)
_VT = TypeVar("_VT", covariant=True)


class TelegramConfig(MutableMapping[_KT, _VT]):

    __data: ClassVar[MutableMapping[_KT, Any]] = {}

    def __init__(self) -> None:

        config: MutableMapping[_KT, Any] = {
            "api_id": os.environ.get("API_ID"),
            "api_hash": os.environ.get("API_HASH"),
            "bot_token": os.environ.get("BOT_TOKEN"),
            "container": os.environ.get("CONTAINER") == "True",
            "db_uri": os.environ.get("DB_URI"),
            "download_path": os.environ.get("DOWNLOAD_PATH"),
            "gdrive_folder_id": os.environ.get("G_DRIVE_FOLDER_ID"),
            "gdrive_index_link": os.environ.get("G_DRIVE_INDEX_LINK"),
            "gdrive_secret": os.environ.get("G_DRIVE_SECRET"),
            "github_repo": os.environ.get("GITHUB_REPO"),
            "github_token": os.environ.get("GITHUB_TOKEN"),
            "heroku_api_key": os.environ.get("HEROKU_API_KEY"),
            "heroku_app_name": os.environ.get("HEROKU_APP"),
            "mirror_enabled": os.environ.get("MIRROR_MODULE") == "enable",
            "string_session": os.environ.get("STRING_SESSION"),
        }

        for key, value in config.items():
            if not value:
                if key == "download_path":
                    value = AsyncPath(Path.home() / "downloads")
                elif key == "github_repo":
                    value = "adekmaulana/caligo"

                if value == "":
                    value = None
            else:
                if key == "download_path":
                    value = AsyncPath(value)
                elif key == "gdrive_index_link":
                    value = value.rstrip("/")
                elif key == "gdrive_secret":
                    value = json.loads(value)

            super().__setattr__(key, value)
            self.__data[key] = value

    def __delattr__(self, obj: object) -> None:  # skipcq: PYL-W0613
        raise RuntimeError("Can't delete configuration while running the bot.")

    def __delitem__(self, k: _KT) -> None:  # skipcq: PYL-W0613
        raise RuntimeError("Can't delete configuration while running the bot.")

    def __getattr__(self, name: str) -> _VT:
        return self.__getattribute__(name)

    def __getitem__(self, k: _KT) -> _VT:
        return self.__data[k]

    def __iter__(self) -> Iterator[_KT]:
        return self.__data.__iter__()

    def __len__(self) -> int:
        return len(self.__data)

    def __setattr__(self, name: str, value: Any) -> None:  # skipcq: PYL-W0613
        raise RuntimeError("Configuration must be done before running the bot.")

    def __setitem__(self, k: str, v: Any) -> None:  # skipcq: PYL-W0613
        raise RuntimeError("Configuration must be done before running the bot.")
