import inspect
from typing import TYPE_CHECKING, Any, Iterable, MutableMapping, Optional

from pyrogram.client import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.filters import Filter, create
from pyrogram.types import Message

from caligo import command, module, util

from .base import CaligoBase

if TYPE_CHECKING:
    from .bot import Caligo


HTML_TAGS = (
    "<blockquote",
    "<b>",
    "<code>",
    "<pre",
    "<i>",
    "<spoiler",
    "<u>",
    "<s>",
)


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
        no_processing: bool = False,
        no_autodel: bool = False,
        opts: Optional[dict[str, Any]] = None,
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
            name,
            mod,
            func,
            filters,
            desc,
            usage,
            usage_optional,
            usage_reply,
            aliases,
            no_processing=no_processing,
            no_autodel=no_autodel,
            opts=opts,
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
                    no_processing=getattr(func, "_cmd_no_processing", False),
                    no_autodel=getattr(func, "_cmd_no_autodel", False),
                    opts=getattr(func, "_cmd_opts", None),
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

            text = message.text
            if text is not None and text.startswith(self.prefix):
                after_prefix = text[len(self.prefix):]
                if not after_prefix:
                    return False

                first_words = after_prefix.split(maxsplit=1)
                if not first_words:
                    return False

                # Filter if command is not in commands
                try:
                    cmd = self.commands[first_words[0]]
                except KeyError:
                    return False

                parts = text.split()
                parts[0] = first_words[0]

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

            # Show processing message if global processing is enabled and command doesn't opt out
            proc_status = getattr(self, "processing_status", None)
            mod = getattr(cmd, "module", None)
            mod_opts = (
                getattr(mod, "opts", None)
                if isinstance(getattr(mod, "opts", None), dict)
                else {}
            )
            skip_proc = (
                getattr(cmd, "no_processing", False) is True
                or getattr(cmd.func, "_cmd_no_processing", False) is True
                or getattr(mod, "_cmd_no_processing", False) is True
                or mod_opts.get("processing") is False
                or mod_opts.get("raw") is True
                or cmd.name == "ping"
                or "ping" in getattr(cmd, "aliases", ())
            )
            if proc_status and not skip_proc:
                proc_text = (
                    proc_status
                    if isinstance(proc_status, str)
                    else "__Processing...__"
                )
                try:
                    await ctx.respond(proc_text)
                except Exception as e:
                    self.log.debug(f"Failed to show processing status: {e}")

            skip_autodel = (
                getattr(cmd, "no_autodel", False) is True
                or getattr(cmd.func, "_cmd_no_autodel", False) is True
                or getattr(mod, "_cmd_no_autodel", False) is True
                or mod_opts.get("autodel") is False
                or mod_opts.get("raw") is True
            )
            del_after = getattr(self, "delete_after", None) if not skip_autodel else None

            try:
                ret = await cmd.func(ctx)
                if ret is not None:
                    kwargs: dict[str, Any] = {}
                    if isinstance(ret, str) and any(tag in ret for tag in HTML_TAGS):
                        kwargs["parse_mode"] = ParseMode.HTML

                    if del_after:
                        kwargs["delete_after"] = del_after

                    await ctx.respond(ret, **kwargs)
                elif del_after and ctx.response:
                    if not ctx._delete_task or ctx._delete_task.done():
                        await ctx._delete(delay=del_after)
            except MessageNotModified:
                cmd.module.log.warning(
                    f"Command '{cmd.name}' triggered a message edit with no changes"
                )
            except FloodWait as e:
                cmd.module.log.warning(
                    f"Command '{cmd.name}' hit FloodWait of {e.value} seconds; waiting..."
                )
                await asyncio.sleep(e.value + 1)
                try:
                    ret = await cmd.func(ctx)
                    if ret is not None:
                        kwargs = {}
                        if isinstance(ret, str) and any(tag in ret for tag in HTML_TAGS):
                            kwargs["parse_mode"] = ParseMode.HTML

                        if del_after:
                            kwargs["delete_after"] = del_after

                        await ctx.respond(ret, **kwargs)
                    elif del_after and ctx.response:
                        if not ctx._delete_task or ctx._delete_task.done():
                            await ctx._delete(delay=del_after)
                except Exception as retry_err:  # skipcq: PYL-W0703
                    cmd.module.log.error(
                        f"Error in command '{cmd.name}' after FloodWait retry",
                        exc_info=retry_err,
                    )
            except Exception as e:  # skipcq: PYL-W0703
                cmd.module.log.error(f"Error in command '{cmd.name}'", exc_info=e)
                err_kwargs: dict[str, Any] = {}
                if del_after:
                    err_kwargs["delete_after"] = del_after

                await ctx.respond(
                    "**In**:\n"
                    f"{ctx.input if ctx.input is not None else message.text}\n\n"
                    "**Out**:\n⚠️ Error executing command:\n"
                    f"```{util.error.format_exception(e)}```",
                    **err_kwargs,
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
