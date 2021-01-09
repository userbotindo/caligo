import inspect
import importlib

from types import ModuleType
from typing import Any, Iterable, MutableMapping, Optional, Type

from .. import module, modules, util
from .base import Base


class ModuleExtender(Base):
    modules: MutableMapping[str, module.Module]

    def __init__(self, **kwargs: Any) -> None:
        self.modules = {}

        super().__init__(**kwargs)

    def load_module(
        self, cls: Type[module.Module], *, comment: Optional[str] = None
    ) -> None:
        self.log.info(f"Loading {cls.format_desc(comment)}")

        if cls.name in self.modules:
            old = type(self.modules[cls.name])
            raise module.ExistingModuleError(old, cls)

        mod = cls(self)
        mod.comment = comment
        self.modules[cls.name] = mod

    def unload_module(self, mod: module.Module) -> None:
        cls = type(mod)
        self.log.info(f"Unloading {mod.format_desc(mod.comment)}")

        del self.modules[cls.name]

    def _load_all_from_metamod(
        self, submodules: Iterable[ModuleType], *, comment: str = None
    ) -> None:
        for module_mod in submodules:
            for sym in dir(module_mod):
                cls = getattr(module_mod, sym)
                if (
                    inspect.isclass(cls)
                    and issubclass(cls, module.Module)
                    and not cls.disabled
                ):
                    self.load_module(cls, comment=comment)

    # noinspection PyTypeChecker,PyTypeChecker
    def load_all_modules(self) -> None:
        self.log.info("Loading modules")
        self._load_all_from_metamod(self.submodules)
        self.log.info("All modules loaded.")

    def unload_all_modules(self) -> None:
        self.log.info("Unloading modules...")

        # Can't modify while iterating, so collect a list first
        for mod in list(self.modules.values()):
            self.unload_module(mod)

        self.log.info("All modules unloaded.")

    async def reload_module_pkg(self) -> None:
        self.log.info("Reloading base module class...")
        await util.run_sync(importlib.reload, module)

        self.log.info("Reloading master module...")
        await util.run_sync(importlib.reload, modules)

    async def _get_cmd(self, *args, **kwargs) -> str:

        for mod in self.submodules:
            for sym in dir(mod):
                cls = getattr(mod, sym)
                if (
                    inspect.isclass(cls)
                    and issubclass(cls, module.Module)
                    and not cls.disabled
                ):
                    for name, func in util.misc.find_prefixed_funcs(cls, "cmd_"):
                        self.log.info(name)
                        self.log.info(func._cmd)
                        self.log.info(func._cmd_description)
                        self.log.info(func._cmd_usage)
