import inspect
from typing import TYPE_CHECKING, Any, Iterable, MutableMapping, Optional

from pyrogram.client import Client
from pyrogram.errors import MessageNotModified
from pyrogram.filters import Filter, create
from pyrogram.types import Message

from caligo import command, module, util

from .base import CaligoBase

if TYPE_CHECKING:
    from .bot import Caligo


class CommandDispatcher(CaligoBase):
    commands: MutableMapping[str, command.Command]

    def __init__(self: "Caligo", **kwargs: Any) -> None:
        self.commands = {}

        super().__init__(**kwargs)

    def register_command(
        self: "Caligo",
        mod: module.Module,
        name: str,
        func: command.CommandFunc,
        filters: Optional[Filter] = None,
        desc: Optional[str] = None,
        usage: Optional[str] = None,
        usage_optional: bool = False,
        usage_reply: bool = False,
        aliases: Iterable[str] = [],
    ) -> None:
        if getattr(func, "_listener_filters", None):
            self.log.warning(
                "@listener.filters decorator only for ListenerFunc. Filters will be ignored..."
            )

        if filters:
            self.log.debug(
                "Registering filter '%s' into '%s'", type(filters).__name__, name
            )

        cmd = command.Command(
            name, mod, func, filters, desc, usage, usage_optional, usage_reply, aliases
        )

        if name in self.commands:
            orig = self.commands[name]
            raise module.ExistingCommandError(orig, cmd)

        self.commands[name] = cmd

        for alias in cmd.aliases:
            if alias in self.commands:
                orig = self.commands[alias]
                raise module.ExistingCommandError(orig, cmd, alias=True)

            self.commands[alias] = cmd

    def unregister_command(self: "Caligo", cmd: command.Command) -> None:
        del self.commands[cmd.name]

        for alias in cmd.aliases:
            try:
                del self.commands[alias]
            except KeyError:
                continue

    def register_commands(self: "Caligo", mod: module.Module) -> None:
        for name, func in util.misc.find_prefixed_funcs(mod, "cmd_"):
            done = False

            try:
                self.register_command(
                    mod,
                    name,
                    func,
                    filters=getattr(func, "_cmd_filters", None),
                    desc=getattr(func, "_cmd_description", None),
                    usage=getattr(func, "_cmd_usage", None),
                    usage_optional=getattr(func, "_cmd_usage_optional", False),
                    usage_reply=getattr(func, "_cmd_usage_reply", False),
                    aliases=getattr(func, "_cmd_aliases", []),
                )
                done = True
            finally:
                if not done:
                    self.unregister_commands(mod)

    def unregister_commands(self: "Caligo", mod: module.Module) -> None:
        to_unreg = []

        for name, cmd in self.commands.items():
            if name != cmd.name:
                continue

            if cmd.module == mod:
                to_unreg.append(cmd)

        for cmd in to_unreg:
            self.unregister_command(cmd)

    def command_predicate(self: "Caligo") -> Filter:
        async def func(_: Filter, client: Client, message: Message) -> bool:
            if message.via_bot:
                return False

            if message.text is not None and message.text.startswith(self.prefix):
                parts = message.text.split()
                parts[0] = parts[0][len(self.prefix) :]  # Remove prefix

                # Filter if command is not in commands
                try:
                    cmd = self.commands[parts[0]]
                except KeyError:
                    return False

                # Check additional built-in filters
                if cmd.filters:
                    if inspect.iscoroutinefunction(cmd.filters.__call__):
                        if not await cmd.filters(client, message):
                            return False
                    else:
                        if not await util.run_sync(cmd.filters, client, message):
                            return False

                message.command = parts
                return True

            return False

        return create(func, "CustomCommandFilter")

    async def on_command(self: "Caligo", _: Client, message: Message) -> None:
        cmd = self.commands[message.command[0]]
        try:
            # Construct invocation context
            ctx = command.Context(
                self,
                message,
                len(self.prefix) + len(message.command[0]) + 1,
            )

            try:
                ret = await cmd.func(ctx)
                if ret is not None:
                    await ctx.respond(ret)
            except MessageNotModified:
                cmd.module.log.warning(
                    f"Command '{cmd.name}' triggered a message edit with no changes"
                )
            except Exception as e:  # skipcq: PYL-W0703
                cmd.module.log.error(f"Error in command '{cmd.name}'", exc_info=e)
                await ctx.respond(
                    "**In**:\n"
                    f"{ctx.input if ctx.input is not None else message.text}\n\n"
                    "**Out**:\n⚠️ Error executing command:\n"
                    f"```{util.error.format_exception(e)}```"
                )

            await self.dispatch_event("command", cmd, message)
        except Exception as e:  # skipcq: PYL-W0703
            cmd.module.log.error("Error in command handler", exc_info=e)
            await self.respond(
                message,
                "⚠️ Error in command handler:\n"
                f"```{util.error.format_exception(e)}```",
            )
        finally:
            message.continue_propagation()
