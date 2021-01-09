import inspect
import logging
import os.path
import importlib
import pkgutil

from typing import (
    ClassVar,
    Optional,
)
submodules = [
    importlib.import_module("roboto.modules." + info.name, __name__)
    for info in pkgutil.iter_modules(["roboto/modules"])
]


class Module:
    # Class variables
    name: ClassVar[str] = "Unnamed"
    disabled: ClassVar[bool] = False

    # Instance variables
    log: logging.Logger
    comment: Optional[str]

    def __init__(self, bot) -> None:
        self.bot = bot
        self.log = logging.getLogger(type(self).name.lower().replace(" ", "_"))
        self.comment = None

    @classmethod
    def format_desc(cls, comment: Optional[str] = None):
        _comment = comment + " " if comment else ""
        return f"{_comment}module '{cls.name}' ({cls.__name__}) from '{os.path.relpath(inspect.getfile(cls))}'"

    def __repr__(self):
        return "<" + self.format_desc(self.comment) + ">"


class ModuleLoadError(Exception):
    pass
